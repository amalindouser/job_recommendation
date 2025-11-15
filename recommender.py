import os
import re
import gzip
import numpy as np
import networkx as nx
from difflib import get_close_matches

# Fix NumPy 2.0 compatibility
if not hasattr(np, "float_"):
    np.float_ = np.float64
if not hasattr(np, "int_"):
    np.int_ = np.int64


# ===============================
# 🔧 Normalisasi teks skill
# ===============================
def normalize(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.lower().strip()
    # Jangan hapus "+" atau "-" (penting untuk C++, Node.js)
    text = re.sub(r"[^a-z0-9+\-.\s]", "", text)
    return text


# ===============================
# 📦 Load Graph
# ===============================
def load_graph_from_path(graph_path: str):
    if not os.path.exists(graph_path):
        raise FileNotFoundError(f"❌ File graph tidak ditemukan: {graph_path}")

    if graph_path.endswith(".gz"):
        with gzip.open(graph_path, "rb") as f:
            G = nx.read_gpickle(f)
    else:
        G = nx.read_gpickle(graph_path)

    print(f"✔ Graph loaded ({len(G.nodes())} nodes, {len(G.edges())} edges)")
    return G


# ===============================
# 🔑 Skill alias
# ===============================
SKILL_ALIASES = {
    "ml": "machine learning",
    "dl": "deep learning",
    "ai": "artificial intelligence",
    "cv": "computer vision",
    "js": "javascript",
    "node": "node.js",
    "cplus": "c++",
    "c sharp": "c#",
    "py": "python",
    "sql db": "sql",
}


def map_alias(skill: str):
    skill = normalize(skill)
    return SKILL_ALIASES.get(skill, skill)


# ===============================
# 🧠 Rekomendasi
# ===============================
def recommend_jobs(G, user_skills, top_n=10, filter_country=None, filter_city=None):
    if isinstance(user_skills, str):
        user_skills = [user_skills]

    # Normalize user skill input
    user_skills = [map_alias(s) for s in user_skills]
    user_skills_norm = [normalize(s) for s in user_skills]

    print(f"🔍 Skills input: {user_skills_norm}")

    results = []

    # Loop job nodes
    for job, data in G.nodes(data=True):

        if str(data.get("type", "")).lower() != "job":
            continue

        # Location
        job_location = data.get("location", "").lower()

        if filter_country and filter_country.lower() not in job_location:
            continue
        if filter_city and filter_city.lower() not in job_location:
            continue

        # Skills for this job
        raw_skills = data.get("skills", "")
        job_skills = [normalize(s) for s in raw_skills.split(",") if s.strip()]

        if not job_skills:
            continue

        matched = [s for s in job_skills if s in user_skills_norm]
        missing = [s for s in job_skills if s not in user_skills_norm]

        if len(job_skills) == 0:
            continue

        match_percent = round((len(matched) / len(job_skills)) * 100, 1)

        if match_percent == 0:
            continue

        # Reason text
        if match_percent >= 80:
            fit_level = "Very Suitable"
            reason_text = (
                f"This job matches strongly because you have these key skills: "
                f"{', '.join(matched)}. "
                f"{'No missing skills.' if not missing else 'You may also need: ' + ', '.join(missing[:3])}."
            )

        elif match_percent >= 50:
            fit_level = "Suitable"
            reason_text = (
                f"You match with: {', '.join(matched)}. "
                f"Consider learning: {', '.join(missing[:3])}."
            )

        elif match_percent >= 20:
            fit_level = "Less Suitable"
            reason_text = (
                f"Some match: {', '.join(matched)}. "
                f"Missing many required skills: {', '.join(missing[:3])}."
            )

        else:
            fit_level = "Not Suitable"
            reason_text = (
                f"Low skill match. Required skills include: "
                f"{', '.join(job_skills[:5])}."
            )

        results.append({
            "job_title": data.get("label") or data.get("title") or str(job),
            "company": data.get("company", "Unknown Company"),
            "location": data.get("location", "Unknown Location"),
            "job_type": data.get("job_type", "N/A"),
            "date": data.get("date") or data.get("first_seen", ""),
            "skills_job": job_skills,
            "matched_skills": matched,
            "missing_skills": missing,
            "match_percent": match_percent,
            "fit_level": fit_level,
            "reason_text": reason_text,
            "link": data.get("link", "#")
        })

    # Sort by best match
    results = sorted(results, key=lambda x: x["match_percent"], reverse=True)

    return results[:top_n]
