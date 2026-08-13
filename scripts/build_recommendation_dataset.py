"""
Build gabungan dataset rekomendasi:
- graph_jobs_clean.graphml (LinkedIn 5K, global)
- subset stratifikasi dari all_jobs_clean.db (JobStreet Indonesia)

Output: data/graph_recommend.graphml

Usage:
    python scripts/build_recommendation_dataset.py [--size 75000] [--seed 42]
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import networkx as nx

from src.clean_skills import clean_and_dedup_skills

DATA_DIR = Path(__file__).parent.parent / "data"
GRAPH_IN = DATA_DIR / "graph_jobs_clean.graphml"
DB_PATH = DATA_DIR / "all_jobs_clean.db"
GRAPH_OUT = DATA_DIR / "graph_recommend.graphml"


def load_linkedin_graph():
    G = nx.read_graphml(str(GRAPH_IN))
    n = sum(1 for _, d in G.nodes(data=True) if d.get("type") == "job")
    print(f"[OK] LinkedIn graph: {n} jobs")
    return G


def sample_db_jobs(target: int, seed: int):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    rows = c.execute(
        """
        SELECT id, job_title, company, location, employment, posted_at,
               job_url, categories, skills, description
        FROM clean_jobs
        WHERE skills IS NOT NULL AND skills != '[]'
          AND job_title IS NOT NULL AND job_title != ''
        """
    ).fetchall()

    jobs = []
    for r in rows:
        try:
            skills = json.loads(r["skills"]) if r["skills"] else []
        except (ValueError, TypeError):
            skills = []
        if not skills:
            continue
        try:
            cats = json.loads(r["categories"]) if r["categories"] else []
        except (ValueError, TypeError):
            cats = []
        jobs.append({
            "id": r["id"],
            "job_title": r["job_title"],
            "company": r["company"] or "",
            "location": r["location"] or "",
            "employment": r["employment"] or "",
            "posted_at": r["posted_at"] or "",
            "job_url": r["job_url"] or "#",
            "categories": cats,
            "skills": skills,
            "description": (r["description"] or "")[:2000],
        })
    conn.close()

    print(f"[OK] DB jobs with skills: {len(jobs):,}")

    bucket = Counter()
    for j in jobs:
        bucket[j["categories"][0] if j["categories"] else "Lainnya"] += 1

    per_cat = {cat: max(1, int(target * cnt / len(jobs))) for cat, cnt in bucket.items()}

    sampled = []
    for cat, limit in per_cat.items():
        pool = [j for j in jobs if (j["categories"][0] if j["categories"] else "Lainnya") == cat]
        pool.sort(key=lambda j: j["id"])
        idx = [i for i in range(0, len(pool), max(1, len(pool) // limit))][:limit]
        for i in idx:
            sampled.append(pool[i])

    print(f"[OK] Sampled: {len(sampled):,} jobs (stratified by category)")
    return sampled


def add_db_jobs_to_graph(G, db_jobs):
    n_added = 0
    for j in db_jobs:
        cleaned = clean_and_dedup_skills(
            ", ".join(j["skills"]),
            j["description"].lower(),
            j["job_title"],
        )
        cleaned = [s for s in cleaned if s.strip()]
        if not cleaned:
            continue

        node_id = f"id_{j['id']}"
        location = j["location"]
        G.add_node(node_id, type="job")
        attrs = {
            "job_title": j["job_title"],
            "company": j["company"],
            "skills_raw": ", ".join(cleaned),
            "job_location": location,
            "search_city": location,
            "search_country": "Indonesia",
            "first_seen": j["posted_at"],
            "job_link": j["job_url"],
            "job_type": j["employment"],
            "description": j["description"],
            "category": j["categories"][0] if j["categories"] else "",
        }
        for k, v in attrs.items():
            G.nodes[node_id][k] = v
        n_added += 1
    print(f"[OK] Added {n_added:,} Indonesian jobs")
    return G


def clean_linkedin_skills(G):
    n_cleaned = 0
    for node, data in G.nodes(data=True):
        if data.get("type") != "job":
            continue
        raw = data.get("skills_raw", "")
        if not raw:
            continue
        cleaned = clean_and_dedup_skills(raw, "", data.get("job_title", ""))
        if cleaned:
            data["skills_raw"] = ", ".join(cleaned)
            n_cleaned += 1
    print(f"[OK] Cleaned skills for {n_cleaned} LinkedIn jobs")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=75000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    G = load_linkedin_graph()
    clean_linkedin_skills(G)
    db_jobs = sample_db_jobs(args.size, args.seed)
    add_db_jobs_to_graph(G, db_jobs)

    n_jobs = sum(1 for _, d in G.nodes(data=True) if d.get("type") == "job")
    print(f"[OK] Total jobs in graph: {n_jobs:,}")

    nx.write_graphml(G, str(GRAPH_OUT))
    print(f"[OK] Saved -> {GRAPH_OUT}")


if __name__ == "__main__":
    main()
