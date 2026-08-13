"""Migrate existing JSON data to PostgreSQL tables."""
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db_service import (
    get_connection, save_job_db, append_reco_log_db, append_feedback_log_db,
    init_all_tables,
)

BASE = Path(__file__).parent.parent


def migrate_saved_jobs():
    path = BASE / "database" / "saved_jobs.json"
    if not path.exists():
        print("[SKIP] saved_jobs.json not found")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"anonymous": data}
    total = 0
    for username, jobs in data.items():
        if not isinstance(jobs, list):
            continue
        for job in jobs:
            if isinstance(job, dict):
                ok = save_job_db(username, job)
                if ok:
                    total += 1
    print(f"[OK] Migrated {total} saved jobs")


def migrate_reco_logs():
    path = BASE / "database" / "recommendation_logs.json"
    if not path.exists():
        print("[SKIP] recommendation_logs.json not found")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"anonymous": data}
    total = 0
    for username, logs in data.items():
        if not isinstance(logs, list):
            continue
        for entry in logs:
            if isinstance(entry, dict):
                ok = append_reco_log_db(username, entry)
                if ok:
                    total += 1
    print(f"[OK] Migrated {total} recommendation logs")


def migrate_feedback_logs():
    path = BASE / "database" / "feedback_logs.json"
    if not path.exists():
        print("[SKIP] feedback_logs.json not found")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("[SKIP] invalid format")
        return
    total = 0
    for entry in data:
        if isinstance(entry, dict):
            ok = append_feedback_log_db(entry)
            if ok:
                total += 1
    print(f"[OK] Migrated {total} feedback logs")


def main():
    print("=== Migrating JSON data to PostgreSQL ===\n")
    init_all_tables()
    migrate_saved_jobs()
    migrate_reco_logs()
    migrate_feedback_logs()
    print("\n[DONE] Migration complete")


if __name__ == "__main__":
    main()
