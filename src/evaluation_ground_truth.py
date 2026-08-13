"""
Evaluasi Rekomendasi menggunakan postings_final.csv sebagai Ground Truth.

Metrik:
1. Skill Hit Rate@K: Berapa banyak skill query ditemukan di top-K rekomendasi
2. Semantic Similarity: Cosine similarity antara query embedding dan job embedding
3. Category Agreement: Apakah rekomendasi masuk kategori yang benar
4. NDCG: Ranking quality berdasarkan skill relevance
5. Response Time

Usage:
    python -m src.evaluation_ground_truth [--sample N] [--top-n 10]
"""
import ast
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path(__file__).parent.parent / "data"
GT_PATH = DATA_DIR / "postings_final.csv"


# ──────────────────────────────────────────────────────────────
# 1. Load Ground Truth
# ──────────────────────────────────────────────────────────────

def load_ground_truth() -> pd.DataFrame:
    df = pd.read_csv(GT_PATH)

    def _parse_skills(val):
        if pd.isna(val):
            return []
        try:
            parsed = ast.literal_eval(val)
            return [s.strip().lower() for s in parsed if s.strip()]
        except (ValueError, SyntaxError):
            return [s.strip().lower() for s in str(val).split(",") if s.strip()]

    df["skills_list"] = df["skills_extracted"].apply(_parse_skills)
    df["title_lower"] = df["title"].str.lower().str.strip()
    df["category_lower"] = df["category"].str.lower().str.strip()
    return df


# ──────────────────────────────────────────────────────────────
# 2. Build Category Map dari Graph ke Ground Truth
# ──────────────────────────────────────────────────────────────

def build_category_map(df: pd.DataFrame) -> dict:
    """
    Bangun mapping: graph job title -> ground truth category.
    Menggunakan fuzzy match pada title.
    """
    cat_map = {}
    gt_titles = df["title_lower"].values
    gt_categories = df["category_lower"].values

    # Build index berdasarkan kata kunci unik
    title_to_cat = {}
    for title, cat in zip(gt_titles, gt_categories):
        title_to_cat[title] = cat

    return title_to_cat


def match_job_category(job_title: str, title_to_cat: dict) -> str:
    """Match job title ke ground truth category."""
    title_lower = job_title.lower().strip()

    # Exact match
    if title_lower in title_to_cat:
        return title_to_cat[title_lower]

    # Partial match
    for gt_title, cat in title_to_cat.items():
        if title_lower in gt_title or gt_title in title_lower:
            return cat

    return "unknown"


# ──────────────────────────────────────────────────────────────
# 3. Generate Test Queries
# ──────────────────────────────────────────────────────────────

def generate_test_queries(df: pd.DataFrame, n: int = 30, seed: int = 42) -> list:
    rng = np.random.RandomState(seed)

    # Stratified sampling: ambil dari berbagai kategori
    categories = df["category"].value_counts()
    top_cats = categories.head(15).index.tolist()  # Top 15 kategori

    queries = []
    per_cat = max(1, n // len(top_cats))

    for cat in top_cats:
        cat_df = df[df["category"] == cat]
        valid = cat_df[cat_df["skills_list"].apply(len) >= 3]
        if len(valid) == 0:
            continue
        n_sample = min(per_cat, len(valid))
        samples = valid.sample(n=n_sample, random_state=rng)
        for _, row in samples.iterrows():
            skills = row["skills_list"]
            query_skills = skills[:6]
            queries.append({
                "query": " ".join(query_skills),
                "expected_category": row["category"],
                "expected_skills": set(skills),
                "job_title": row["title"],
            })

    # Shuffle dan ambil n
    rng.shuffle(queries)
    return queries[:n]


# ──────────────────────────────────────────────────────────────
# 4. Metric Functions
# ──────────────────────────────────────────────────────────────

def skill_hit_rate(recommended: list, expected_skills: set, k: int) -> float:
    """Berapa persen skill query ditemukan di setidaknya 1 job top-k."""
    if not expected_skills:
        return 0.0
    top_k = recommended[:k]
    all_job_skills = set()
    for job in top_k:
        job_skills = set(s.lower() for s in job.get("skills", []))
        all_job_skills.update(job_skills)

    hits = len(all_job_skills & expected_skills)
    return hits / len(expected_skills)


def skill_overlap_jaccard(recommended: list, expected_skills: set, k: int) -> float:
    """Rata-rata Jaccard similarity skill antara rekomendasi dan expected."""
    top_k = recommended[:k]
    if not top_k:
        return 0.0
    scores = []
    for job in top_k:
        job_skills = set(s.lower() for s in job.get("skills", []))
        if not job_skills or not expected_skills:
            scores.append(0.0)
            continue
        intersection = len(job_skills & expected_skills)
        union = len(job_skills | expected_skills)
        scores.append(intersection / union if union > 0 else 0.0)
    return float(np.mean(scores))


def category_agreement(recommended: list, expected_category: str, title_to_cat: dict, k: int) -> float:
    """Berapa persen top-k rekomendasi kategorinya sesuai dengan expected."""
    top_k = recommended[:k]
    if not top_k:
        return 0.0
    matches = 0
    for job in top_k:
        job_cat = match_job_category(job.get("job_title", ""), title_to_cat)
        if job_cat == expected_category.lower():
            matches += 1
        elif job_cat != "unknown" and job_cat in expected_category.lower():
            matches += 1
    return matches / k


def ndcg_at_k(recommended: list, expected_skills: set, k: int) -> float:
    dcg = 0.0
    for i, job in enumerate(recommended[:k]):
        job_skills = set(s.lower() for s in job.get("skills", []))
        relevance = len(job_skills & expected_skills)
        if relevance > 0:
            dcg += relevance / math.log2(i + 2)
    ideal_relevance = len(expected_skills)
    idcg = sum(ideal_relevance / math.log2(i + 2) for i in range(min(k, len(recommended))))
    return dcg / idcg if idcg > 0 else 0.0


def mean_reciprocal_rank(recommended: list, expected_skills: set) -> float:
    """MRR: seberapa cepat skill pertama ditemukan."""
    for i, job in enumerate(recommended):
        job_skills = set(s.lower() for s in job.get("skills", []))
        if job_skills & expected_skills:
            return 1.0 / (i + 1)
    return 0.0


# ──────────────────────────────────────────────────────────────
# 5. Semantic Similarity (opsional, butuh model)
# ──────────────────────────────────────────────────────────────

def compute_query_job_similarity(query: str, recommended: list, model) -> float:
    """Rata-rata cosine similarity antara query embedding dan job embeddings."""
    if not recommended or model is None:
        return 0.0
    from src.recommender_sentence import normalize
    q_emb = model.encode([normalize(query)], convert_to_numpy=True)
    q_emb = q_emb / (np.linalg.norm(q_emb) + 1e-12)

    from src.recommender_sentence import JOB_EMB_ARRAY, JOB_NODE_IDS, JOB_METAS, NODEID_TO_INDEX
    if JOB_EMB_ARRAY is None:
        return 0.0

    sims = []
    for job in recommended:
        job_title = job.get("job_title", "")
        # Cari job di embedding array
        for jid, jmeta in enumerate(JOB_METAS):
            if jmeta.get("job_title") == job_title:
                job_emb = JOB_EMB_ARRAY[jid]
                sim = float(np.dot(q_emb.flatten(), job_emb))
                sims.append(sim)
                break
        else:
            sims.append(0.0)

    return float(np.mean(sims)) if sims else 0.0


# ──────────────────────────────────────────────────────────────
# 6. Run Evaluation
# ──────────────────────────────────────────────────────────────

def run_ground_truth_evaluation(
    G,
    n_queries: int = 30,
    top_n: int = 12,
    ks: list = [3, 5, 10],
    use_kg_enhanced: bool = True,
    alpha: float = 0.5,
    beta: float = 0.25,
) -> tuple:
    from src.recommender_sentence import (
        recommend_jobs_sentence,
        load_and_cache_embeddings,
        get_model,
    )
    from src.graph_enricher import load_enriched_graph

    df = load_ground_truth()
    title_to_cat = build_category_map(df)
    queries = generate_test_queries(df, n=n_queries)

    print(f"[*] Ground truth: {len(df):,} jobs, {df['category'].nunique()} categories")
    print(f"[*] Test queries: {len(queries)}, top_n={top_n}\n")

    results_per_query = []
    all_skill_hit = {k: [] for k in ks}
    all_skill_overlap = {k: [] for k in ks}
    all_category_agree = {k: [] for k in ks}
    all_ndcg = {k: [] for k in ks}
    all_mrr = []
    all_times = []

    for i, q in enumerate(queries):
        t0 = time.time()
        recs = recommend_jobs_sentence(
            G,
            q["query"],
            top_n=top_n,
            use_kg_enhanced=use_kg_enhanced,
            alpha=alpha,
            beta=beta,
        )
        elapsed = time.time() - t0
        all_times.append(elapsed)

        for k in ks:
            all_skill_hit[k].append(skill_hit_rate(recs, q["expected_skills"], k))
            all_skill_overlap[k].append(skill_overlap_jaccard(recs, q["expected_skills"], k))
            all_category_agree[k].append(category_agreement(recs, q["expected_category"], title_to_cat, k))
            all_ndcg[k].append(ndcg_at_k(recs, q["expected_skills"], k))

        all_mrr.append(mean_reciprocal_rank(recs, q["expected_skills"]))

        # Get matched categories
        matched_cats = [match_job_category(r.get("job_title", ""), title_to_cat) for r in recs[:5]]

        results_per_query.append({
            "query": q["query"][:80],
            "expected_category": q["expected_category"],
            "job_title": q["job_title"],
            "num_results": len(recs),
            "matched_categories": matched_cats,
            "top_skills_found": list(q["expected_skills"] & set(
                s for r in recs[:3] for s in r.get("skills", [])
            ))[:5],
            "time": round(elapsed, 3),
        })

        status = "✓" if q["expected_category"].lower() in matched_cats else "○"
        print(f"  {status} [{i+1}/{len(queries)}] '{q['query'][:50]}...' -> {len(recs)} results ({elapsed:.2f}s)")

    # ── Aggregate ──
    summary = {
        "num_queries": len(queries),
        "top_n": top_n,
        "ground_truth_jobs": len(df),
        "ground_truth_categories": df["category"].nunique(),
        "avg_time": round(float(np.mean(all_times)), 3),
        "metrics": {},
    }

    for k in ks:
        summary["metrics"][f"Skill_Hit_Rate@{k}"] = round(float(np.mean(all_skill_hit[k])), 4)
        summary["metrics"][f"Skill_Jaccard@{k}"] = round(float(np.mean(all_skill_overlap[k])), 4)
        summary["metrics"][f"Category_Agreement@{k}"] = round(float(np.mean(all_category_agree[k])), 4)
        summary["metrics"][f"NDCG@{k}"] = round(float(np.mean(all_ndcg[k])), 4)
    summary["metrics"]["MRR"] = round(float(np.mean(all_mrr)), 4)

    # Category distribution of matched results
    all_matched_cats = []
    for r in results_per_query:
        all_matched_cats.extend(r["matched_categories"])
    cat_dist = Counter(all_matched_cats)
    summary["category_distribution"] = dict(cat_dist.most_common(15))

    return summary, results_per_query


# ──────────────────────────────────────────────────────────────
# 7. Visualizations
# ──────────────────────────────────────────────────────────────

def save_visualizations(summary: dict, results: list, output_dir: str = None):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns
    except ImportError:
        print("[!] matplotlib/seaborn not installed, skipping visualizations")
        return

    if output_dir is None:
        output_dir = str(DATA_DIR / "evaluation_results")
    os.makedirs(output_dir, exist_ok=True)

    sns.set_style("whitegrid")
    colors = ["#2196F3", "#4CAF50", "#FF9800", "#9C27B0", "#F44336"]

    # 1. Grouped bar chart: Metrics per K
    metrics = summary["metrics"]
    metric_groups = defaultdict(list)
    for key, val in metrics.items():
        parts = key.rsplit("@", 1)
        name = parts[0]
        metric_groups[name].append(val)

    # Filter only groups with exactly 3 values (for K=3,5,10)
    metric_groups = {k: v for k, v in metric_groups.items() if len(v) == 3}

    fig, ax = plt.subplots(figsize=(12, 6))
    group_names = list(metric_groups.keys())
    x = np.arange(len(group_names))
    width = 0.25

    for idx, k in enumerate([3, 5, 10]):
        vals = [metric_groups[g][idx] for g in group_names]
        bars = ax.bar(x + idx * width, vals, width, label=f"K={k}", color=colors[idx])
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                    f"{val:.3f}", ha="center", va="bottom", fontsize=8)

    ax.set_ylabel("Score")
    ax.set_title("Rekomendasi Evaluation Metrics (Ground Truth: postings_final.csv)")
    ax.set_xticks(x + width)
    ax.set_xticklabels(group_names, rotation=15, ha="right")
    ax.legend()
    ax.set_ylim(0, 1)
    plt.tight_layout()
    plt.savefig(f"{output_dir}/metrics_grouped_bar.png", dpi=150)
    plt.close()
    print(f"[OK] Saved {output_dir}/metrics_grouped_bar.png")

    # 2. Pie chart: Category distribution
    cat_dist = summary.get("category_distribution", {})
    if cat_dist:
        fig, ax = plt.subplots(figsize=(10, 8))
        labels = list(cat_dist.keys())
        sizes = list(cat_dist.values())
        total = sum(sizes)
        # Only show labels for slices > 3%
        show_labels = [l if s/total > 0.03 else "" for l, s in zip(labels, sizes)]
        colors_pie = plt.cm.Set3(np.linspace(0, 1, len(labels)))
        wedges, texts, autotexts = ax.pie(
            sizes, labels=show_labels, autopct=lambda p: f"{p:.1f}%" if p > 3 else "",
            colors=colors_pie, startangle=90
        )
        ax.set_title("Distribusi Kategori Hasil Rekomendasi")
        plt.tight_layout()
        plt.savefig(f"{output_dir}/category_distribution.png", dpi=150)
        plt.close()
        print(f"[OK] Saved {output_dir}/category_distribution.png")

    # 3. Heatmap: Category Agreement per Query
    cat_data = []
    for r in results:
        cat_data.append({
            "query": r["query"][:30],
            "expected": r["expected_category"],
            "found_in_top5": r["expected_category"].lower() in r["matched_categories"],
        })
    if cat_data:
        cat_df = pd.DataFrame(cat_data)
        fig, ax = plt.subplots(figsize=(10, max(6, len(cat_data) * 0.4)))
        colors_bar = ["#4CAF50" if x else "#F44336" for x in cat_df["found_in_top5"]]
        bars = ax.barh(range(len(cat_df)), [1]*len(cat_df), color=colors_bar, edgecolor="white")
        ax.set_yticks(range(len(cat_df)))
        ax.set_yticklabels([f"{r['expected']}: {r['query'][:25]}" for _, r in cat_df.iterrows()], fontsize=8)
        ax.set_xlim(0, 1.2)
        ax.set_xticks([])
        ax.set_title("Category Agreement (Green=MATCH, Red=MISS)")
        plt.tight_layout()
        plt.savefig(f"{output_dir}/category_agreement.png", dpi=150)
        plt.close()
        print(f"[OK] Saved {output_dir}/category_agreement.png")

    # 4. Response time distribution
    times = [r["time"] for r in results]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(times, bins=15, color="#2196F3", edgecolor="white", alpha=0.8)
    ax.axvline(np.mean(times), color="#F44336", linestyle="--", label=f"Mean: {np.mean(times):.2f}s")
    ax.set_xlabel("Response Time (seconds)")
    ax.set_ylabel("Frequency")
    ax.set_title("Distribusi Response Time per Query")
    ax.legend()
    plt.tight_layout()
    plt.savefig(f"{output_dir}/response_time.png", dpi=150)
    plt.close()
    print(f"[OK] Saved {output_dir}/response_time.png")


# ──────────────────────────────────────────────────────────────
# 8. Print Report
# ──────────────────────────────────────────────────────────────

def print_report(summary: dict, results: list):
    print(f"\n{'='*70}")
    print(f"{'EVALUATION REPORT':^70}")
    print(f"{'(Ground Truth: postings_final.csv)':^70}")
    print(f"{'='*70}")
    print(f"  Ground Truth Jobs    : {summary['ground_truth_jobs']:,}")
    print(f"  Categories           : {summary['ground_truth_categories']}")
    print(f"  Test Queries         : {summary['num_queries']}")
    print(f"  Top-N                : {summary['top_n']}")
    print(f"  Avg Response Time    : {summary['avg_time']}s")
    print(f"{'─'*70}")

    print(f"\n  {'METRICS PER K':^50}")
    print(f"  {'─'*50}")
    for metric, value in summary["metrics"].items():
        bar_len = int(value * 40)
        bar = "█" * bar_len + "░" * (40 - bar_len)
        print(f"  {metric:<30} {value:.4f}  {bar}")

    print(f"\n  {'CATEGORY DISTRIBUTION (Matched)':^50}")
    print(f"  {'─'*50}")
    total = sum(summary.get("category_distribution", {}).values()) or 1
    for cat, count in summary.get("category_distribution", {}).items():
        pct = count / total * 100
        bar = "█" * int(pct / 2)
        print(f"  {cat:<30} {count:>4} ({pct:.1f}%) {bar}")

    print(f"\n  {'SAMPLE RESULTS':^50}")
    print(f"  {'─'*50}")
    for r in results[:5]:
        match = "✓" if r["expected_category"].lower() in r["matched_categories"] else "✗"
        print(f"  {match} Query: {r['query'][:55]}...")
        print(f"    Expected: {r['expected_category']}")
        print(f"    Matched : {', '.join(r['matched_categories'][:5])}")
        print(f"    Skills  : {', '.join(r['top_skills_found'][:5])}")
        print(f"    Results : {r['num_results']} jobs ({r['time']}s)")
        print()

    print(f"{'='*70}\n")


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate recommendations using ground truth")
    parser.add_argument("--sample", type=int, default=30, help="Number of test queries")
    parser.add_argument("--top-n", type=int, default=12, help="Number of recommendations per query")
    parser.add_argument("--no-kg", action="store_true", help="Disable KG-enhanced scoring")
    args = parser.parse_args()

    from src.recommender_sentence import load_and_cache_embeddings
    from src.graph_enricher import load_enriched_graph

    print("[*] Loading graph...")
    G = load_enriched_graph()
    print(f"[OK] Graph: {len(G.nodes)} nodes, {len(G.edges)} edges")

    print("[*] Loading embeddings...")
    load_and_cache_embeddings(G)
    print("[OK] Embeddings ready\n")

    summary, results = run_ground_truth_evaluation(
        G,
        n_queries=args.sample,
        top_n=args.top_n,
        use_kg_enhanced=not args.no_kg,
    )

    print_report(summary, results)

    # Save results
    output_dir = str(DATA_DIR / "evaluation_results")
    os.makedirs(output_dir, exist_ok=True)

    with open(f"{output_dir}/evaluation_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[OK] Saved {output_dir}/evaluation_summary.json")

    with open(f"{output_dir}/evaluation_details.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"[OK] Saved {output_dir}/evaluation_details.json")

    save_visualizations(summary, results, output_dir)
