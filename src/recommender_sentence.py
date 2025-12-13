import os
import re
import gzip
import numpy as np
import networkx as nx
from sklearn.metrics.pairwise import cosine_similarity
import psycopg2
import pandas as pd
import pickle
from pathlib import Path

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
JOB_DB_CACHE = {}  # Cache for database job lookups

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
def load_db_jobs_cache(DB_URL=None):
    """Preload all jobs from database into cache for fast lookups."""
    global JOB_DB_CACHE
    if not DB_URL or JOB_DB_CACHE:
        return
    try:
        conn = psycopg2.connect(DB_URL)
        df = pd.read_sql("SELECT job_title, company_name, search_city, search_country, first_seen, job_link, job_type FROM jobs_skills", conn)
        conn.close()
        for _, row in df.iterrows():
            key = (str(row.get('job_title')).lower(), str(row.get('company_name')).lower())
            JOB_DB_CACHE[key] = {
                "location": f"{row.get('search_city')}, {row.get('search_country')}",
                "date": str(row.get("first_seen")) if pd.notna(row.get("first_seen")) else "",
                "link": row.get("job_link", "#"),
                "job_type": row.get("job_type", ""),
            }
        print(f"[OK] Cached {len(JOB_DB_CACHE)} jobs from database")
    except Exception as e:
        print(f"[!] DB cache load skipped (using graph data only): {e}")

def get_job_from_cache(job_title, company):
    """Get job data from cache."""
    key = (str(job_title).lower(), str(company).lower())
    return JOB_DB_CACHE.get(key)

def load_and_cache_embeddings(G, batch_size=256, DB_URL=None, force_refresh=False):
    """Load job data from graph and create sentence embeddings.
    
    Args:
        G: NetworkX graph with job data
        batch_size: Batch size for encoding
        DB_URL: Database connection URL
        force_refresh: If True, ignore cache and regenerate embeddings
    """
    global JOB_EMBEDDINGS, JOB_EMB_ARRAY, JOB_NODE_IDS, JOB_METAS, NODEID_TO_INDEX
    
    # Skip if already loaded (and not forcing refresh)
    if JOB_EMB_ARRAY is not None and not force_refresh:
        print("[OK] Embeddings already loaded, skipping")
        return
    
    # Try to load from cache file (unless force_refresh)
    cache_path = Path(__file__).parent.parent / "embeddings_cache.pkl"
    if cache_path.exists() and not force_refresh:
        try:
            with open(cache_path, 'rb') as f:
                cache_data = pickle.load(f)
                JOB_EMB_ARRAY = cache_data['embs']
                JOB_NODE_IDS = cache_data['node_ids']
                JOB_METAS = cache_data['metas']
                NODEID_TO_INDEX = cache_data['nodeid_to_index']
                print(f"[OK] Loaded {len(JOB_METAS)} embeddings from cache")
                return
        except Exception as e:
            print(f"[!] Cache load failed, will regenerate: {e}")
    
    # Preload DB cache if needed (optional, graph has most data)
    # if DB_URL:
    #     load_db_jobs_cache(DB_URL)
    
    sentences = []
    node_ids = []
    metas = []

    for node_id, data in G.nodes(data=True):
        # Skip non-job nodes
        if data.get("type") != "job":
            continue
            
        job_title = data.get("job_title", "")
        company = data.get("company", "")
        
        # Get skills from skills_raw (comma-separated)
        skills_raw = data.get("skills_raw", "")
        if isinstance(skills_raw, str) and skills_raw:
            skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
        else:
            skills = []
        
        # Get location from graph
        location = data.get("job_location", "")
        search_city = data.get("search_city", "")
        search_country = data.get("search_country", "")
        if search_city and search_country:
            location = f"{search_city}, {search_country}"
        
        # Get date and link from graph
        date_str = data.get("first_seen", "")
        link = data.get("job_link", "#")
        job_type = data.get("job_type", "")
        
        # Combine all text for embedding
        text = f"{job_title} {company} {' '.join(skills)} {location}"
        text = normalize(text)
        
        if text.strip():
            sentences.append(text)
            node_ids.append(node_id)
            
            # Enrich with database data from cache (database overrides if available)
            db_data = get_job_from_cache(job_title, company)
            meta = {
                "job_title": job_title,
                "company": company,
                "skills": skills,
                "location": db_data.get("location") if db_data else location,
                "link": db_data.get("link") if db_data else link,
                "date": db_data.get("date") if db_data else date_str,
                "job_type": db_data.get("job_type") if db_data else job_type,
                "match_percent": None
            }
            metas.append(meta)

    if not sentences:
        JOB_EMB_ARRAY = None
        JOB_NODE_IDS = []
        JOB_METAS = []
        NODEID_TO_INDEX = {}
        return

    print(f"[*] Encoding {len(sentences)} job sentences (this may take 1-2 min on first run)...")
    embs = get_model().encode(sentences, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)
    # normalize
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs = embs / (norms + 1e-12)

    JOB_EMB_ARRAY = embs
    JOB_NODE_IDS = node_ids
    JOB_METAS = metas
    NODEID_TO_INDEX = {nid: i for i, nid in enumerate(node_ids)}

    # Save to cache
    try:
        with open(cache_path, 'wb') as f:
            pickle.dump({
                'embs': JOB_EMB_ARRAY,
                'node_ids': JOB_NODE_IDS,
                'metas': JOB_METAS,
                'nodeid_to_index': NODEID_TO_INDEX
            }, f)
        print(f"[OK] Saved embeddings to cache")
    except Exception as e:
        print(f"[!] Cache save failed: {e}")

    print(f"[OK] Loaded {len(metas)} job embeddings")


# ===============================
# Get embeddings for user input
# ===============================
def recommend_jobs_sentence(
    G,
    user_text: str,
    top_n: int = 12,
    filter_country: str = None,
    filter_city: str = None,
    DB_URL: str = None,
):
    """
    Recommend jobs based on user text similarity using sentence embeddings.
    
    Args:
        G: NetworkX graph with job data
        user_text: User input skills/preferences
        top_n: Max number of recommendations
        filter_country: Filter by country
        filter_city: Filter by city
        DB_URL: Database connection URL for enriching data
    
    Returns:
        List of recommended jobs with match score
    """
    global JOB_EMB_ARRAY, JOB_METAS
    
    # Load embeddings if not cached
    if JOB_EMB_ARRAY is None:
        load_and_cache_embeddings(G, DB_URL=DB_URL)
    
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
    top_indices = np.argsort(similarities)[::-1][:top_n]
    
    results = []
    user_skills_norm = set(normalize(s) for s in user_text.lower().split())
    
    for idx in top_indices:
        job_idx = candidates[idx]
        similarity_score = float(similarities[idx])
        match_percent = int(min(100, max(0, similarity_score * 100)))
        
        job = JOB_METAS[job_idx].copy()
        job["match_percent"] = match_percent
        
        # Calculate matched and missing skills
        job_skills_norm = [normalize(s) for s in job.get("skills", [])]
        matched = [s for s in job_skills_norm if any(uk in s for uk in user_skills_norm)]
        missing = [s for s in job_skills_norm if not any(uk in s for uk in user_skills_norm)]
        
        match_ratio = len(matched) / len(job_skills_norm) if job_skills_norm else 0
        
        # Generate concise but informative reason
        reason_parts = []
        
        # Match quality assessment - concise version
        if match_percent >= 85:
            reason_parts.append(f"[+] Excellent Match ({match_percent}%)")
            reason_parts.append(f"\nYou have {len(matched)}/{len(job_skills_norm)} required skills. You're a highly competitive candidate.")
        elif match_percent >= 70:
            reason_parts.append(f"[o] Strong Match ({match_percent}%)")
            reason_parts.append(f"\nYou have {len(matched)}/{len(job_skills_norm)} required skills. Ready to contribute with minimal ramp-up.")
        elif match_percent >= 50:
            reason_parts.append(f"[o] Fair Match ({match_percent}%)")
            reason_parts.append(f"\nYou have {len(matched)}/{len(job_skills_norm)} required skills. Good growth opportunity with 3-6 months learning curve.")
        else:
            reason_parts.append(f"[o] Learning Opportunity ({match_percent}%)")
            reason_parts.append(f"\nYou have {len(matched)}/{len(job_skills_norm)} required skills. Strategic skill diversification opportunity.")
        
        # Skill summary - compact
        if matched:
            matched_display = ", ".join(matched[:3])
            if len(matched) > 3:
                matched_display += f", +{len(matched)-3} more"
            reason_parts.append(f"\n\n[OK] Your strengths: {matched_display}")
        
        if missing:
            missing_display = ", ".join(missing[:3])
            if len(missing) > 3:
                missing_display += f", +{len(missing)-3} more"
            reason_parts.append(f"\n[!] Growth areas: {missing_display}")
        
        # Position context
        reason_parts.append(f"\nPOS: {job.get('location', 'TBD')}")
        if job.get('job_type'):
            reason_parts.append(f" | {job.get('job_type').title()}")
        
        # Quick action
        if match_percent >= 75:
            reason_parts.append("\n\n-> Apply now! Strong candidate fit.")
        elif match_percent >= 60:
            reason_parts.append("\n\n-> Recommended for growth potential.")
        elif match_percent >= 45:
            reason_parts.append("\n\n-> Worth exploring for career development.")
        else:
            reason_parts.append("\n\n-> Consider for skill diversification.")
        
        job["reason_text"] = "".join(reason_parts)
        results.append(job)

    return results
