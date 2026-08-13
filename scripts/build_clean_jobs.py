"""
Build clean job listings from graph skills + CSV descriptions.
Usage: python scripts/build_clean_jobs.py [--sample N]
"""
import csv, json, re, sys, random
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
import networkx as nx
from src.clean_skills import (SKILL_NORMALIZE, categorize_skills,
    is_stop_skill, clean_and_dedup_skills, EXTRA_STOP_SKILLS, EXTRA_STOP_PATTERNS)

DATA_DIR = Path(__file__).parent.parent / "data"
GRAPH_PATH = DATA_DIR / "graph_jobs_clean.graphml"
CSV_PATH = DATA_DIR / "jobs.csv"
OUTPUT_PATH = DATA_DIR / "clean_jobs.json"

_extra_patterns = [re.compile(p, re.IGNORECASE) for p in EXTRA_STOP_PATTERNS]

def _is_extra_stop(skill):
    s = skill.lower().strip()
    if s in EXTRA_STOP_SKILLS:
        return True
    for p in _extra_patterns:
        if p.search(s):
            return True
    return False


def main():
    sample_n = None
    if "--sample" in sys.argv:
        idx = sys.argv.index("--sample")
        sample_n = int(sys.argv[idx + 1])

    print("Loading graph...")
    G = nx.read_graphml(str(GRAPH_PATH))

    # Build graph skill lookup
    graph_skills = {}
    for node, data in G.nodes(data=True):
        if data.get("type") != "job":
            continue
        title = (data.get("job_title", "") or "").strip()
        company = (data.get("company", "") or "").strip()
        raw = data.get("skills_raw", "") or ""
        graph_skills[(title.lower(), company.lower())] = {
            "title": title, "company": company, "raw": raw,
        }

    # Load CSV descriptions
    print("Loading CSV descriptions...")
    csv_desc = {}
    with open(CSV_PATH, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("jobTitle", "") or "").lower()
            company = (row.get("companyName", "") or "").lower()
            desc = row.get("description", "") or ""
            if title and desc:
                csv_desc[(title, company)] = desc

    # Match graph jobs to CSV descriptions
    print(f"Matching {len(graph_skills)} graph jobs to CSV descriptions...")
    jobs_list = []
    matched = 0
    for (title_lower, company_lower), info in graph_skills.items():
        match_key = (title_lower, company_lower)
        description = csv_desc.get(match_key, "")
        if not description:
            for (ct, cc), d in csv_desc.items():
                if ct == title_lower:
                    description = d
                    break

        cleaned = clean_and_dedup_skills(info["raw"], description.lower(), title_lower)
        cleaned = [s for s in cleaned if not _is_extra_stop(s)]

        if cleaned:
            cat_skills = categorize_skills(cleaned)
            jobs_list.append({
                "job_title": info["title"],
                "company": info["company"],
                "description": description[:2000] if description else "",
                "skills": sorted(cleaned),
                "categorized_skills": cat_skills,
            })
            matched += 1

    if sample_n and sample_n < len(jobs_list):
        random.seed(42)
        jobs_list = random.sample(jobs_list, sample_n)

    # Save
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(jobs_list, f, indent=2, ensure_ascii=False)

    # Stats
    semua = len(jobs_list)
    with_lainnya = sum(1 for j in jobs_list if "Lainnya" in j.get("categorized_skills", {}))
    avg_skills = sum(len(j.get("skills", [])) for j in jobs_list) / max(semua, 1)

    print(f"\n{'='*50}")
    print(f"Done! Output: {OUTPUT_PATH}")
    print(f"Jobs processed: {semua:,}")
    print(f"Matched with CSV: {matched:,}")
    print(f"Avg skills/job: {avg_skills:.1f}")
    print(f"Jobs with 'Lainnya' category: {with_lainnya}/{semua}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
