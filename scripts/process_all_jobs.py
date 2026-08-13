"""
Pipeline: Process ALL 623K jobs from jobs.csv
- Load graph skills vocabulary (41K skills)
- Match graph jobs by title+company for rich skills (4.5K jobs)
- Keyword matching from descriptions for the rest
- Use categoriesName as domain tags
- Output: data/all_jobs_clean.jsonl

Usage:
    python3 scripts/process_all_jobs.py              # full run
    python3 scripts/process_all_jobs.py --sample 100 # sample only
"""

import csv
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import networkx as nx
from src.clean_skills import categorize_skills, is_stop_skill, SKILL_NORMALIZE

DATA_DIR = Path(__file__).parent.parent / "data"

# ── 1. Load skills vocabulary from graph ──────────────────────────

def load_graph_vocabulary():
    G = nx.read_graphml(DATA_DIR / "graph_jobs_clean.graphml")

    # Build skill vocabulary from graph
    vocab = set()
    graph_skills_by_job = {}  # normalized title+company -> set of skills

    for n, d in G.nodes(data=True):
        raw = d.get("skills_raw", "")
        if raw:
            for s in raw.split(","):
                s = s.strip().lower()
                if s and len(s) <= 60:
                    vocab.add(s)

    # Also index graph jobs by title+company for later matching
    for n, d in G.nodes(data=True):
        if d.get("type") == "job":
            title = d.get("job_title", "").strip().lower()
            company = d.get("company", "").strip().lower()
            key = f"{title}|{company}"
            raw = d.get("skills_raw", "")
            skills = set()
            if raw:
                for s in raw.split(","):
                    s2 = s.strip().lower()
                    if s2:
                        skills.add(s2)
            graph_skills_by_job[key] = skills

    # Separate single-word vs multi-word for efficient matching
    single = {s for s in vocab if " " not in s and len(s) > 1}
    # Only keep short multi-word skills (<=40 chars) — longer are noisy fragments
    multi_phrases = [s for s in vocab if " " in s and 1 < len(s) <= 40]
    # Index by first word for fast lookup
    multi_index = {}
    for s in multi_phrases:
        first = s.split(" ", 1)[0]
        multi_index.setdefault(first, []).append(s)

    print(f"[OK] Skills vocab: {len(vocab):,} ({len(single):,} single, {len(multi_phrases):,} multi)")
    print(f"[OK] Graph jobs indexed: {len(graph_skills_by_job):,}")
    return vocab, single, multi_phrases, multi_index, graph_skills_by_job


# ── 2. Build regex for single-word skills ─────────────────────────

def build_single_word_pattern(single_words):
    # Escape and sort by length desc to match longest first
    esc = sorted([re.escape(s) for s in single_words], key=len, reverse=True)
    # Split into chunks of 10K to avoid regex compilation issues
    chunk_size = 10000
    patterns = []
    for i in range(0, len(esc), chunk_size):
        chunk = esc[i:i + chunk_size]
        p = re.compile(r"\b(?:" + "|".join(chunk) + r")\b", re.IGNORECASE)
        patterns.append(p)
    print(f"[OK] Built {len(patterns)} single-word regex chunks")
    return patterns


# ── 3. Process a chunk of CSV rows ────────────────────────────────

def process_chunk(rows, single_patterns, multi_index, graph_skills_by_job):
    results = []
    for row in rows:
        job = extract_basic_info(row)
        if not job:
            continue
        title = job["job_title"].strip().lower()
        company = job["company"].strip().lower() if job.get("company") else ""
        key = f"{title}|{company}"
        if key in graph_skills_by_job:
            raw_skills = graph_skills_by_job[key]
        else:
            desc = job.get("description_raw", "")
            raw_skills = extract_skills(desc, single_patterns, multi_index)
        cleaned = []
        seen = set()
        for s in raw_skills:
            sk = s.strip().lower()
            norm = SKILL_NORMALIZE.get(sk, sk)
            if norm in seen or is_stop_skill(norm):
                continue
            seen.add(norm)
            cleaned.append(norm)
        categorized = categorize_skills(cleaned)
        job["skills"] = cleaned
        job["categorized_skills"] = categorized
        results.append(job)
    return results


def extract_basic_info(row):
    try:
        desc = row.get("description", "")
        return {
            "csv_id": row.get("id", ""),
            "job_title": row.get("jobTitle", "").strip(),
            "company": row.get("companyName", "").strip(),
            "location": row.get("locations", "").strip(),
            "employment": row.get("employment", "").strip(),
            "salary_min": row.get("salaryMin", ""),
            "salary_max": row.get("salaryMax", ""),
            "salary_currency": row.get("salarycurrency", ""),
            "salary_period": row.get("salaryPeriod", ""),
            "posted_at": row.get("postedAt", ""),
            "job_url": row.get("jobUrl", ""),
            "description_raw": desc[:300],  # keep raw for matching
            "categories": [c.strip() for c in row.get("categoriesName", "").split(",") if c.strip()],
        }
    except Exception as e:
        return None


def extract_skills(desc, single_patterns, multi_index):
    if not desc or len(desc) < 10:
        return set()

    desc_lower = desc.lower()
    found = set()

    # Match single-word skills
    for pat in single_patterns:
        for m in pat.finditer(desc_lower):
            found.add(m.group(0).lower())

    # Match multi-word skills using first-word index
    desc_words = set(desc_lower.split())
    for first_word, phrases in multi_index.items():
        if first_word not in desc_words:
            continue
        for phrase in phrases:
            if phrase in desc_lower:
                found.add(phrase)

    return found


# ── 4. Main pipeline ──────────────────────────────────────────────

def main():
    sample_mode = "--sample" in sys.argv
    sample_n = 100
    for a in sys.argv:
        if a.startswith("--sample="):
            sample_n = int(a.split("=")[1])
            sample_mode = True

    t_start = time.time()

    # Load graph vocabulary
    print("[1/4] Loading graph vocabulary...")
    vocab, single, multi, multi_index, graph_jobs = load_graph_vocabulary()
    single_patterns = build_single_word_pattern(single)

    # Read CSV
    csv_path = DATA_DIR / "jobs.csv"
    print(f"[2/4] Reading {csv_path.name}...")
    total_rows = sum(1 for _ in open(csv_path, "r", encoding="utf-8")) - 1
    print(f"      Total rows in CSV: {total_rows:,}")

    # Output
    out_path = DATA_DIR / "all_jobs_clean.jsonl"
    out_tmp = out_path.with_suffix(".jsonl.tmp")

    processed = 0
    matched_graph = 0
    total_skills_found = 0
    chunk_size = 50000

    with open(csv_path, "r", encoding="utf-8") as f_in, \
         open(out_tmp, "w", encoding="utf-8") as f_out:

        reader = csv.DictReader(f_in)
        chunk = []

        for row_idx, row in enumerate(reader):
            if sample_mode and row_idx >= sample_n:
                break

            chunk.append(row)

            if len(chunk) >= chunk_size or (sample_mode and row_idx + 1 == sample_n):
                results = process_chunk(
                    chunk, single_patterns, multi_index, graph_jobs
                )
                for j in results:
                    f_out.write(json.dumps(j, ensure_ascii=False) + "\n")

                processed += len(results)
                matched_graph += sum(
                    1 for r in results
                    if f"{r['job_title'].lower()}|{r['company'].lower()}" in graph_jobs
                )
                total_skills_found += sum(len(r.get("skills", [])) for r in results)

                elapsed = time.time() - t_start
                rate = processed / elapsed if elapsed > 0 else 0
                print(f"      [{processed:>7,}/{total_rows:,}] "
                      f"{elapsed:.0f}s | {rate:.0f} jobs/s | "
                      f"graph={matched_graph:,} | skills={total_skills_found:,}",
                      end="\r")
                chunk = []

        # Process remaining
        if chunk:
            results = process_chunk(
                chunk, single_patterns, multi_index, graph_jobs
            )
            for j in results:
                f_out.write(json.dumps(j, ensure_ascii=False) + "\n")
            processed += len(results)

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"Done! Output: {out_tmp}")
    print(f"Jobs processed: {processed:,}")
    print(f"Matched from graph: {matched_graph:,}")
    print(f"Total skills found: {total_skills_found:,}")
    if processed > 0:
        print(f"Avg skills/job: {total_skills_found/processed:.1f}")
    print(f"Time: {elapsed:.0f}s ({processed/elapsed:.0f} jobs/s)")
    print(f"{'='*60}")

    if not sample_mode:
        out_tmp.rename(out_path)
        print(f"Final: {out_path}")
        print(f"File size: {out_path.stat().st_size / 1024 / 1024:.0f} MB")


if __name__ == "__main__":
    main()
