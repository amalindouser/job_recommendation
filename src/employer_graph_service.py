import json
import os
import re
from pathlib import Path
import numpy as np
import networkx as nx
from collections import Counter
from sklearn.metrics.pairwise import cosine_similarity

from src.recommender_sentence import (
    normalize,
    get_model,
    JOB_EMB_ARRAY,
    JOB_METAS,
    JOB_NODE_IDS,
    NODEID_TO_INDEX,
)

USER_GRAPH_PATH = Path(__file__).parent.parent / "data" / "user_vacancies.graphml"


# =========================================
# FEATURE 1 - Smart Job Title Analysis
# =========================================

_JOB_STOPWORDS = {
    "senior", "staff", "junior", "lead", "principal",
    "manager", "director", "head", "of", "and", "the", "for", "with",
    "associate", "intern", "trainee", "entry", "level",
    "i", "ii", "iii", "iv", "v",
    "1", "2", "3", "4", "5", "sr", "jr", "mid", "intermediate",
    "experienced", "or", "in", "to", "a", "an", "is", "on", "at", "by",
    "vp", "svp", "evp", "cfo", "ceo", "cto", "coo", "chief",
    "vice", "president",
}

def _significant_words(text):
    words = normalize(text).split()
    return [w for w in words if w not in _JOB_STOPWORDS]


def _keyword_overlap(query, title):
    q_sig = _significant_words(query)
    t_sig = _significant_words(title)
    if not q_sig:
        return 0.0
    if not t_sig:
        return 0.0
    q_set = set(q_sig)
    t_set = set(t_sig)
    common = q_set & t_set
    if not common:
        return 0.0
    # Jaccard-like: common / unique(query ∪ title)
    return len(common) / len(q_set | t_set)


def find_similar_jobs_by_title(title, G, top_n=10):
    title_norm = normalize(title)
    if not title_norm:
        return []

    if JOB_EMB_ARRAY is not None and len(JOB_METAS) > 0:
        title_emb = get_model().encode(title_norm, convert_to_numpy=True)
        title_emb = title_emb / (np.linalg.norm(title_emb) + 1e-12)
        sims = cosine_similarity(title_emb.reshape(1, -1), JOB_EMB_ARRAY)[0]
        top_indices = np.argsort(sims)[::-1][:top_n * 5]

        candidates = []
        seen_job_texts = set()
        for idx in top_indices:
            meta = JOB_METAS[idx]
            text = normalize(f"{meta.get('job_title', '')} {meta.get('company', '')}")
            if text in seen_job_texts:
                continue

            job_title = meta.get("job_title", "")
            kw_score = _keyword_overlap(title_norm, job_title)
            combined = float(sims[idx]) * 0.4 + kw_score * 0.6
            if kw_score > 0.0 and combined >= 0.15:
                seen_job_texts.add(text)
                node_id = JOB_NODE_IDS[idx] if idx < len(JOB_NODE_IDS) else None
                skills = _get_node_skills(node_id, G)
                candidates.append({
                    "node_id": node_id,
                    "job_title": job_title,
                    "company": meta.get("company", ""),
                    "skills": skills,
                    "similarity": float(sims[idx]),
                    "keyword_score": kw_score,
                    "combined": combined,
                })

        if not candidates:
            seen2 = set()
            for idx in top_indices:
                meta = JOB_METAS[idx]
                text = normalize(f"{meta.get('job_title', '')} {meta.get('company', '')}")
                if text in seen2:
                    continue
                seen2.add(text)
                job_title = meta.get("job_title", "")
                kw_score = _keyword_overlap(title_norm, job_title)
                combined = float(sims[idx]) * 0.6 + kw_score * 0.4
                if combined < 0.15:
                    continue
                node_id = JOB_NODE_IDS[idx] if idx < len(JOB_NODE_IDS) else None
                skills = _get_node_skills(node_id, G)
                candidates.append({
                    "node_id": node_id,
                    "job_title": job_title,
                    "company": meta.get("company", ""),
                    "skills": skills,
                    "similarity": float(sims[idx]),
                    "keyword_score": kw_score,
                    "combined": combined,
                })

        candidates.sort(key=lambda x: x["combined"], reverse=True)
        return candidates[:top_n]
    else:
        candidates = []
        for n, d in G.nodes(data=True):
            if d.get("type") != "job":
                continue
            job_title = d.get("job_title", "")
            if not job_title:
                continue
            score = _text_similarity(title_norm, normalize(job_title))
            if score > 0.3:
                candidates.append((score, n, d))
        candidates.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, n, d in candidates[:top_n]:
            skills = _get_node_skills(n, G)
            results.append({
                "node_id": n,
                "job_title": d.get("job_title", ""),
                "company": d.get("company", ""),
                "skills": skills,
                "similarity": score,
            })
        return results


def _get_node_skills(node_id, G):
    if node_id is None or node_id not in G:
        return []
    skills = []
    for succ in G.successors(node_id):
        sd = G.nodes.get(succ, {})
        if sd.get("type") == "skill":
            label = sd.get("label", succ)
            if label:
                skills.append(label)
    return skills


def _text_similarity(a, b):
    a_words = set(a.split())
    b_words = set(b.split())
    if not a_words or not b_words:
        return 0.0
    intersection = a_words & b_words
    union = a_words | b_words
    return len(intersection) / len(union)


def _unique_query_match(query_words, title_words):
    if not query_words:
        return 0.0
    common = query_words & title_words
    if not common:
        return 0.0
    # Fraction of query words that appear in title
    return len(common) / len(query_words)


def analyze_job_title(title, G, top_n=10):
    similar = find_similar_mixed(title, G, top_n=top_n)

    # --- Ontology fallback enrichment ---
    from src.ontology_service import get_ontology
    ontology = get_ontology()
    ontology_skills = ontology.get_skills_for_job(title)

    if not similar and not ontology_skills:
        return {
            "title": title,
            "similar_jobs_found": 0,
            "recommended_skills": [],
            "related_titles": [],
            "confidence": 0.0,
        }

    if not similar:
        # Pure ontology fallback
        recommended = []
        for s in ontology_skills:
            recommended.append({"skill": s.replace("_", " ").title(), "frequency": 1.0, "percentage": 100})
            if len(recommended) >= 20:
                break
        return {
            "title": title,
            "similar_jobs_found": 0,
            "recommended_skills": recommended,
            "related_titles": [],
            "confidence": 0.5,
            "source": "ontology",
        }

    query_words = set(_significant_words(title))
    all_title_words = Counter()
    for job in similar:
        for w in _significant_words(job.get("job_title", "")):
            all_title_words[w] += 1
    most_common_word = all_title_words.most_common(1)[0][0] if all_title_words else None

    skill_weight = Counter()
    title_weight = Counter()
    total_weight = 0.0

    for job in similar:
        kw = job.get("keyword_score", 0)
        sim = job.get("similarity", 0)

        job_words = set(_significant_words(job.get("job_title", "")))
        unique_query = query_words - {most_common_word} if most_common_word else query_words
        if unique_query:
            shared_unique = unique_query & job_words
            bonus = 2.0 if shared_unique else 1.0
        else:
            bonus = 1.0

        weight = max(kw * 0.6 + sim * 0.4, 0.05) * bonus
        total_weight += weight
        for skill in job.get("skills", []):
            skill_weight[skill] += weight
        t = job.get("job_title", "")
        if t:
            title_weight[t] += weight

    # Merge ontology skills with lower weight
    if ontology_skills:
        onto_weight = total_weight * 0.15 / max(len(ontology_skills), 1)
        for s in ontology_skills:
            skill_weight[s.replace("_", " ").title()] += onto_weight
            total_weight += onto_weight

    recommended_skills = []
    for skill, w in skill_weight.most_common(30):
        freq_pct = round(w / total_weight * 100) if total_weight > 0 else 0
        if freq_pct < 5:
            continue
        recommended_skills.append({
            "skill": skill,
            "frequency": round(w, 1),
            "percentage": freq_pct,
        })
        if len(recommended_skills) >= 20:
            break

    total_jobs = len(similar)
    related_titles = []
    for t, w in title_weight.most_common(10):
        related_titles.append({
            "title": t,
            "count": round(w, 1),
        })

    skill_confidence = min(1.0, sum(s["percentage"] for s in recommended_skills[:5]) / 500) if recommended_skills else 0
    confidence = round(skill_confidence, 2)

    graph_elements = build_analysis_graph(title, recommended_skills[:5], related_titles[:5])

    return {
        "title": title,
        "similar_jobs_found": total_jobs,
        "recommended_skills": recommended_skills,
        "related_titles": related_titles,
        "confidence": confidence,
        "graph_elements": graph_elements,
    }


# =========================================
# FEATURE 2 - Analysis Graph Builder
# =========================================

def build_analysis_graph(job_title, top_skills, top_titles):
    elements = {"nodes": [], "edges": []}
    seen = set()

    def add_node(nid, label, ntype):
        if nid in seen:
            return
        seen.add(nid)
        elements["nodes"].append({"data": {"id": nid, "label": label, "type": ntype}})

    def add_edge(src, tgt, label=""):
        elements["edges"].append({"data": {"source": src, "target": tgt, "label": label}})

    job_id = "analysis_job"
    add_node(job_id, job_title, "job")

    for s in top_skills:
        sid = f"ask_{s['skill'].replace(' ', '_')}"
        add_node(sid, s["skill"], "skill")
        add_edge(job_id, sid, "REQUIRES_SKILL")
        # connect skill to related titles
        for t in top_titles:
            tid = f"art_{t['title'].replace(' ', '_')}"
            add_node(tid, t["title"], "related_job")
            add_edge(sid, tid, "APPEARS_IN")

    return elements


# =========================================
# USER VACANCIES INTEGRATION - growable graph
# =========================================

def _load_user_vacancies():
    import json
    from pathlib import Path
    path = Path(__file__).parent.parent / "data" / "vacancies.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _search_user_vacancies(title, G, top_n=5):
    vacancies = _load_user_vacancies()
    if not vacancies:
        return []

    title_norm = normalize(title)
    title_emb = get_model().encode(title_norm, convert_to_numpy=True)
    title_emb = title_emb / (np.linalg.norm(title_emb) + 1e-12)

    candidates = []
    seen = set()
    for v in vacancies:
        vt = v.get("job_title", "").strip()
        if not vt or vt.lower() in seen:
            continue
        seen.add(vt.lower())

        vt_emb = get_model().encode(normalize(vt), convert_to_numpy=True)
        vt_emb = vt_emb / (np.linalg.norm(vt_emb) + 1e-12)
        sim = float(cosine_similarity(title_emb.reshape(1, -1), vt_emb.reshape(1, -1))[0][0])

        kw_score = _keyword_overlap(title_norm, vt)
        combined = sim * 0.4 + kw_score * 0.6
        if kw_score <= 0.0 and sim < 0.5:
            continue
        if combined < 0.20:
            continue

        skills = v.get("skills", [])
        candidates.append({
            "node_id": f"user_vacancy_{v.get('id', 'unknown')}",
            "job_title": vt,
            "company": v.get("company", ""),
            "skills": skills,
            "similarity": sim,
            "keyword_score": kw_score,
            "combined": combined,
            "source": "user",
        })

    candidates.sort(key=lambda x: x["combined"], reverse=True)
    return candidates[:top_n]


def find_similar_mixed(title, G, top_n=10):
    graph_jobs = find_similar_jobs_by_title(title, G, top_n=top_n)
    user_jobs = _search_user_vacancies(title, G, top_n=max(3, top_n // 2))

    all_jobs = graph_jobs + user_jobs
    seen = set()
    merged = []
    for j in all_jobs:
        key = normalize(j.get("job_title", ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(j)
    merged.sort(key=lambda x: x.get("combined", x.get("similarity", 0)), reverse=True)
    return merged[:top_n]


# =========================================
# FEATURE 3 - Skill Recommendation
# =========================================

def get_recommended_skills(analysis_result, min_percentage=20):
    return [s for s in analysis_result.get("recommended_skills", [])
            if s["percentage"] >= min_percentage]


# =========================================
# FEATURE 3 - Graph Visualization Data
# =========================================

def build_skill_subgraph(job_title, selected_skills, G, max_related=5):
    elements = {"nodes": [], "edges": []}
    seen_ids = set()

    def add_node(node_id, label, ntype):
        if node_id in seen_ids:
            return
        seen_ids.add(node_id)
        elements["nodes"].append({
            "data": {"id": node_id, "label": label, "type": ntype},
            "classes": ntype,
        })

    def add_edge(source, target, label=""):
        elements["edges"].append({
            "data": {"source": source, "target": target, "label": label},
        })

    job_node_id = f"vacancy_{re.sub(r'[^a-z0-9]', '_', normalize(job_title))}"
    add_node(job_node_id, job_title, "job")

    for skill in selected_skills:
        skill_id = normalize(skill).replace(" ", "_")
        add_node(skill_id, skill, "skill")
        add_edge(job_node_id, skill_id, "REQUIRES_SKILL")

        related_jobs = _find_jobs_by_skill(skill, G, max_related)
        for rj_id, rj_title in related_jobs:
            add_node(rj_id, rj_title, "related_job")
            add_edge(skill_id, rj_id, "APPEARS_IN")

    return elements


def _find_jobs_by_skill(skill_name, G, max_results=5):
    skill_norm = normalize(skill_name)
    skill_node = None
    for n, d in G.nodes(data=True):
        if d.get("type") == "skill":
            if normalize(d.get("label", n)) == skill_norm:
                skill_node = n
                break

    if skill_node is None:
        return []

    results = []
    for pred in G.predecessors(skill_node):
        pd = G.nodes.get(pred, {})
        if pd.get("type") == "job":
            title = pd.get("job_title", pred)
            results.append((pred, title))
            if len(results) >= max_results:
                break
    return results


# =========================================
# FEATURE 4 - Job Skill Validation
# =========================================

def validate_job_skills(job_title, selected_skills, G, top_n=15):
    analysis = analyze_job_title(job_title, G, top_n=top_n)
    all_skills = set(s["skill"].lower() for s in analysis["recommended_skills"])

    # Also collect ALL skills from similar jobs (unfiltered)
    similar = find_similar_mixed(job_title, G, top_n=top_n)
    for job in similar:
        for s in job.get("skills", []):
            if s and s.strip():
                all_skills.add(s.strip().lower())

    # Ontology fallback: include O*NET/ESCO skills for validation
    from src.ontology_service import get_ontology
    ontology = get_ontology()
    onto_skills = ontology.get_skills_for_job(job_title)
    for s in onto_skills:
        all_skills.add(s.replace("_", " ").lower())

    selected_lower = set(s.lower() for s in selected_skills)
    if not selected_lower:
        return {
            "score": 0,
            "status": "no_skills",
            "message": "No skills selected.",
            "matching": [],
            "missing": [],
            "recommended": [s["skill"] for s in analysis["recommended_skills"][:5]],
        }

    matching = selected_lower & all_skills
    missing = selected_lower - all_skills

    total_possible = len(selected_lower)
    score = round(len(matching) / total_possible * 100) if total_possible > 0 else 0

    if score >= 70:
        status = "highly_relevant"
        message = "Sangat Sesuai"
    elif score >= 40:
        status = "moderately_relevant"
        message = "Cukup Sesuai"
    else:
        status = "low_relevance"
        message = "Kurang Sesuai — beberapa skill belum umum di posisi ini"

    return {
        "score": score,
        "status": status,
        "message": message,
        "matching": sorted(list(matching)),
        "missing": sorted(list(missing)),
        "recommended": [s["skill"] for s in analysis["recommended_skills"][:5]],
    }


# =========================================
# FEATURE 5 - Talent Availability
# =========================================

def estimate_talent_availability(selected_skills, G):
    if not selected_skills:
        return {
            "total_estimated": 0,
            "skills_analysis": [],
            "high_demand": [],
            "rare_skills": [],
        }

    total_jobs = 0
    skills_analysis = []
    skill_job_counts = {}

    for skill in selected_skills:
        skill_norm = normalize(skill)
        skill_node = None
        for n, d in G.nodes(data=True):
            if d.get("type") == "skill":
                if normalize(d.get("label", n)) == skill_norm:
                    skill_node = n
                    break

        if skill_node is not None:
            job_count = sum(1 for pred in G.predecessors(skill_node)
                           if G.nodes.get(pred, {}).get("type") == "job")
        else:
            job_count = 0

        skill_job_counts[skill] = job_count
        skills_analysis.append({
            "skill": skill,
            "job_count": job_count,
        })

    if skill_job_counts:
        avg = sum(skill_job_counts.values()) / len(skill_job_counts)
        high_demand = [s for s, c in skill_job_counts.items() if c > avg * 1.5]
        rare_skills = [s for s, c in skill_job_counts.items() if c < avg * 0.5]

    return {
        "total_estimated": max(1, int(np.mean(list(skill_job_counts.values()) or [1])) * len(selected_skills)),
        "skills_analysis": sorted(skills_analysis, key=lambda x: x["job_count"], reverse=True),
        "high_demand": high_demand,
        "rare_skills": rare_skills,
    }


# =========================================
# FEATURE 5 - Add Vacancy to Knowledge Graph
# =========================================

def add_vacancy_to_graph(vacancy: dict):
    G = _load_user_graph()
    vid = f"vacancy_{vacancy['id']}"
    job_title = vacancy.get("job_title", "Unknown")
    company_name = vacancy.get("company", "")
    skills = vacancy.get("skills", [])

    G.add_node(vid, type="vacancy", label=job_title, company=company_name,
               location=vacancy.get("location", ""),
               job_level=vacancy.get("job_level", ""),
               job_type=vacancy.get("job_type", ""))

    # Connect vacancy to company node (if exists in graph)
    for n, d in G.nodes(data=True):
        if d.get("type") == "company" and d.get("label", "").lower() == company_name.lower():
            G.add_edge(n, vid, relation="OPENS")
            break

    for skill in skills:
        skill = skill.strip().lower()
        if not skill:
            continue
        if not G.has_node(skill):
            G.add_node(skill, type="skill", label=skill)
        G.add_edge(vid, skill, relation="REQUIRES_SKILL")

    _save_user_graph(G)
    return vid


def _load_user_graph():
    if USER_GRAPH_PATH.exists():
        try:
            G = nx.read_graphml(str(USER_GRAPH_PATH))
        except Exception:
            G = nx.DiGraph()
    else:
        G = nx.DiGraph()
    return G


def _save_user_graph(G):
    for n, d in G.nodes(data=True):
        for k, v in list(d.items()):
            if isinstance(v, (set, list)):
                d[k] = str(v)
            elif v is None:
                d[k] = ""
    nx.write_graphml(G, str(USER_GRAPH_PATH))


# =========================================
# FEATURE 6 - Add Company Node to Knowledge Graph
# =========================================

def add_company_node(company: dict):
    G = _load_user_graph()
    cid = f"company_{company['id']}"
    G.add_node(cid, type="company", label=company.get("name", "Unknown"),
               industry=company.get("industry", ""),
               location=company.get("location", ""),
               website=company.get("website", ""))
    _save_user_graph(G)
    return cid
