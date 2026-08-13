import json
from pathlib import Path
from src.db_service import (
    get_connection, init_vacancies_table, init_applications_table,
    create_vacancy_db, apply_to_vacancy_db,
)

DATA_DIR = Path(__file__).parent.parent / "data"


def run():
    conn = get_connection()
    if not conn:
        print("[!] No database connection. Aborting.")
        return

    print("[*] Creating tables...")
    init_vacancies_table()
    init_applications_table()

    # Import vacancies
    v_path = DATA_DIR / "vacancies.json"
    if v_path.exists():
        try:
            existing = json.loads(v_path.read_text(encoding="utf-8"))
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM app.vacancies")
            count = c.fetchone()[0]
            c.close()
            if count == 0 and existing:
                # Need user_id - use first employer user
                c = conn.cursor()
                c.execute("SELECT id FROM users WHERE role = 'employer' LIMIT 1")
                emp = c.fetchone()
                c.close()
                user_id = emp[0] if emp else 1
                imported = 0
                for v in existing:
                    try:
                        c = conn.cursor()
                        c.execute("""
                            INSERT INTO app.vacancies (id, user_id, job_title, company, description, skills,
                                                       salary_min, salary_max, job_level, job_type, location, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO NOTHING
                        """, (
                            v["id"], user_id, v.get("job_title", ""), v.get("company", ""),
                            v.get("description", ""),
                            [s.strip() for s in v.get("skills", []) if s.strip()],
                            v.get("salary_min", ""), v.get("salary_max", ""),
                            v.get("job_level", ""), v.get("job_type", ""),
                            v.get("location", ""),
                            v.get("created_at", None),
                        ))
                        conn.commit()
                        c.close()
                        imported += 1
                    except Exception as e:
                        conn.rollback()
                        print(f"  [!] Skip vacancy {v.get('id')}: {e}")
                print(f"[OK] Imported {imported}/{len(existing)} vacancies")
            else:
                print(f"[OK] vacancies table already has {count} rows")
        except Exception as e:
            print(f"[!] Error importing vacancies: {e}")
    else:
        print("[!] vacancies.json not found")

    # Import applications
    a_path = DATA_DIR / "applications.json"
    if a_path.exists():
        try:
            existing = json.loads(a_path.read_text(encoding="utf-8"))
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM app.applications")
            count = c.fetchone()[0]
            c.close()
            if count == 0 and existing:
                imported = 0
                for a in existing:
                    try:
                        c = conn.cursor()
                        c.execute("""
                            INSERT INTO app.applications (id, vacancy_id, user_id, username, cv_filename,
                                                          cover_letter, status, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO NOTHING
                        """, (
                            a["id"], a["vacancy_id"], int(a["user_id"]), a.get("username", ""),
                            a.get("cv_filename", ""), a.get("cover_letter", ""),
                            a.get("status", "pending"), a.get("created_at", None),
                        ))
                        conn.commit()
                        c.close()
                        imported += 1
                    except Exception as e:
                        conn.rollback()
                        print(f"  [!] Skip application {a.get('id')}: {e}")
                print(f"[OK] Imported {imported}/{len(existing)} applications")
            else:
                print(f"[OK] applications table already has {count} rows")
        except Exception as e:
            print(f"[!] Error importing applications: {e}")
    else:
        print("[!] applications.json not found")

    conn.close()
    print("[*] Migration complete.")


if __name__ == "__main__":
    run()
