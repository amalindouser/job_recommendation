import json
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
JSONL_PATH = DATA_DIR / "all_jobs_clean.jsonl"
DB_PATH = DATA_DIR / "all_jobs_clean.db"


def to_num(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    c = conn.cursor()

    c.execute("DROP TABLE IF EXISTS clean_jobs")
    c.execute("""
        CREATE TABLE clean_jobs (
            id INTEGER PRIMARY KEY,
            csv_id TEXT,
            job_title TEXT,
            company TEXT,
            location TEXT,
            employment TEXT,
            salary_min REAL,
            salary_max REAL,
            salary_currency TEXT,
            salary_period TEXT,
            posted_at TEXT,
            job_url TEXT,
            categories TEXT,
            skills TEXT,
            categorized_skills TEXT,
            description TEXT
        )
    """)
    c.execute("CREATE INDEX idx_job_title ON clean_jobs(job_title)")
    c.execute("CREATE INDEX idx_company ON clean_jobs(company)")

    total = 0
    batch = []

    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            j = json.loads(line)
            total += 1
            desc = (j.get("description") or j.get("description_raw") or "").strip()
            batch.append((
                total - 1,
                j.get("csv_id"),
                j.get("job_title"),
                j.get("company"),
                j.get("location"),
                j.get("employment"),
                to_num(j.get("salary_min")),
                to_num(j.get("salary_max")),
                j.get("salary_currency"),
                j.get("salary_period"),
                j.get("posted_at"),
                j.get("job_url"),
                json.dumps(j.get("categories") or [], ensure_ascii=False),
                json.dumps(j.get("skills") or [], ensure_ascii=False),
                json.dumps(j.get("categorized_skills") or {}, ensure_ascii=False),
                desc,
            ))
            if len(batch) >= 5000:
                c.executemany(
                    "INSERT INTO clean_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    batch,
                )
                batch = []
                print(f"  {total} rows...", end="\r")

    if batch:
        c.executemany(
            "INSERT INTO clean_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            batch,
        )

    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    db_size = DB_PATH.stat().st_size
    print(f"\n[OK] {total} rows written to {DB_PATH.name} ({db_size/1024/1024:.1f} MB)")


if __name__ == "__main__":
    main()
