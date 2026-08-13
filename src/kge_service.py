import os
import re
import pickle
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from collections import defaultdict

import numpy as np
import networkx as nx

from src.graph_enricher import load_enriched_graph
from src.kge_model import RotatEModel
from src.recommender_sentence import normalize, get_model, JOB_EMB_ARRAY, JOB_NODE_IDS, JOB_METAS


CACHE_DIR = Path(__file__).parent.parent / "data"
KG_VECTOR_CACHE = CACHE_DIR / "kg_entity_vectors.pkl"
KGE_EMBEDDINGS_PATH = CACHE_DIR / "kge_embeddings.pkl"


class KgeService:
    def __init__(self, G: Optional[nx.Graph] = None):
        self.G = G
        self._entity_vectors: Dict[str, np.ndarray] = {}
        self._sbert_model = None
        self._rotate_model: Optional[RotatEModel] = None

    def _get_sbert(self):
        if self._sbert_model is None:
            self._sbert_model = get_model()
        return self._sbert_model

    def _load_rotate(self):
        if self._rotate_model is not None:
            return self._rotate_model
        try:
            self._rotate_model = RotatEModel.load(KGE_EMBEDDINGS_PATH)
            print(f"[OK] RotatE model loaded ({self._rotate_model.n_entities} entities, dim={self._rotate_model.dim})")
        except Exception as e:
            print(f"[!] RotatE model load failed: {e}")
        return self._rotate_model

    @classmethod
    def build(cls, G: Optional[nx.Graph] = None, force_refresh: bool = False) -> "KgeService":
        if G is None:
            G = load_enriched_graph()

        svc = cls(G=G)
        svc._load_rotate()

        if not force_refresh and KG_VECTOR_CACHE.exists():
            try:
                with open(KG_VECTOR_CACHE, "rb") as f:
                    svc._entity_vectors = pickle.load(f)
                print(f"[OK] Loaded {len(svc._entity_vectors)} KG entity vectors from cache")
                return svc
            except Exception as e:
                print(f"[!] Cache load failed: {e}")

        t0 = time.time()

        model = svc._get_sbert()
        texts = []
        ids = []

        for n, d in G.nodes(data=True):
            ntype = d.get("type", "")
            if ntype in ("job", "skill", "industry", "qualification", "certification"):
                label = d.get("label", "") or d.get("job_title", "") or n
                label = normalize(str(label))
                if label and len(label) > 1:
                    prefix_map = {"skill": "skill", "job": "job", "industry": "industry", "qualification": "qualification", "certification": "certification"}
                    prefix = prefix_map.get(ntype, "")
                    texts.append(f"{prefix}: {label}" if prefix else label)
                    ids.append(n)

        if texts:
            batch_size = min(256, max(32, len(texts) // 20))
            embs = model.encode(texts, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=True)
            norms = np.linalg.norm(embs, axis=1, keepdims=True)
            embs = embs / (norms + 1e-12)

            for i, nid in enumerate(ids):
                svc._entity_vectors[nid] = embs[i]

        try:
            with open(KG_VECTOR_CACHE, "wb") as f:
                pickle.dump(svc._entity_vectors, f)
            print(f"[OK] Cached {len(svc._entity_vectors)} entity vectors")
        except Exception as e:
            print(f"[!] Cache save failed: {e}")

        print(f"[OK] Built {len(svc._entity_vectors)} entity vectors in {time.time()-t0:.1f}s")
        return svc

    def get_entity_vector(self, entity_id: str) -> Optional[np.ndarray]:
        vec = self._entity_vectors.get(entity_id)
        if vec is not None:
            return vec
        if JOB_EMB_ARRAY is not None and entity_id in JOB_NODE_IDS:
            idx = JOB_NODE_IDS.index(entity_id) if entity_id in JOB_NODE_IDS else -1
            if idx >= 0 and idx < len(JOB_EMB_ARRAY):
                return JOB_EMB_ARRAY[idx]
        return None

    def compute_kg_similarity(self, entity_a: str, entity_b: str) -> float:
        va = self._entity_vectors.get(entity_a)
        vb = self._entity_vectors.get(entity_b)
        if va is None or vb is None:
            return 0.0
        return float(np.dot(va, vb))

    def compute_rotate_score_for_job(
        self,
        user_skills_set: Set[str],
        job_node_id: str,
    ) -> float:
        """Compute KG score using actual RotatE entity embeddings.

        RotatE embeddings live in a complex vector space optimized for relation
        prediction, not semantic similarity. We compute pairwise cosine similarities
        between the job and its skill neighbors, then min-max normalize within the
        job's neighborhood to get a [0, 1] score. User-matched skills get a boost.
        """
        rotate = self._load_rotate()
        if rotate is None:
            return 0.0

        job_emb = rotate.get_entity_embedding_vector(job_node_id)
        if job_emb is None:
            return 0.0

        job_norm = np.linalg.norm(job_emb)
        if job_norm == 0:
            return 0.0

        if self.G and job_node_id in self.G:
            neighbor_skills = set()
            for nb in nx.neighbors(self.G, job_node_id):
                if self.G.nodes[nb].get("type") == "skill":
                    neighbor_skills.add(nb)
        else:
            neighbor_skills = set()

        if not neighbor_skills:
            return 0.0

        raw_sims = []
        for sn in neighbor_skills:
            label = self.G.nodes[sn].get("label", sn) if self.G and sn in self.G else sn
            label_norm = normalize(str(label))
            user_match = any(us in label_norm or label_norm in us for us in user_skills_set)

            skill_emb = rotate.get_entity_embedding_vector(sn)
            if skill_emb is None:
                continue

            skill_norm = np.linalg.norm(skill_emb)
            if skill_norm == 0:
                continue

            cos_sim = float(np.dot(skill_emb, job_emb) / (job_norm * skill_norm))
            raw_sims.append((cos_sim, user_match, label_norm))

        if not raw_sims:
            return 0.0

        cos_vals = np.array([s[0] for s in raw_sims])
        cmin, cmax = float(cos_vals.min()), float(cos_vals.max())
        crange = cmax - cmin if cmax > cmin else 1.0

        normalized = []
        for cos_sim, user_match, label_norm in raw_sims:
            norm_sim = (cos_sim - cmin) / crange
            norm_sim = max(0.0, min(1.0, norm_sim))
            normalized.append((norm_sim, user_match, label_norm))

        normalized.sort(key=lambda x: -x[0])

        user_matched = [s for s, matched, _ in normalized if matched]
        all_top = [s for s, _, _ in normalized[:5]]

        if user_matched:
            return 0.6 * max(user_matched) + 0.4 * float(np.mean(user_matched[:3]))
        else:
            return float(np.mean(all_top[:3])) * 0.5

    def compute_enhanced_hybrid_score(
        self,
        user_embedding: np.ndarray,
        job_embedding: np.ndarray,
        user_skills_set: Set[str],
        job_skills_list: List[str],
        job_node_id: str,
        alpha: float = 0.5,
        beta: float = 0.25,
    ) -> float:
        from sklearn.metrics.pairwise import cosine_similarity

        cos_sim = float(cosine_similarity(
            user_embedding.reshape(1, -1), job_embedding.reshape(1, -1)
        )[0][0])

        skill_overlap = 0.0
        if job_skills_list and user_skills_set:
            job_skills_norm = [normalize(s) for s in job_skills_list]
            matched_count = sum(
                1 for js in job_skills_norm
                if any(us in js or js in us for us in user_skills_set)
            )
            skill_overlap = matched_count / len(job_skills_norm)

        kg_score_sbert = self.compute_kg_score_for_job_match(user_skills_set, job_node_id)
        kg_score_rotate = self.compute_rotate_score_for_job(user_skills_set, job_node_id)

        gamma = beta
        kg_score = gamma * kg_score_rotate + (1 - gamma) * kg_score_sbert

        remaining = 1 - alpha - beta
        return alpha * cos_sim + remaining * skill_overlap + beta * kg_score

    def compute_kg_score_for_job_match(
        self,
        user_skills_set: Set[str],
        job_node_id: str,
    ) -> float:
        if not user_skills_set or not job_node_id:
            return 0.0

        job_vec = self.get_entity_vector(job_node_id)
        if job_vec is None:
            return 0.0

        if self.G and job_node_id in self.G:
            neighbor_skills = set()
            for nb in nx.neighbors(self.G, job_node_id):
                if self.G.nodes[nb].get("type") == "skill":
                    neighbor_skills.add(nb)
        else:
            neighbor_skills = set()

        matched = []
        for sn in neighbor_skills:
            label = self.G.nodes[sn].get("label", sn) if self.G and sn in self.G else sn
            label_norm = normalize(str(label))
            if any(us in label_norm or label_norm in us for us in user_skills_set):
                sv = self._entity_vectors.get(sn)
                if sv is not None:
                    matched.append(sv)

        if not matched:
            for sn in neighbor_skills:
                sv = self._entity_vectors.get(sn)
                if sv is not None:
                    matched.append(sv)

            if not matched:
                return 0.0
            skill_embs = np.array(matched)
            sims = np.dot(skill_embs, job_vec)
            return float(np.max(sims))

        skill_embs = np.array(matched)
        sims = np.dot(skill_embs, job_vec)
        max_sim = float(np.max(sims))
        mean_sim = float(np.mean(sims))
        return 0.6 * max_sim + 0.4 * mean_sim

    def get_related_entities(self, entity_id: str, top_n: int = 10) -> List[Tuple[str, float]]:
        target = self._entity_vectors.get(entity_id)
        if target is None:
            return []

        scores = []
        for eid, vec in self._entity_vectors.items():
            if eid == entity_id:
                continue
            sim = float(np.dot(target, vec))
            scores.append((eid, sim))

        scores.sort(key=lambda x: -x[1])
        return scores[:top_n]


_instance = None


def get_kge_service(refresh: bool = False) -> KgeService:
    global _instance
    if _instance is None or refresh:
        G = load_enriched_graph()
        _instance = KgeService.build(G, force_refresh=refresh)
    return _instance


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    svc = get_kge_service(refresh=True)
    print(f"Vectors: {len(svc._entity_vectors)}")
    print(f"RotatE loaded: {svc._rotate_model is not None}")

    G = svc.G
    for n, d in G.nodes(data=True):
        if d.get("type") == "job":
            job_title = d.get('job_title', '')[:60]
            print(f"\nJob: {job_title}")

            rotate_score = svc.compute_rotate_score_for_job({"python", "machine learning"}, n)
            sbert_score = svc.compute_kg_score_for_job_match({"python", "machine learning"}, n)
            print(f"  RotatE score: {rotate_score:.4f}")
            print(f"  SBERT score:  {sbert_score:.4f}")

            related = svc.get_related_entities(n, top_n=5)
            for eid, sim in related:
                label = G.nodes[eid].get("label", eid) if eid in G else eid
                etype = G.nodes[eid].get("type", "unknown") if eid in G else "unknown"
                print(f"  {sim:.4f} | {etype:15s} | {label}")
            break
