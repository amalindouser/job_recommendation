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
    text = re.sub(r"\s+", " ", text)
    return text


# ===============================
# Load and cache embeddings
# ===============================
def load_and_cache_embeddings(G, batch_size=128):
    """Load job data from graph and create sentence embeddings."""
    global JOB_EMBEDDINGS, JOB_EMB_ARRAY, JOB_NODE_IDS, JOB_METAS, NODEID_TO_INDEX
    
    sentences = []
    node_ids = []
    metas = []

    for node_id, data in G.nodes(data=True):
        job_title = data.get("job_title", "")
        company = data.get("company", "")
        skills = data.get("skills", [])
        location = data.get("location", "")
        
        # Combine all text for embedding
        text = f"{job_title} {company} {' '.join(skills) if isinstance(skills, list) else skills} {location}"
        text = normalize(text)
        
        if text.strip():
            sentences.append(text)
            node_ids.append(node_id)
            metas.append({
                "job_title": job_title,
                "company": company,
                "skills": skills,
                "location": location,
                "link": data.get("link", "#"),
                "date": data.get("date", ""),
                "match_percent": None
            })

    if not sentences:
        JOB_EMB_ARRAY = None
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
    NODEID_TO_INDEX = {nid: i for i, nid in enumerate(node_ids)}

    print(f"✔ Loaded {len(metas)} job embeddings")


# ===============================
# Get embeddings for user input
# ===============================
def recommend_jobs_sentence(
    user_text: str,
    G,
    limit: int = 12,
    filter_country: str = None,
    filter_city: str = None,
):
    """
    Recommend jobs based on user text similarity using sentence embeddings.
    
    Args:
        user_text: User input skills/preferences
        G: NetworkX graph with job data
        limit: Max number of recommendations
        filter_country: Filter by country
        filter_city: Filter by city
    
    Returns:
        List of recommended jobs with match score
    """
    global JOB_EMB_ARRAY, JOB_METAS
    
    # Load embeddings if not cached
    if JOB_EMB_ARRAY is None:
        load_and_cache_embeddings(G)
    
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
        
        candidates = [
            i for i in candidates
            if (not fc or fc in normalize(JOB_METAS[i].get("location", "")))
            and (not fcity or fcity in normalize(JOB_METAS[i].get("location", "")))
        ]

    if not candidates:
        return []

    # Compute similarity
    similarities = cosine_similarity([user_embedding], JOB_EMB_ARRAY[candidates])[0]
    
    # Get top matches
    top_indices = np.argsort(similarities)[::-1][:limit]
    
    results = []
    for idx in top_indices:
        job_idx = candidates[idx]
        similarity_score = float(similarities[idx])
        match_percent = int(min(100, max(0, similarity_score * 100)))
        
        job = JOB_METAS[job_idx].copy()
        job["match_percent"] = match_percent
        job["reason_text"] = f"This job matches {match_percent}% of your skills and experience."
        results.append(job)

    return results
