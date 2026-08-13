import os
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv()

import psycopg2
import psycopg2.extras
import networkx as nx


DB_URL = os.getenv("DB_URL")
DATA_DIR = Path(__file__).parent.parent / "data"
GRAPH_PATH = DATA_DIR / "graph_jobs_clean.graphml"


SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION viki;

CREATE TABLE IF NOT EXISTS app.jobs (
    id SERIAL PRIMARY KEY,
    job_id TEXT,
    job_title TEXT NOT NULL,
    company TEXT,
    job_location TEXT,
    search_city TEXT,
    search_country TEXT,
    job_level TEXT,
    job_type TEXT,
    job_link TEXT,
    first_seen TEXT,
    skills_raw TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app.job_skills (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES app.jobs(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    UNIQUE(job_id, skill)
);

CREATE INDEX IF NOT EXISTS idx_jobs_title ON app.jobs(job_title);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON app.jobs(company);
CREATE INDEX IF NOT EXISTS idx_job_skills_skill ON app.job_skills(skill);
"""


def ensure_tables(conn):
    c = conn.cursor()
    c.execute(SCHEMA_SQL)
    conn.commit()
    c.close()
    print("[OK] Tables ensured: jobs, job_skills")


def get_existing_job_titles(conn):
    c = conn.cursor()
    c.execute("SELECT job_title, company FROM app.jobs")
    existing = set()
    for row in c.fetchall():
        existing.add((row[0], row[1] or ""))
    c.close()
    return existing


def import_from_graph(conn, force=False):
    print(f"[*] Loading graph from {GRAPH_PATH}...")
    G = nx.read_graphml(str(GRAPH_PATH))

    job_nodes = [(n, d) for n, d in G.nodes(data=True) if d.get("type") == "job"]
    print(f"[OK] Found {len(job_nodes)} job nodes in graph")

    if not force:
        existing = get_existing_job_titles(conn)
        print(f"[OK] {len(existing)} existing jobs in DB")
    else:
        existing = set()
        c = conn.cursor()
        c.execute("DELETE FROM app.job_skills")
        c.execute("DELETE FROM app.jobs")
        conn.commit()
        c.close()
        print("[OK] Truncated existing data (force=True)")

    new_count = 0
    skill_count = 0

    for node_id, data in job_nodes:
        job_title = data.get("job_title", "")
        company = data.get("company", "") or ""

        key = (job_title, company)
        if key in existing:
            continue

        skills_raw = data.get("skills_raw", "") or ""
        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]

        c = conn.cursor()
        c.execute("""
            INSERT INTO app.jobs (job_id, job_title, company, job_location, search_city, search_country,
                              job_level, job_type, job_link, first_seen, skills_raw)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
        """, (
            data.get("job_id", ""),
            job_title,
            company,
            data.get("job_location", ""),
            data.get("search_city", ""),
            data.get("search_country", ""),
            data.get("job_level", ""),
            data.get("job_type", ""),
            data.get("job_link", ""),
            data.get("first_seen", ""),
            skills_raw,
        ))
        row = c.fetchone()
        if row:
            job_db_id = row[0]
            for skill in skills:
                try:
                    c.execute(
                        "INSERT INTO app.job_skills (job_id, skill) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (job_db_id, skill.lower())
                    )
                    skill_count += 1
                except Exception:
                    pass
            new_count += 1
        conn.commit()
        c.close()

    print(f"[OK] Imported {new_count} new jobs, {skill_count} skill relations")
    return new_count


def run_import(force=False):
    if not DB_URL:
        print("[!] No DB_URL configured. Skipping import.")
        return

    try:
        conn = psycopg2.connect(DB_URL)
        ensure_tables(conn)
        count = import_from_graph(conn, force=force)
        conn.close()
        print(f"[OK] Import complete. Total new jobs: {count}")
        return count
    except Exception as e:
        print(f"[!] Import error: {e}")
        import traceback
        traceback.print_exc()
        return 0


if __name__ == "__main__":
    force = "--force" in sys.argv
    run_import(force=force)
