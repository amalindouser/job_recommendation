import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import networkx as nx

from src.graph_enricher import load_enriched_graph
from src.employer_graph_service import add_vacancy_to_graph
from src.db_service import (
    get_connection,
    create_vacancy_db,
    get_vacancy_db,
    list_vacancies_db,
    update_vacancy_db,
    delete_vacancy_db,
)

VACANCIES_PATH = Path(__file__).parent.parent / "data" / "vacancies.json"


def _ensure_vacancies():
    if not VACANCIES_PATH.exists():
        VACANCIES_PATH.write_text(json.dumps([], indent=2), encoding="utf-8")


def _read_vacancies():
    _ensure_vacancies()
    try:
        return json.loads(VACANCIES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_vacancies(vacancies):
    VACANCIES_PATH.write_text(json.dumps(vacancies, indent=2, ensure_ascii=False), encoding="utf-8")


def create_vacancy(data: dict, user_id: int = None) -> dict:
    db_vacancy = create_vacancy_db(data, user_id or 1)
    if db_vacancy:
        try:
            add_vacancy_to_graph(db_vacancy)
        except Exception as e:
            print(f"[!] Failed to add vacancy to graph: {e}")
        return db_vacancy
    # Fallback to JSON
    vacancies = _read_vacancies()
    vacancy = {
        "id": str(uuid.uuid4())[:8],
        "job_title": data.get("job_title", "").strip(),
        "company": data.get("company", "").strip(),
        "description": data.get("description", "").strip(),
        "skills": [s.strip() for s in data.get("skills", "").split(",") if s.strip()],
        "salary_min": data.get("salary_min", "").strip(),
        "salary_max": data.get("salary_max", "").strip(),
        "job_level": data.get("job_level", "").strip(),
        "job_type": data.get("job_type", "").strip(),
        "location": data.get("location", "").strip(),
        "created_at": datetime.now().isoformat(),
    }
    vacancies.append(vacancy)
    _write_vacancies(vacancies)
    try:
        add_vacancy_to_graph(vacancy)
    except Exception as e:
        print(f"[!] Failed to add vacancy to graph: {e}")
    return vacancy


def list_vacancies(search: str = None, company: str = None, salary_min=None, salary_max=None):
    vacancies = _read_vacancies()
    if search:
        search = search.lower()
        vacancies = [v for v in vacancies if search in v.get("job_title", "").lower()
                     or search in v.get("company", "").lower()
                     or search in " ".join(v.get("skills", [])).lower()]
    if company:
        vacancies = [v for v in vacancies if v.get("company", "").lower() == company.lower()]

    # Include employer vacancies from PostgreSQL app.vacancies
    try:
        from src.db_service import list_employer_vacancies_db
        db_vacs = list_employer_vacancies_db(search=search or "", company=company or "", limit=200)
        existing_ids = {v["id"] for v in vacancies}
        for v in db_vacs:
            if v["id"] not in existing_ids:
                vacancies.append(v)
    except Exception as e:
        print(f"[!] Failed to load employer vacancies from DB: {e}")

    try:
        conn = get_connection()
        if conn:
            c = conn.cursor()
            query = """
                SELECT id, job_title, company, job_location, search_city, search_country,
                       job_level, job_type, skills_raw, first_seen
                FROM app.jobs
            """
            params = []
            conditions = []
            if search:
                conditions.append("(LOWER(job_title) LIKE %s OR LOWER(company) LIKE %s OR LOWER(skills_raw) LIKE %s)")
                params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
            if company:
                conditions.append("LOWER(company) LIKE %s")
                params.append(f"%{company.lower()}%")
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY first_seen DESC NULLS LAST LIMIT 500"

            c.execute(query, params)
            for row in c.fetchall():
                skills = [s.strip().lower() for s in (row[8] or "").split(",") if s.strip()]
                vacancies.append({
                    "id": f"hist_{row[0]}",
                    "job_title": row[1],
                    "company": row[2] or "",
                    "skills": skills,
                    "job_level": row[6] or "",
                    "job_type": row[7] or "",
                    "location": f"{row[4]}, {row[5]}" if row[4] and row[5] else (row[3] or ""),
                    "created_at": row[9] or "",
                    "historical": True,
                })
            c.close()
            conn.close()
    except Exception as e:
        print(f"[!] Failed to load historical jobs: {e}")

    if salary_min:
        try:
            smin = int(salary_min)
            vacancies = [v for v in vacancies if
                         (v.get("salary_min") and v["salary_min"].isdigit() and int(v["salary_min"]) >= smin) or
                         (v.get("salary_max") and v["salary_max"].isdigit() and int(v["salary_max"]) >= smin)]
        except ValueError:
            pass
    if salary_max:
        try:
            smax = int(salary_max)
            vacancies = [v for v in vacancies if
                         (v.get("salary_max") and v["salary_max"].isdigit() and int(v["salary_max"]) <= smax) or
                         (v.get("salary_min") and v["salary_min"].isdigit() and int(v["salary_min"]) <= smax)]
        except ValueError:
            pass

    return vacancies


def get_vacancy(vacancy_id: str):
    # Try DB first
    db_vacancy = get_vacancy_db(vacancy_id)
    if db_vacancy:
        return db_vacancy

    # Fallback to JSON
    vacancies = _read_vacancies()
    for v in vacancies:
        if v["id"] == vacancy_id:
            return v

    if vacancy_id.startswith("hist_"):
        try:
            db_id = int(vacancy_id[5:])
            conn = get_connection()
            if conn:
                c = conn.cursor()
                c.execute("""
                    SELECT id, job_title, company, job_location, search_city, search_country,
                           job_level, job_type, skills_raw, first_seen
                    FROM app.jobs WHERE id = %s
                """, (db_id,))
                row = c.fetchone()
                c.close()
                conn.close()
                if row:
                    skills = [s.strip().lower() for s in (row[8] or "").split(",") if s.strip()]
                    return {
                        "id": f"hist_{row[0]}",
                        "job_title": row[1],
                        "company": row[2] or "",
                        "skills": skills,
                        "job_level": row[6] or "",
                        "job_type": row[7] or "",
                        "location": f"{row[4]}, {row[5]}" if row[4] and row[5] else (row[3] or ""),
                        "created_at": row[9] or "",
                        "historical": True,
                    }
        except (ValueError, Exception) as e:
            print(f"[!] Failed to fetch historical job {vacancy_id}: {e}")

    return None


def _node_id(value: str, prefix: str) -> str:
    if not isinstance(value, str):
        value = ""
    value = value.strip().lower()
    for ch in [" ", ",", ".", "/", "\\", "(", ")", "'", '"']:
        value = value.replace(ch, "_")
    value = re.sub(r"_+", "_", value).strip("_")
    return f"{prefix}_{value}" if value else f"{prefix}_unknown"


def get_vacancy_graph(vacancy_id: str, G: nx.Graph = None):
    vacancy = get_vacancy(vacancy_id)
    if not vacancy:
        return None

    if G is None:
        G = load_enriched_graph()

    elements = {"nodes": [], "edges": []}
    seen_ids = set()

    def add_node(node_id, label, ntype, graph_data=None):
        if node_id in seen_ids:
            return
        seen_ids.add(node_id)
        if graph_data:
            label = graph_data.get("label", label)
        elements["nodes"].append({
            "data": {"id": node_id, "label": label, "type": ntype},
            "classes": ntype
        })

    vacancy_node_id = f"vacancy_{vacancy_id}"
    add_node(vacancy_node_id, vacancy["job_title"], "job")

    # Company
    company_id = _node_id(vacancy.get("company", ""), "company")
    if company_id in G:
        add_node(company_id, vacancy["company"], "company", G.nodes[company_id])
    else:
        add_node(company_id, vacancy.get("company", "Unknown"), "company")
    elements["edges"].append({
        "data": {"source": company_id, "target": vacancy_node_id, "label": "OPENS"}
    })

    # Level
    level_id = _node_id(vacancy.get("job_level", ""), "level")
    if level_id in G:
        add_node(level_id, vacancy["job_level"], "level", G.nodes[level_id])
    else:
        add_node(level_id, vacancy.get("job_level", "Unknown"), "level")
    elements["edges"].append({
        "data": {"source": vacancy_node_id, "target": level_id, "label": "HAS_LEVEL"}
    })

    # Job Type
    type_id = _node_id(vacancy.get("job_type", ""), "jobtype")
    if type_id in G:
        add_node(type_id, vacancy["job_type"], "jobtype", G.nodes[type_id])
    else:
        add_node(type_id, vacancy.get("job_type", "Unknown"), "jobtype")
    elements["edges"].append({
        "data": {"source": vacancy_node_id, "target": type_id, "label": "HAS_TYPE"}
    })

    # Location
    loc_id = _node_id(vacancy.get("location", ""), "location")
    if loc_id in G:
        add_node(loc_id, vacancy["location"], "location", G.nodes[loc_id])
    else:
        add_node(loc_id, vacancy.get("location", "Unknown"), "location")
    elements["edges"].append({
        "data": {"source": vacancy_node_id, "target": loc_id, "label": "LOCATED_IN"}
    })

    # Skills
    for skill in vacancy.get("skills", []):
        skill_id = f"skill_{skill.strip().lower().replace(' ', '_')}"
        add_node(skill_id, skill, "skill")
        elements["edges"].append({
            "data": {"source": vacancy_node_id, "target": skill_id, "label": "REQUIRES_SKILL"}
        })

    return elements


def get_graph_metrics(vacancy_id: str, G: nx.Graph = None):
    vacancy = get_vacancy(vacancy_id)
    if not vacancy:
        return None

    if G is None:
        G = load_enriched_graph()

    metrics = {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "company_nodes": len([n for n, d in G.nodes(data=True) if d.get("type") == "company"]),
        "skill_nodes": len([n for n, d in G.nodes(data=True) if d.get("type") == "skill"]),
        "job_nodes": len([n for n, d in G.nodes(data=True) if d.get("type") == "job"]),
        "location_nodes": len([n for n, d in G.nodes(data=True) if d.get("type") == "location"]),
        "level_nodes": len([n for n, d in G.nodes(data=True) if d.get("type") == "level"]),
        "type_nodes": len([n for n, d in G.nodes(data=True) if d.get("type") == "jobtype"]),
    }

    node_id = vacancy.get("job_title", "").lower().replace(" ", "_")
    if node_id in G:
        metrics["degree"] = G.degree(node_id)
        try:
            metrics["pagerank"] = round(nx.pagerank(G, alpha=0.85).get(node_id, 0), 6)
        except Exception:
            metrics["pagerank"] = 0
    else:
        metrics["degree"] = 0
        metrics["pagerank"] = 0

    return metrics


def get_analytics_skills(G: nx.Graph = None, top_n: int = 20):
    if G is None:
        G = load_enriched_graph()

    skill_counts = {}
    for _, _, data in G.edges(data=True):
        pass

    for node_id, data in G.nodes(data=True):
        if data.get("type") == "skill":
            label = data.get("label", node_id)
            degree = G.degree(node_id)
            skill_counts[label] = degree

    sorted_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"skill": s, "frequency": c} for s, c in sorted_skills]


def get_analytics_companies(G: nx.Graph = None, top_n: int = 20):
    if G is None:
        G = load_enriched_graph()

    company_jobs = {}
    for node_id, data in G.nodes(data=True):
        if data.get("type") == "company":
            label = data.get("label", node_id)
            degree = G.degree(node_id)
            company_jobs[label] = degree

    sorted_companies = sorted(company_jobs.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"company": c, "job_count": cnt} for c, cnt in sorted_companies]


def get_analytics_locations(G: nx.Graph = None, top_n: int = 20):
    if G is None:
        G = load_enriched_graph()

    location_jobs = {}
    for node_id, data in G.nodes(data=True):
        if data.get("type") == "location":
            label = data.get("label", node_id)
            degree = G.degree(node_id)
            location_jobs[label] = degree

    sorted_locs = sorted(location_jobs.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"location": loc, "job_count": cnt} for loc, cnt in sorted_locs]


def get_analytics_levels(G: nx.Graph = None):
    if G is None:
        G = load_enriched_graph()

    level_counts = {}
    for node_id, data in G.nodes(data=True):
        if data.get("type") == "level":
            label = data.get("label", node_id)
            level_counts[label] = G.degree(node_id)

    return [{"level": l, "count": c} for l, c in sorted(level_counts.items(), key=lambda x: x[1], reverse=True)]


def update_vacancy(vacancy_id: str, data: dict):
    updated = update_vacancy_db(vacancy_id, data)
    if updated:
        return updated
    # Fallback to JSON
    vacancies = _read_vacancies()
    for i, v in enumerate(vacancies):
        if v["id"] == vacancy_id:
            v["job_title"] = data.get("job_title", v["job_title"]).strip()
            v["company"] = data.get("company", v["company"]).strip()
            v["description"] = data.get("description", v.get("description", "")).strip()
            v["skills"] = [s.strip() for s in data.get("skills", ",".join(v.get("skills", []))).split(",") if s.strip()]
            v["salary_min"] = data.get("salary_min", v.get("salary_min", "")).strip()
            v["salary_max"] = data.get("salary_max", v.get("salary_max", "")).strip()
            v["job_level"] = data.get("job_level", v.get("job_level", "")).strip()
            v["job_type"] = data.get("job_type", v.get("job_type", "")).strip()
            v["location"] = data.get("location", v.get("location", "")).strip()
            vacancies[i] = v
            _write_vacancies(vacancies)
            return v
    return None


def delete_vacancy(vacancy_id: str) -> bool:
    removed = False
    # Remove from DB
    if delete_vacancy_db(vacancy_id):
        removed = True
    # Remove from JSON too (vacancy may exist in both)
    vacancies = _read_vacancies()
    filtered = [v for v in vacancies if v["id"] != vacancy_id]
    if len(filtered) < len(vacancies):
        _write_vacancies(filtered)
        removed = True
    return removed
