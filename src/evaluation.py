import json
import math
import sys
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple

import numpy as np

from src.graph_enricher import load_enriched_graph
from src.recommender_sentence import recommend_jobs_sentence, load_and_cache_embeddings


TEST_QUERIES = [
    {
        "query": "python machine learning tensorflow pytorch deep learning",
        "relevant_skills": ["python", "machine learning", "tensorflow", "pytorch", "deep learning"],
        "description": "ML Engineer",
    },
    {
        "query": "javascript react node.js typescript full stack developer",
        "relevant_skills": ["javascript", "react", "node.js", "typescript", "full stack"],
        "description": "Full Stack Developer",
    },
    {
        "query": "java spring boot microservices aws cloud",
        "relevant_skills": ["java", "spring", "microservices", "aws", "cloud"],
        "description": "Java Backend",
    },
    {
        "query": "data analysis sql python tableau excel analytics",
        "relevant_skills": ["sql", "python", "tableau", "excel", "data analysis"],
        "description": "Data Analyst",
    },
    {
        "query": "devops docker kubernetes terraform ci/cd jenkins",
        "relevant_skills": ["docker", "kubernetes", "terraform", "ci/cd", "jenkins", "devops"],
        "description": "DevOps Engineer",
    },
    {
        "query": "product management agile strategy roadmap user research",
        "relevant_skills": ["product management", "agile", "strategy", "roadmap", "user research"],
        "description": "Product Manager",
    },
    {
        "query": "c++ c# .net software engineer windows desktop",
        "relevant_skills": ["c++", "c#", ".net", "software engineer"],
        "description": "C++/.NET Developer",
    },
    {
        "query": "ui ux design figma wireframe prototyping user research visual design",
        "relevant_skills": ["ui", "ux", "figma", "wireframe", "prototyping", "visual design"],
        "description": "UI/UX Designer",
    },
]


def is_job_relevant(job_skills: List[str], relevant_skills: Set[str], min_match: int = 1) -> bool:
    job_skills_norm = {s.strip().lower() for s in job_skills}
    matches = 0
    for rs in relevant_skills:
        for js in job_skills_norm:
            if rs in js or js in rs:
                matches += 1
                break
    return matches >= min_match


def precision_at_k(recommended: List[dict], relevant_skills: Set[str], k: int, min_match: int = 1) -> float:
    if k <= 0:
        return 0.0
    top_k = recommended[:k]
    if not top_k:
        return 0.0
    relevant_count = sum(
        1 for job in top_k
        if is_job_relevant(job.get("skills", []), relevant_skills, min_match)
    )
    return relevant_count / min(k, len(top_k))


def recall_at_k(recommended: List[dict], relevant_skills: Set[str], k: int, min_match: int = 1) -> float:
    top_k = recommended[:k]
    if not top_k:
        return 0.0
    relevant_found = sum(
        1 for job in top_k
        if is_job_relevant(job.get("skills", []), relevant_skills, min_match)
    )
    return relevant_found / max(len(top_k), 1)


def dcg_at_k(recommended: List[dict], relevant_skills: Set[str], k: int, min_match: int = 1) -> float:
    dcg = 0.0
    for i, job in enumerate(recommended[:k]):
        if is_job_relevant(job.get("skills", []), relevant_skills, min_match):
            dcg += 1.0 / math.log2(i + 2)
    return dcg


def ndcg_at_k(recommended: List[dict], relevant_skills: Set[str], k: int, min_match: int = 1) -> float:
    dcg = dcg_at_k(recommended, relevant_skills, k, min_match)
    ideal_count = min(k, len(recommended))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    return dcg / idcg if idcg > 0 else 0.0


def mrr(recommended: List[dict], relevant_skills: Set[str], min_match: int = 1) -> float:
    for i, job in enumerate(recommended):
        if is_job_relevant(job.get("skills", []), relevant_skills, min_match):
            return 1.0 / (i + 1)
    return 0.0


def run_evaluation(
    G,
    queries: List[dict],
    top_n: int = 20,
    use_kg_enhanced: bool = False,
    alpha: float = 0.6,
    beta: float = 0.2,
    ks: List[int] = [5, 10, 20],
) -> Dict:
    results = {}
    all_p_at_k = {k: [] for k in ks}
    all_r_at_k = {k: [] for k in ks}
    all_ndcg_at_k = {k: [] for k in ks}
    all_mrr = []
    all_times = []

    for tq in queries:
        query = tq["query"]
        relevant_set = set(tq["relevant_skills"])

        t0 = time.time()
        recs = recommend_jobs_sentence(
            G, query,
            top_n=top_n,
            use_kg_enhanced=use_kg_enhanced,
            alpha=alpha,
            beta=beta,
        )
        elapsed = time.time() - t0
        all_times.append(elapsed)

        for k in ks:
            all_p_at_k[k].append(precision_at_k(recs, relevant_set, k))
            all_r_at_k[k].append(recall_at_k(recs, relevant_set, k))
            all_ndcg_at_k[k].append(ndcg_at_k(recs, relevant_set, k))

        all_mrr.append(mrr(recs, relevant_set))

    results = {
        "mode": "kg_enhanced" if use_kg_enhanced else "standard",
        "num_queries": len(queries),
        "avg_time": round(float(np.mean(all_times)), 3),
        "metrics": {},
    }
    for k in ks:
        results["metrics"][f"P@{k}"] = round(float(np.mean(all_p_at_k[k])), 4)
        results["metrics"][f"R@{k}"] = round(float(np.mean(all_r_at_k[k])), 4)
        results["metrics"][f"NDCG@{k}"] = round(float(np.mean(all_ndcg_at_k[k])), 4)
    results["metrics"]["MRR"] = round(float(np.mean(all_mrr)), 4)

    return results


def print_comparison(results_list: List[Dict]):
    print(f"\n{'='*70}")
    print(f"{'Evaluation Results':^70}")
    print(f"{'='*70}")
    print()
    for res in results_list:
        mode = res["mode"]
        print(f"  Mode: {mode}")
        print(f"  Queries: {res['num_queries']}, Avg Time: {res['avg_time']}s")
        print(f"  Metrics:")
        for metric, value in res["metrics"].items():
            print(f"    {metric:>8}: {value:.4f}")
        print(f"  {'─'*50}")

    if len(results_list) == 2:
        r1, r2 = results_list[0], results_list[1]
        print(f"\n  {'Improvement (KG vs Standard):':^50}")
        print(f"  {'─'*50}")
        for metric in r1["metrics"]:
            v1 = r1["metrics"][metric]
            v2 = r2["metrics"][metric]
            delta = v2 - v1
            pct = (delta / v1 * 100) if v1 != 0 else 0
            arrow = "▲" if delta > 0 else "▼" if delta < 0 else "─"
            print(f"    {metric:>8}: {v1:.4f} → {v2:.4f}  {arrow} {pct:+.2f}%")
    print()


if __name__ == "__main__":
    print("[*] Loading enriched graph...")
    G = load_enriched_graph()
    print(f"[OK] Graph: {len(G.nodes)} nodes, {len(G.edges)} edges")

    print("[*] Running standard evaluation...")
    r_std = run_evaluation(G, TEST_QUERIES, use_kg_enhanced=False, alpha=0.7, beta=0.0)

    print("[*] Running KG-enhanced evaluation...")
    r_kg = run_evaluation(G, TEST_QUERIES, use_kg_enhanced=True, alpha=0.6, beta=0.2)

    print_comparison([r_std, r_kg])
