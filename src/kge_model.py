import os
import math
import pickle
import random
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple, Any

import numpy as np
import networkx as nx

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


CACHE_DIR = Path(__file__).parent.parent / "data"
EMBEDDINGS_CACHE = CACHE_DIR / "kge_embeddings.pkl"


class RotatEModel:
    def __init__(
        self,
        n_entities: int = 0,
        n_relations: int = 0,
        dim: int = 256,
        entity_ids: Optional[List[str]] = None,
        relation_ids: Optional[List[str]] = None,
    ):
        self.dim = dim
        self.n_entities = n_entities
        self.n_relations = n_relations
        self.entity_ids = entity_ids or []
        self.relation_ids = relation_ids or []

        self.entity_to_idx: Dict[str, int] = {}
        self.relation_to_idx: Dict[str, int] = {}

        self.entity_embeddings: Optional[np.ndarray] = None
        self.relation_embeddings: Optional[np.ndarray] = None

    def _init_embeddings(self):
        self.entity_embeddings = np.random.randn(self.n_entities, self.dim, 2).astype(np.float32) * 0.05
        phase = np.random.uniform(0, 2 * math.pi, (self.n_relations, self.dim)).astype(np.float32)
        r_real = np.cos(phase)
        r_imag = np.sin(phase)
        self.relation_embeddings = np.stack([r_real, r_imag], axis=-1)

        for i, eid in enumerate(self.entity_ids):
            self.entity_to_idx[eid] = i
        for i, rid in enumerate(self.relation_ids):
            self.relation_to_idx[rid] = i

    @classmethod
    def from_graph(cls, G: nx.Graph, dim: int = 256):
        entities = list(G.nodes())
        relations_set = set()
        for _, _, d in G.edges(data=True):
            r = d.get("relation", "unknown")
            relations_set.add(r)
        relations = sorted(relations_set)

        model = cls(
            n_entities=len(entities),
            n_relations=len(relations),
            dim=dim,
            entity_ids=entities,
            relation_ids=relations,
        )
        model._init_embeddings()
        return model

    def get_entity_embedding(self, entity_id: str) -> Optional[np.ndarray]:
        idx = self.entity_to_idx.get(entity_id)
        if idx is None:
            return None
        return self.entity_embeddings[idx]

    def get_relation_embedding(self, relation_id: str) -> Optional[np.ndarray]:
        idx = self.relation_to_idx.get(relation_id)
        if idx is None:
            return None
        return self.relation_embeddings[idx]

    def score_triple(self, h: np.ndarray, r: np.ndarray, t: np.ndarray) -> float:
        hr_real = h[..., 0] * r[..., 0] - h[..., 1] * r[..., 1]
        hr_imag = h[..., 0] * r[..., 1] + h[..., 1] * r[..., 0]
        diff_real = hr_real - t[..., 0]
        diff_imag = hr_imag - t[..., 1]
        score = -np.sum(diff_real ** 2 + diff_imag ** 2)
        return float(score)

    def compute_entity_similarity(self, e1_id: str, e2_id: str) -> Optional[float]:
        idx1 = self.entity_to_idx.get(e1_id)
        idx2 = self.entity_to_idx.get(e2_id)
        if idx1 is None or idx2 is None:
            return None
        e1 = self.entity_embeddings[idx1]
        e2 = self.entity_embeddings[idx2]
        e1_flat = e1.ravel()
        e2_flat = e2.ravel()
        norm1 = np.linalg.norm(e1_flat)
        norm2 = np.linalg.norm(e2_flat)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(e1_flat, e2_flat) / (norm1 * norm2))

    def get_entity_embedding_vector(self, entity_id: str) -> Optional[np.ndarray]:
        emb = self.get_entity_embedding(entity_id)
        if emb is None:
            return None
        return emb.ravel()

    def save(self, path: Optional[Path] = None):
        path = path or EMBEDDINGS_CACHE
        data = {
            "dim": self.dim,
            "n_entities": self.n_entities,
            "n_relations": self.n_relations,
            "entity_ids": self.entity_ids,
            "relation_ids": self.relation_ids,
            "entity_to_idx": self.entity_to_idx,
            "relation_to_idx": self.relation_to_idx,
            "entity_embeddings": self.entity_embeddings,
            "relation_embeddings": self.relation_embeddings,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)
        print(f"[OK] RotatE embeddings saved to {path}")

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "RotatEModel":
        path = Path(path) if path and not isinstance(path, Path) else (path or EMBEDDINGS_CACHE)
        if not path.exists():
            raise FileNotFoundError(f"RotatE embeddings not found at {path}")

        with open(path, "rb") as f:
            data = pickle.load(f)

        model = cls(
            n_entities=data["n_entities"],
            n_relations=data["n_relations"],
            dim=data["dim"],
            entity_ids=data["entity_ids"],
            relation_ids=data["relation_ids"],
        )
        model.entity_to_idx = data["entity_to_idx"]
        model.relation_to_idx = data["relation_to_idx"]
        model.entity_embeddings = data["entity_embeddings"]
        model.relation_embeddings = data["relation_embeddings"]
        print(f"[OK] RotatE embeddings loaded ({model.n_entities} entities, {model.n_relations} relations, dim={model.dim})")
        return model


def _torch_train_rotate(
    G: nx.Graph,
    dim: int = 256,
    n_epochs: int = 100,
    learning_rate: float = 0.001,
    batch_size: int = 1024,
    n_negatives: int = 64,
    save_path: Optional[Path] = None,
) -> RotatEModel:
    if not HAS_TORCH:
        raise ImportError("PyTorch is required for training. Install with: pip install torch")

    entities = list(G.nodes())
    relations_set = set()
    for _, _, d in G.edges(data=True):
        r = d.get("relation", "unknown")
        relations_set.add(r)
    relations = sorted(relations_set)

    entity_to_idx = {e: i for i, e in enumerate(entities)}
    relation_to_idx = {r: i for i, r in enumerate(relations)}

    triples = []
    for h, t, d in G.edges(data=True):
        r = d.get("relation", "unknown")
        triples.append((entity_to_idx[h], relation_to_idx[r], entity_to_idx[t]))

    n_entities = len(entities)
    n_relations = len(relations)
    n_triples = len(triples)

    print(f"[*] PyTorch RotatE training: {n_entities} entities, {n_relations} relations, {n_triples} triples, dim={dim}")

    ent_re = nn.Embedding(n_entities, dim)
    ent_im = nn.Embedding(n_entities, dim)
    rel_re = nn.Embedding(n_relations, dim)
    rel_im = nn.Embedding(n_relations, dim)

    nn.init.xavier_uniform_(ent_re.weight)
    nn.init.xavier_uniform_(ent_im.weight)
    nn.init.xavier_uniform_(rel_re.weight)
    nn.init.xavier_uniform_(rel_im.weight)

    params = list(ent_re.parameters()) + list(ent_im.parameters()) + list(rel_re.parameters()) + list(rel_im.parameters())
    optimizer = torch.optim.Adam(params, lr=learning_rate)

    triples_tensor = torch.tensor(triples, dtype=torch.long)
    all_entities_tensor = torch.arange(n_entities, dtype=torch.long)

    n_batches_per_epoch = max(1, (n_triples + batch_size - 1) // batch_size)

    for epoch in range(n_epochs):
        perm = torch.randperm(n_triples)
        total_loss = 0.0

        for i in range(0, n_triples, batch_size):
            idx = perm[i : i + batch_size]
            batch = triples_tensor[idx]
            batch_h = batch[:, 0]
            batch_r = batch[:, 1]
            batch_t = batch[:, 2]
            bs = batch_h.size(0)

            h_re = ent_re(batch_h)
            h_im = ent_im(batch_h)
            r_re = rel_re(batch_r)
            r_im = rel_im(batch_r)
            t_re = ent_re(batch_t)
            t_im = ent_im(batch_t)

            hr_re = h_re * r_re - h_im * r_im
            hr_im = h_re * r_im + h_im * r_re
            pos_diff_re = hr_re - t_re
            pos_diff_im = hr_im - t_im
            pos_score = -torch.sum(pos_diff_re ** 2 + pos_diff_im ** 2, dim=-1)
            pos_loss = -torch.mean(F.logsigmoid(pos_score))

            neg_t = torch.randint(0, n_entities, (bs, n_negatives))
            neg_t_re = ent_re(neg_t)
            neg_t_im = ent_im(neg_t)
            hr_re_exp = hr_re.unsqueeze(1).expand(-1, n_negatives, -1)
            hr_im_exp = hr_im.unsqueeze(1).expand(-1, n_negatives, -1)
            neg_diff_re = hr_re_exp - neg_t_re
            neg_diff_im = hr_im_exp - neg_t_im
            neg_score = -torch.sum(neg_diff_re ** 2 + neg_diff_im ** 2, dim=-1)
            neg_loss = -torch.mean(F.logsigmoid(-neg_score))

            loss = pos_loss + neg_loss
            total_loss += loss.item()

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            with torch.no_grad():
                r_norm = torch.sqrt(rel_re.weight ** 2 + rel_im.weight ** 2)
                rel_re.weight /= (r_norm + 1e-12)
                rel_im.weight /= (r_norm + 1e-12)

        avg_loss = total_loss / n_batches_per_epoch
        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  Epoch {epoch+1}/{n_epochs}, loss: {avg_loss:.4f}")

    numpy_model = RotatEModel(
        n_entities=n_entities,
        n_relations=n_relations,
        dim=dim,
        entity_ids=entities,
        relation_ids=relations,
    )
    numpy_model.entity_to_idx = entity_to_idx
    numpy_model.relation_to_idx = relation_to_idx
    numpy_model.entity_embeddings = np.stack(
        [ent_re.weight.detach().numpy(), ent_im.weight.detach().numpy()], axis=-1
    ).astype(np.float32)
    numpy_model.relation_embeddings = np.stack(
        [rel_re.weight.detach().numpy(), rel_im.weight.detach().numpy()], axis=-1
    ).astype(np.float32)

    if save_path:
        numpy_model.save(save_path)

    return numpy_model


def train_rotate(
    G: nx.Graph,
    dim: int = 256,
    n_epochs: int = 100,
    learning_rate: float = 0.001,
    batch_size: int = 1024,
    n_negatives: int = 64,
    save_path: Optional[Path] = None,
) -> RotatEModel:
    if HAS_TORCH:
        return _torch_train_rotate(G, dim, n_epochs, learning_rate, batch_size, n_negatives, save_path)

    raise ImportError("PyTorch is required for RotatE training. Install with: pip install torch")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.graph_enricher import load_enriched_graph

    G = load_enriched_graph()
    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    model = train_rotate(
        G, dim=256, n_epochs=50, learning_rate=0.002, batch_size=2048, n_negatives=32
    )
    print(f"\nModel trained: {model.n_entities} entities, {model.n_relations} relations")

    # Test similarity with trained model
    import numpy as np
    for n, d in G.nodes(data=True):
        if d.get('type') == 'job' and 'software' in d.get('job_title', '').lower():
            job_node = n
            job_title = d.get('job_title', '')
            print(f"\nJob: {job_title} ({n})")

            target_emb = model.get_entity_embedding_vector(n)
            if target_emb is not None:
                scores = []
                for eid in model.entity_ids:
                    if eid == n:
                        continue
                    emb = model.get_entity_embedding_vector(eid)
                    if emb is not None:
                        sim = float(np.dot(target_emb, emb))
                        scores.append((eid, sim))
                scores.sort(key=lambda x: -x[1])
                print("Top 10 related entities:")
                for eid, sim in scores[:10]:
                    label = G.nodes[eid].get('label', eid) if eid in G else eid
                    etype = G.nodes[eid].get('type', 'unknown') if eid in G else 'unknown'
                    print(f"  {sim:.4f} | {etype:15s} | {label}")
            break
