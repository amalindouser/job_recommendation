import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import networkx as nx

from src.recommender_sentence import (
    normalize,
    JOB_EMB_ARRAY,
    JOB_METAS,
    JOB_NODE_IDS,
    NODEID_TO_INDEX,
    get_model,
    load_and_cache_embeddings,
)


def match_candidates_for_vacancy(vacancy: dict, G: nx.Graph, top_n: int = 10):
    if JOB_EMB_ARRAY is None:
        try:
            load_and_cache_embeddings(G)
        except Exception as e:
            print(f"[!] Failed to load embeddings: {e}")
            return []

    if JOB_EMB_ARRAY is None or not JOB_METAS:
        return []

    vacancy_text = f"{vacancy.get('job_title', '')} {vacancy.get('company', '')} {' '.join(vacancy.get('skills', []))} {vacancy.get('location', '')}"
    vacancy_text = normalize(vacancy_text)

    if not vacancy_text.strip():
        return []

    vacancy_emb = get_model().encode(vacancy_text, convert_to_numpy=True)
    norm = np.linalg.norm(vacancy_emb)
    if norm > 0:
        vacancy_emb = vacancy_emb / norm

    vacancy_skills = set(normalize(s) for s in vacancy.get("skills", []))

    scores = []
    for idx, meta in enumerate(JOB_METAS):
        job_skills = [normalize(s) for s in meta.get("skills", [])]

        # 40% Skill overlap
        skill_overlap = 0.0
        if job_skills and vacancy_skills:
            match_count = 0
            for js in job_skills:
                if any(us in js or js in us for us in vacancy_skills):
                    match_count += 1
            skill_overlap = match_count / len(job_skills)

        # 40% Embedding similarity
        emb_sim = float(cosine_similarity(
            vacancy_emb.reshape(1, -1),
            JOB_EMB_ARRAY[idx].reshape(1, -1)
        )[0][0])

        # 20% Graph relationship score
        graph_score = 0.0
        nid = JOB_NODE_IDS[idx] if idx < len(JOB_NODE_IDS) else None
        if nid and nid in G:
            try:
                related = set()
                for neighbor in G.neighbors(nid):
                    nd = G.nodes[neighbor]
                    if nd.get("type") == "skill":
                        related.add(normalize(nd.get("label", neighbor)))
                if related and vacancy_skills:
                    common = related & vacancy_skills
                    graph_score = len(common) / max(len(vacancy_skills), 1)
            except Exception:
                graph_score = 0.0

        total = 0.4 * skill_overlap + 0.4 * emb_sim + 0.2 * graph_score
        scores.append((total, meta, skill_overlap, emb_sim, graph_score))

    scores.sort(key=lambda x: x[0], reverse=True)
    results = []
    for total, meta, skill_ov, emb_sim, graph_sc in scores[:top_n]:
        match_pct = int(min(100, max(0, total * 100)))
        results.append({
            "job_title": meta.get("job_title", ""),
            "company": meta.get("company", ""),
            "location": meta.get("location", ""),
            "skills": meta.get("skills", []),
            "match_percent": match_pct,
            "skill_overlap": round(skill_ov, 2),
            "embedding_similarity": round(emb_sim, 2),
            "graph_score": round(graph_sc, 2),
            "total_score": round(total, 4),
        })

    return results
