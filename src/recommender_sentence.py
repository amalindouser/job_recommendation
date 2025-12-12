import os
import re
import gzip
import numpy as np
import networkx as nx
from sklearn.metrics.pairwise import cosine_similarity

import numpy as np
if not hasattr(np, "float_"):
    np.float_ = np.float64

if not hasattr(np, "int_"):
    np.int_ = np.int64

# Lazy load model to avoid memory issues in serverless
model = None

def get_model():
    global model
    if model is None:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
    return model

JOB_EMBEDDINGS = {}
JOB_EMB_ARRAY = None
JOB_NODE_IDS = []
JOB_METAS = []
NODEID_TO_INDEX = {}

# ===============================
# Normalisasi teks
# ===============================
def normalize(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9+\-.\s]", " ", text)
    return text


# ===============================
# Load graph
# ===============================
def load_graph_from_path(graph_path: str):
    if not os.path.exists(graph_path):
        raise FileNotFoundError(f"Graph tidak ditemukan: {graph_path}")

    if graph_path.endswith(".gz"):
        with gzip.open(graph_path, "rb") as f:
            return nx.read_graphml(f)

    return nx.read_graphml(graph_path)


# ===============================
# Generate Smart Reason Text
# ===============================
def generate_reason_text(user_text, job_title, skills_required, match_percent, job_level):
    """Generate reason text in English describing why a job was recommended.

    The function returns a concise, human-friendly explanation emphasizing strengths,
    missing skills, and recommended next steps.
    """
    try:
        user_skills = normalize(user_text).split()
    except Exception:
        user_skills = []
    required_skills = [s.strip() for s in str(skills_required).split(",") if s.strip()]

    # Find matching keywords (case-insensitive)
    matched = [s for s in required_skills if any(uk in normalize(s) for uk in user_skills)]
    missing = [s for s in required_skills if s not in matched]

    # safety for match_percent
    try:
        mp = float(match_percent) if match_percent is not None else 0.0
    except Exception:
        mp = 0.0

    parts = []

    # Tone based on match percentage
    if mp >= 90:
        parts.append(f"Outstanding match — your profile is an excellent fit for {job_title}.")
    elif mp >= 75:
        parts.append(f"Strong match — your experience and skills align well with {job_title}.")
    elif mp >= 50:
        parts.append(f"Good potential — there is a meaningful overlap between your background and {job_title}.")
    elif mp >= 30:
        parts.append(f"Potential match — you have some relevant experience that could suit {job_title}.")
    else:
        parts.append(f"Low match — the role {job_title} may require skills you haven't highlighted yet.")

    # Matched skills summary
    if matched:
        top_matched = matched[:3]
        parts.append(f"You match on: {', '.join(top_matched)}.")
    else:
        parts.append("No direct skill overlap was detected from your input.")

    # Suggest next steps based on missing skills and job level
    if missing:
        top_missing = missing[:3]
        parts.append(f"Consider strengthening: {', '.join(top_missing)} to improve your fit.")

    if job_level:
        lvl = normalize(job_level)
        if 'senior' in lvl:
            parts.append("This position targets experienced professionals — highlight leadership and impact in your CV.")
        elif 'junior' in lvl or 'entry' in lvl or 'associate' in lvl:
            parts.append("This is suitable for early-career candidates — emphasize projects and learning ability.")

    # Practical call to action
    if mp >= 50:
        parts.append("Recommended action: consider applying and tailor your resume to the listed skills.")
    else:
        parts.append("Recommended action: upskill for the missing areas or search for roles closer to your current experience.")

    parts.append(f"Match score: {round(mp,1)}% (semantic similarity).")

    # Join into a short paragraph
    return ' '.join(parts)


# ===============================
# Helpers: build & cache job embeddings
# ===============================
def build_job_sentence(data: dict) -> str:
    job_sentence = f"""
        {data.get('job_title', '')}.
        Required skills: {data.get('skills_raw', '')}.
        Job type: {data.get('job_type', '')}.
        Level: {data.get('job_level', '')}.
        """
    return normalize(job_sentence)


def build_job_embeddings(G, force: bool = False, batch_size: int = 64):
    """Batch-encode all job nodes in graph G and cache arrays for fast scoring."""
    global JOB_EMB_ARRAY, JOB_NODE_IDS, JOB_METAS, NODEID_TO_INDEX

    if JOB_EMB_ARRAY is not None and not force:
        return

    sentences = []
    node_ids = []
    metas = []

    for node_id, data in G.nodes(data=True):
        if data.get("type") != "job":
            continue
        sentences.append(build_job_sentence(data))
        node_ids.append(node_id)
        metas.append(data)

    if not sentences:
        JOB_EMB_ARRAY = np.zeros((0, 0))
        JOB_NODE_IDS = []
        JOB_METAS = []
        NODEID_TO_INDEX = {}
        return

    embs = get_model().encode(sentences, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)
    # normalize
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs = embs / (norms + 1e-12)

    JOB_EMB_ARRAY = embs
    JOB_NODE_IDS = node_ids
    JOB_METAS = metas
    NODEID_TO_INDEX = {nid: idx for idx, nid in enumerate(node_ids)}
    print(f"✔ Built embeddings for {len(node_ids)} jobs")


# ===============================
# Sentence Matching Recommender
# ===============================
def recommend_jobs_sentence(
    G,
    user_text,
    top_n=10,
    filter_country=None,
    filter_city=None,
    threshold=0.35
):
    results = []

    # Ensure embeddings are built
    build_job_embeddings(G)

    if JOB_EMB_ARRAY is None or len(JOB_METAS) == 0:
        return []

    user_sentence = normalize(user_text)
    user_embedding = get_model().encode(user_sentence, convert_to_numpy=True)
    user_embedding = user_embedding / (np.linalg.norm(user_embedding) + 1e-12)

    # Filter candidates by location (if requested)
    candidates = list(range(len(JOB_METAS)))
    if filter_country or filter_city:
        fc = normalize(filter_country) if filter_country else None
        fcity = normalize(filter_city) if filter_city else None
        filtered = []
        for idx in candidates:
            meta = JOB_METAS[idx]
            jl = normalize(meta.get("job_location", ""))
            if fc and fc not in jl:
                continue
            if fcity and fcity not in jl:
                continue
            filtered.append(idx)
        candidates = filtered

    if not candidates:
        return []

    # Vectorized similarity against candidate embeddings
    emb_subset = JOB_EMB_ARRAY[candidates]
    sims = emb_subset.dot(user_embedding)

    # Apply threshold
    keep_mask = sims >= threshold
    if not np.any(keep_mask):
        return []

    keep_idxs = np.where(keep_mask)[0]
    sims_kept = sims[keep_idxs]

    # Pick top_n
    order = np.argsort(-sims_kept)[:top_n]
    selected_rel = keep_idxs[order]

    for rel_idx in selected_rel:
        score = sims[rel_idx]
        node_idx = candidates[rel_idx]
        data = JOB_METAS[node_idx]

        match_percent = round(float(score) * 100, 1)

        reason = generate_reason_text(
            user_text,
            data.get("job_title", "Unknown"),
            data.get("skills_raw", ""),
            match_percent,
            data.get("job_level", "")
        )

        results.append({
            "job_title": data.get("job_title", "Unknown"),
            "company": data.get("company", "Unknown"),
            "location": data.get("job_location", ""),
            "job_type": data.get("job_type", ""),
            "date": data.get("first_seen", ""),
            "skills": [
                s.strip() for s in str(data.get("skills_raw", "")).split(",") if s.strip()
            ][:8],
            "match_percent": match_percent,
            "reason_text": reason,
            "link": data.get("job_link", "#")
        })

    return results
