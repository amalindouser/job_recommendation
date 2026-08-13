import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DB_URL")


def get_connection():
    import psycopg2
    try:
        return psycopg2.connect(DB_URL)
    except Exception as e:
        print(f"[!] DB connection error: {e}")
        return None


def search_job_titles(query, limit=20):
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        c.execute("""
            SELECT DISTINCT job_title, company, search_city, search_country
            FROM app.jobs
            WHERE job_title ILIKE %s
            ORDER BY job_title
            LIMIT %s
        """, (f"%{query}%", limit))
        rows = c.fetchall()
        c.close()
        conn.close()
        return [
            {"job_title": r[0], "company": r[1], "location": f"{r[2]}, {r[3]}" if r[2] and r[3] else ""}
            for r in rows
        ]
    except Exception as e:
        print(f"[!] search_job_titles error: {e}")
        return []


def get_all_job_titles(limit=5000):
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        c.execute("""
            SELECT DISTINCT job_title FROM app.jobs ORDER BY job_title LIMIT %s
        """, (limit,))
        rows = c.fetchall()
        c.close()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        print(f"[!] get_all_job_titles error: {e}")
        return []


def get_skills_for_job_title(title, limit=50):
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        c.execute("""
            SELECT DISTINCT js.skill, COUNT(*) OVER (PARTITION BY js.skill) as freq
            FROM app.job_skills js
            JOIN app.jobs j ON j.id = js.job_id
            WHERE j.job_title ILIKE %s
            ORDER BY freq DESC
            LIMIT %s
        """, (f"%{title}%", limit))
        rows = c.fetchall()
        c.close()
        conn.close()
        return [{"skill": r[0], "frequency": r[1]} for r in rows]
    except Exception as e:
        print(f"[!] get_skills_for_job_title error: {e}")
        return []


def init_companies_table():
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS app.companies (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE NOT NULL,
                name TEXT NOT NULL,
                industry TEXT DEFAULT '',
                description TEXT DEFAULT '',
                location TEXT DEFAULT '',
                website TEXT DEFAULT '',
                size TEXT DEFAULT '',
                logo_url TEXT DEFAULT '',
                hr_name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] init_companies_table error: {e}")
        return False


def get_company_by_user_id(user_id):
    conn = get_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM app.companies WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        if row:
            return {
                "id": row[0], "user_id": row[1], "name": row[2],
                "industry": row[3] or "", "description": row[4] or "",
                "location": row[5] or "", "website": row[6] or "",
                "size": row[7] or "", "logo_url": row[8] or "",
                "hr_name": row[9] or "", "phone": row[10] or "",
                "created_at": str(row[11]) if row[11] else "",
            }
        return None
    except Exception as e:
        print(f"[!] get_company_by_user_id error: {e}")
        return None


def create_company(user_id, name, industry="", description="", location="",
                   website="", size="", logo_url="", hr_name="", phone=""):
    conn = get_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO app.companies (user_id, name, industry, description, location,
                                       website, size, logo_url, hr_name, phone)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                name=EXCLUDED.name, industry=EXCLUDED.industry,
                description=EXCLUDED.description, location=EXCLUDED.location,
                website=EXCLUDED.website, size=EXCLUDED.size,
                logo_url=EXCLUDED.logo_url, hr_name=EXCLUDED.hr_name,
                phone=EXCLUDED.phone
            RETURNING id
        """, (user_id, name, industry, description, location,
              website, size, logo_url, hr_name, phone))
        company_id = c.fetchone()[0]
        conn.commit()
        c.close()
        conn.close()
        return company_id
    except Exception as e:
        print(f"[!] create_company error: {e}")
        return None


def init_profiles_table():
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS app.job_seeker_profiles (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE NOT NULL,
                full_name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                skills TEXT[] DEFAULT '{}',
                experience_years INTEGER DEFAULT 0,
                education TEXT DEFAULT '',
                expected_salary_min NUMERIC DEFAULT 0,
                location TEXT DEFAULT '',
                portfolio_url TEXT DEFAULT '',
                headline TEXT DEFAULT '',
                about TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] init_profiles_table error: {e}")
        return False


def get_profile_by_user_id(user_id):
    conn = get_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM app.job_seeker_profiles WHERE user_id = %s", (user_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        if row:
            skills = row[4] if row[4] else []
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.strip("{}").split(",") if s.strip()]
            return {
                "id": row[0], "user_id": row[1],
                "full_name": row[2] or "", "phone": row[3] or "",
                "skills": skills,
                "experience_years": row[5] or 0,
                "education": row[6] or "",
                "expected_salary_min": float(row[7]) if row[7] else 0,
                "location": row[8] or "",
                "portfolio_url": row[9] or "",
                "headline": row[10] or "",
                "about": row[11] or "",
                "updated_at": str(row[12]) if row[12] else "",
            }
        return None
    except Exception as e:
        print(f"[!] get_profile_by_user_id error: {e}")
        return None


def upsert_profile(user_id, full_name="", phone="", skills=None,
                   experience_years=0, education="", expected_salary_min=0,
                   location="", portfolio_url="", headline="", about=""):
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO app.job_seeker_profiles
                (user_id, full_name, phone, skills, experience_years, education,
                 expected_salary_min, location, portfolio_url, headline, about)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                full_name=EXCLUDED.full_name, phone=EXCLUDED.phone,
                skills=EXCLUDED.skills, experience_years=EXCLUDED.experience_years,
                education=EXCLUDED.education, expected_salary_min=EXCLUDED.expected_salary_min,
                location=EXCLUDED.location, portfolio_url=EXCLUDED.portfolio_url,
                headline=EXCLUDED.headline, about=EXCLUDED.about,
                updated_at=CURRENT_TIMESTAMP
        """, (user_id, full_name, phone, skills or [],
              experience_years, education, expected_salary_min,
              location, portfolio_url, headline, about))
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] upsert_profile error: {e}")
        return False


def get_profiles_by_skills(skill_list, limit=50):
    """Find seekers matching given skills (for employer)."""
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        c.execute("""
            SELECT user_id, full_name, skills, experience_years, education,
                   expected_salary_min, location, headline
            FROM app.job_seeker_profiles
            WHERE skills && %s
            ORDER BY experience_years DESC
            LIMIT %s
        """, (skill_list, limit))
        rows = c.fetchall()
        c.close()
        conn.close()
        return [
            {"user_id": r[0], "full_name": r[1] or "",
             "skills": list(r[2]) if r[2] else [],
             "experience_years": r[3] or 0, "education": r[4] or "",
             "expected_salary_min": float(r[5]) if r[5] else 0,
             "location": r[6] or "", "headline": r[7] or ""}
            for r in rows
        ]
    except Exception as e:
        print(f"[!] get_profiles_by_skills error: {e}")
        return []


def get_similar_jobs_from_db(title, limit=10):
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        c.execute("""
            SELECT job_title, company, search_city, search_country, job_level, job_type,
                   skills_raw
            FROM app.jobs
            WHERE job_title ILIKE %s
            ORDER BY job_title
            LIMIT %s
        """, (f"%{title}%", limit))
        rows = c.fetchall()
        c.close()
        conn.close()
        results = []
        for r in rows:
            skills = [s.strip() for s in (r[6] or "").split(",") if s.strip()]
            results.append({
                "job_title": r[0],
                "company": r[1],
                "location": f"{r[2]}, {r[3]}" if r[2] and r[3] else "",
                "job_level": r[4] or "",
                "job_type": r[5] or "",
                "skills": skills,
            })
        return results
    except Exception as e:
        print(f"[!] get_similar_jobs_from_db error: {e}")
        return []


# === Vacancies (employer-owned) ===

def init_vacancies_table():
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS app.vacancies (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                job_title TEXT NOT NULL,
                company TEXT DEFAULT '',
                description TEXT DEFAULT '',
                skills TEXT[] DEFAULT '{}',
                salary_min TEXT DEFAULT '',
                salary_max TEXT DEFAULT '',
                job_level TEXT DEFAULT '',
                job_type TEXT DEFAULT '',
                location TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] init_vacancies_table error: {e}")
        return False


def create_vacancy_db(data: dict, user_id: int):
    conn = get_connection()
    if not conn:
        return None
    try:
        import uuid
        vid = str(uuid.uuid4())[:8]
        c = conn.cursor()
        c.execute("""
            INSERT INTO app.vacancies (id, user_id, job_title, company, description, skills,
                                       salary_min, salary_max, job_level, job_type, location)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
        """, (vid, user_id, data.get("job_title", "").strip(),
              data.get("company", "").strip(),
              data.get("description", "").strip(),
              [s.strip() for s in data.get("skills", "").split(",") if s.strip()],
              data.get("salary_min", "").strip(),
              data.get("salary_max", "").strip(),
              data.get("job_level", "").strip(),
              data.get("job_type", "").strip(),
              data.get("location", "").strip()))
        row = c.fetchone()
        conn.commit()
        c.close()
        conn.close()
        if row:
            return {**data, "id": row[0], "created_at": str(row[1])}
        return None
    except Exception as e:
        print(f"[!] create_vacancy_db error: {e}")
        return None


def get_vacancy_db(vacancy_id: str):
    conn = get_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM app.vacancies WHERE id = %s", (vacancy_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        if row:
            skills = row[5] if row[5] else []
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.strip("{}").split(",") if s.strip()]
            return {
                "id": row[0], "user_id": row[1], "job_title": row[2],
                "company": row[3] or "", "description": row[4] or "",
                "skills": list(skills) if not isinstance(skills, list) else skills,
                "salary_min": row[6] or "", "salary_max": row[7] or "",
                "job_level": row[8] or "", "job_type": row[9] or "",
                "location": row[10] or "", "created_at": str(row[11]) if row[11] else "",
            }
        return None
    except Exception as e:
        print(f"[!] get_vacancy_db error: {e}")
        return None


def list_vacancies_db(user_id: int, search: str = ""):
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        query = "SELECT * FROM app.vacancies WHERE user_id = %s"
        params = [user_id]
        if search:
            query += " AND (LOWER(job_title) LIKE %s OR LOWER(company) LIKE %s OR LOWER(array_to_string(skills, ',')) LIKE %s)"
            params.extend([f"%{search.lower()}%", f"%{search.lower()}%", f"%{search.lower()}%"])
        query += " ORDER BY created_at DESC"
        c.execute(query, params)
        rows = c.fetchall()
        c.close()
        conn.close()
        results = []
        for row in rows:
            skills = row[5] if row[5] else []
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.strip("{}").split(",") if s.strip()]
            results.append({
                "id": row[0], "user_id": row[1], "job_title": row[2],
                "company": row[3] or "", "description": row[4] or "",
                "skills": list(skills) if not isinstance(skills, list) else skills,
                "salary_min": row[6] or "", "salary_max": row[7] or "",
                "job_level": row[8] or "", "job_type": row[9] or "",
                "location": row[10] or "", "created_at": str(row[11]) if row[11] else "",
            })
        return results
    except Exception as e:
        print(f"[!] list_vacancies_db error: {e}")
        return []


def update_vacancy_db(vacancy_id: str, data: dict):
    conn = get_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE app.vacancies SET
                job_title = %s, company = %s, description = %s,
                skills = %s, salary_min = %s, salary_max = %s,
                job_level = %s, job_type = %s, location = %s
            WHERE id = %s
        """, (
            data.get("job_title", "").strip(),
            data.get("company", "").strip(),
            data.get("description", "").strip(),
            [s.strip() for s in data.get("skills", "").split(",") if s.strip()],
            data.get("salary_min", "").strip(),
            data.get("salary_max", "").strip(),
            data.get("job_level", "").strip(),
            data.get("job_type", "").strip(),
            data.get("location", "").strip(),
            vacancy_id,
        ))
        conn.commit()
        c.close()
        conn.close()
        return get_vacancy_db(vacancy_id)
    except Exception as e:
        print(f"[!] update_vacancy_db error: {e}")
        return None


def delete_vacancy_db(vacancy_id: str):
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("DELETE FROM app.vacancies WHERE id = %s", (vacancy_id,))
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] delete_vacancy_db error: {e}")
        return False


# === Applications ===

def init_applications_table():
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS app.applications (
                id TEXT PRIMARY KEY,
                vacancy_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT DEFAULT '',
                cv_filename TEXT DEFAULT '',
                cover_letter TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] init_applications_table error: {e}")
        return False


def apply_to_vacancy_db(vacancy_id, user_id, username, cv_filename="", cover_letter=""):
    conn = get_connection()
    if not conn:
        return None
    try:
        import uuid
        c = conn.cursor()
        # Cek existing
        c.execute("SELECT id FROM app.applications WHERE vacancy_id = %s AND user_id = %s",
                  (vacancy_id, user_id))
        if c.fetchone():
            c.close()
            conn.close()
            return None, "Anda sudah melamar lowongan ini."
        aid = uuid.uuid4().hex[:12]
        c.execute("""
            INSERT INTO app.applications (id, vacancy_id, user_id, username, cv_filename, cover_letter)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (aid, vacancy_id, user_id, username, cv_filename, cover_letter))
        conn.commit()
        c.close()
        conn.close()
        return {
            "id": aid, "vacancy_id": vacancy_id, "user_id": str(user_id),
            "username": username, "cv_filename": cv_filename,
            "cover_letter": cover_letter, "status": "pending",
        }, None
    except Exception as e:
        print(f"[!] apply_to_vacancy_db error: {e}")
        return None, str(e)


def get_applications_for_vacancy_db(vacancy_id):
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM app.applications WHERE vacancy_id = %s ORDER BY created_at DESC",
                  (vacancy_id,))
        rows = c.fetchall()
        c.close()
        conn.close()
        results = []
        for row in rows:
            results.append({
                "id": row[0], "vacancy_id": row[1], "user_id": str(row[2]),
                "username": row[3] or "", "cv_filename": row[4] or "",
                "cover_letter": row[5] or "", "status": row[6] or "pending",
                "created_at": str(row[7]) if row[7] else "",
            })
        return results
    except Exception as e:
        print(f"[!] get_applications_for_vacancy_db error: {e}")
        return []


def get_applications_for_user_db(user_id):
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM app.applications WHERE user_id = %s ORDER BY created_at DESC",
                  (int(user_id),))
        rows = c.fetchall()
        c.close()
        conn.close()
        results = []
        for row in rows:
            results.append({
                "id": row[0], "vacancy_id": row[1], "user_id": str(row[2]),
                "username": row[3] or "", "cv_filename": row[4] or "",
                "cover_letter": row[5] or "", "status": row[6] or "pending",
                "created_at": str(row[7]) if row[7] else "",
            })
        return results
    except Exception as e:
        print(f"[!] get_applications_for_user_db error: {e}")
        return []


# === Saved Jobs ===

def init_saved_jobs_table():
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS app.saved_jobs (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL,
                job_title TEXT DEFAULT '',
                company TEXT DEFAULT '',
                location TEXT DEFAULT '',
                job_type TEXT DEFAULT '',
                match_percent INTEGER DEFAULT 0,
                skills TEXT DEFAULT '',
                categorized_skills TEXT DEFAULT '',
                description TEXT DEFAULT '',
                reason_text TEXT DEFAULT '',
                link TEXT DEFAULT '',
                date TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] init_saved_jobs_table error: {e}")
        return False


def get_saved_jobs_db(username):
    conn = get_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM app.saved_jobs WHERE username = %s ORDER BY created_at DESC", (username,))
        rows = c.fetchall()
        c.close()
        conn.close()
        results = []
        for row in rows:
            results.append({
                "id": row[0], "username": row[1], "job_title": row[2] or "",
                "company": row[3] or "", "location": row[4] or "",
                "job_type": row[5] or "", "match_percent": row[6] or 0,
                "skills": row[7] or "", "categorized_skills": row[8] or "",
                "description": row[9] or "", "reason_text": row[10] or "",
                "link": row[11] or "", "date": row[12] or "",
            })
        return results
    except Exception as e:
        print(f"[!] get_saved_jobs_db error: {e}")
        return None


def save_job_db(username, job_data):
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO app.saved_jobs
                (username, job_title, company, location, job_type, match_percent,
                 skills, categorized_skills, description, reason_text, link, date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            username,
            job_data.get("job_title", ""),
            job_data.get("company", ""),
            job_data.get("location", ""),
            job_data.get("job_type", ""),
            job_data.get("match_percent", 0),
            job_data.get("skills", ""),
            job_data.get("categorized_skills", ""),
            job_data.get("description", ""),
            job_data.get("reason_text", ""),
            job_data.get("link", ""),
            job_data.get("date", ""),
        ))
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] save_job_db error: {e}")
        return False


def clear_saved_jobs_db(username):
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("DELETE FROM app.saved_jobs WHERE username = %s", (username,))
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] clear_saved_jobs_db error: {e}")
        return False


def remove_saved_job_db(username, idx):
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            DELETE FROM app.saved_jobs
            WHERE username = %s AND id = (
                SELECT id FROM app.saved_jobs
                WHERE username = %s ORDER BY created_at DESC LIMIT 1 OFFSET %s
            )
        """, (username, username, idx))
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] remove_saved_job_db error: {e}")
        return False


# === Recommendation Logs ===

def init_reco_logs_table():
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS app.reco_logs (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL,
                ts DOUBLE PRECISION,
                query TEXT DEFAULT '',
                filter_country TEXT DEFAULT '',
                filter_city TEXT DEFAULT '',
                num_results INTEGER DEFAULT 0,
                avg_match_percent DOUBLE PRECISION,
                duration DOUBLE PRECISION,
                top_skills TEXT DEFAULT '',
                method TEXT DEFAULT '',
                alpha DOUBLE PRECISION DEFAULT 0.7,
                diversity_lambda DOUBLE PRECISION DEFAULT 0.7
            )
        """)
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] init_reco_logs_table error: {e}")
        return False


def get_reco_logs_db(username):
    conn = get_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM app.reco_logs WHERE username = %s ORDER BY ts DESC NULLS LAST", (username,))
        rows = c.fetchall()
        c.close()
        conn.close()
        results = []
        for row in rows:
            top_skills = row[9] or ""
            if isinstance(top_skills, str) and top_skills:
                top_skills = [s.strip() for s in top_skills.split(",") if s.strip()]
            else:
                top_skills = []
            results.append({
                "id": row[0], "username": row[1], "ts": row[2],
                "query": row[3] or "", "filter_country": row[4] or "",
                "filter_city": row[5] or "", "num_results": row[6] or 0,
                "avg_match_percent": row[7], "duration": row[8],
                "top_skills": top_skills,
                "method": row[10] or "", "alpha": row[11] or 0.7,
                "diversity_lambda": row[12] or 0.7,
            })
        return results
    except Exception as e:
        print(f"[!] get_reco_logs_db error: {e}")
        return None


def append_reco_log_db(username, entry):
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        top_skills = entry.get("top_skills", [])
        if isinstance(top_skills, list):
            top_skills = ",".join(top_skills)
        c.execute("""
            INSERT INTO app.reco_logs
                (username, ts, query, filter_country, filter_city, num_results,
                 avg_match_percent, duration, top_skills, method, alpha, diversity_lambda)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            username, entry.get("ts"), entry.get("query", ""),
            entry.get("filter_country", ""), entry.get("filter_city", ""),
            entry.get("num_results", 0), entry.get("avg_match_percent"),
            entry.get("duration"), top_skills,
            entry.get("method", ""), entry.get("alpha", 0.7),
            entry.get("diversity_lambda", 0.7),
        ))
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] append_reco_log_db error: {e}")
        return False


# === Feedback Logs ===

def init_feedback_logs_table():
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS app.feedback_logs (
                id SERIAL PRIMARY KEY,
                ts DOUBLE PRECISION,
                username TEXT DEFAULT '',
                action TEXT DEFAULT '',
                job_title TEXT DEFAULT '',
                company TEXT DEFAULT '',
                link TEXT DEFAULT '',
                match_percent INTEGER
            )
        """)
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] init_feedback_logs_table error: {e}")
        return False


def append_feedback_log_db(entry):
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO app.feedback_logs
                (ts, username, action, job_title, company, link, match_percent)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            entry.get("ts"), entry.get("username", ""),
            entry.get("action", ""), entry.get("job_title", ""),
            entry.get("company", ""), entry.get("link", ""),
            entry.get("match_percent"),
        ))
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] append_feedback_log_db error: {e}")
        return False


# === Employer Vacancies Listing (merge DB + JSON) ===

def list_employer_vacancies_db(user_id=None, search="", company="", limit=200):
    """Get vacancies from app.vacancies (employer-created), filtered in SQL.

    Filtering di SQL supaya tidak load semua baris per request (605K+ baris).
    """
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        query = "SELECT * FROM app.vacancies"
        params = []
        conditions = []
        if user_id is not None:
            conditions.append("user_id = %s")
            params.append(user_id)
        if search:
            conditions.append(
                "(LOWER(job_title) LIKE %s OR LOWER(company) LIKE %s "
                "OR LOWER(CAST(skills AS TEXT)) LIKE %s)"
            )
            params.extend([f"%{search.lower()}%"] * 3)
        if company:
            conditions.append("LOWER(company) = %s")
            params.append(company.lower())
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC NULLS LAST LIMIT %s"
        params.append(limit)
        c.execute(query, params)
        rows = c.fetchall()
        c.close()
        conn.close()
        results = []
        for row in rows:
            skills = row[5] if row[5] else []
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.strip("{}").split(",") if s.strip()]
            results.append({
                "id": row[0], "user_id": row[1], "job_title": row[2],
                "company": row[3] or "", "description": row[4] or "",
                "skills": list(skills) if not isinstance(skills, list) else skills,
                "salary_min": row[6] or "", "salary_max": row[7] or "",
                "job_level": row[8] or "", "job_type": row[9] or "",
                "location": row[10] or "", "created_at": str(row[11]) if row[11] else "",
            })
        return results
    except Exception as e:
        print(f"[!] list_employer_vacancies_db error: {e}")
        return []


def init_all_tables():
    """Initialize all app tables."""
    for fn in [init_companies_table, init_profiles_table, init_vacancies_table,
               init_applications_table, init_saved_jobs_table,
               init_reco_logs_table, init_feedback_logs_table,
               init_messages_table, init_notifications_table]:
        try:
            fn()
        except Exception as e:
            print(f"[!] Table init error: {e}")


# === NOTIFICATIONS TABLE ===

def init_notifications_table():
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS app.notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                type VARCHAR(50) NOT NULL,
                message TEXT NOT NULL,
                related_id TEXT DEFAULT '',
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] init_notifications_table error: {e}")
        return False


def create_notification(user_id, notif_type, message, related_id=""):
    conn = get_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO app.notifications (user_id, type, message, related_id)
            VALUES (%s, %s, %s, %s) RETURNING id, created_at
        """, (user_id, notif_type, message, related_id))
        row = c.fetchone()
        conn.commit()
        c.close()
        conn.close()
        return {"id": row[0], "user_id": user_id, "type": notif_type,
                "message": message, "related_id": related_id,
                "is_read": False, "created_at": str(row[1]) if row[1] else ""}
    except Exception as e:
        print(f"[!] create_notification error: {e}")
        return None


def get_notifications_for_user(user_id, limit=20):
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        c.execute("""
            SELECT id, user_id, type, message, related_id, is_read, created_at
            FROM app.notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (user_id, limit))
        rows = c.fetchall()
        c.close()
        conn.close()
        return [{
            "id": r[0], "user_id": r[1], "type": r[2],
            "message": r[3], "related_id": r[4],
            "is_read": r[5], "created_at": str(r[6]) if r[6] else "",
        } for r in rows]
    except Exception as e:
        print(f"[!] get_notifications_for_user error: {e}")
        return []


def count_unread_notifications(user_id):
    conn = get_connection()
    if not conn:
        return 0
    try:
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) FROM app.notifications
            WHERE user_id = %s AND is_read = FALSE
        """, (user_id,))
        count = c.fetchone()[0]
        c.close()
        conn.close()
        return count
    except Exception as e:
        print(f"[!] count_unread_notifications error: {e}")
        return 0


def mark_notification_read(notif_id, user_id):
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE app.notifications SET is_read = TRUE
            WHERE id = %s AND user_id = %s
        """, (notif_id, user_id))
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] mark_notification_read error: {e}")
        return False


def mark_all_notifications_read(user_id):
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE app.notifications SET is_read = TRUE
            WHERE user_id = %s AND is_read = FALSE
        """, (user_id,))
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] mark_all_notifications_read error: {e}")
        return False


# === MESSAGES TABLE ===

def init_messages_table():
    conn = get_connection()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS app.messages (
                id SERIAL PRIMARY KEY,
                vacancy_id TEXT NOT NULL,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] init_messages_table error: {e}")
        return False


def send_message_db(vacancy_id, sender_id, receiver_id, message):
    conn = get_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO app.messages (vacancy_id, sender_id, receiver_id, message)
            VALUES (%s, %s, %s, %s) RETURNING id, created_at
        """, (vacancy_id, sender_id, receiver_id, message))
        row = c.fetchone()
        conn.commit()
        c.close()
        conn.close()
        return {
            "id": row[0], "vacancy_id": vacancy_id,
            "sender_id": sender_id, "receiver_id": receiver_id,
            "message": message, "created_at": str(row[1]) if row[1] else "",
        }
    except Exception as e:
        print(f"[!] send_message_db error: {e}")
        return None


def get_conversation_db(vacancy_id, user_a_id, user_b_id):
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        c.execute("""
            SELECT id, vacancy_id, sender_id, receiver_id, message, created_at
            FROM app.messages
            WHERE vacancy_id = %s AND (
                (sender_id = %s AND receiver_id = %s) OR
                (sender_id = %s AND receiver_id = %s)
            )
            ORDER BY created_at ASC
        """, (vacancy_id, user_a_id, user_b_id, user_b_id, user_a_id))
        rows = c.fetchall()
        c.close()
        conn.close()
        return [{
            "id": r[0], "vacancy_id": r[1], "sender_id": r[2],
            "receiver_id": r[3], "message": r[4], "created_at": str(r[5]) if r[5] else "",
        } for r in rows]
    except Exception as e:
        print(f"[!] get_conversation_db error: {e}")
        return []


def get_messages_for_user_db(user_id):
    conn = get_connection()
    if not conn:
        return []
    try:
        c = conn.cursor()
        c.execute("""
            SELECT id, vacancy_id, sender_id, receiver_id, message, created_at
            FROM app.messages
            WHERE receiver_id = %s OR sender_id = %s
            ORDER BY created_at DESC
        """, (user_id, user_id))
        rows = c.fetchall()
        c.close()
        conn.close()
        return [{
            "id": r[0], "vacancy_id": r[1], "sender_id": r[2],
            "receiver_id": r[3], "message": r[4], "created_at": str(r[5]) if r[5] else "",
        } for r in rows]
    except Exception as e:
        print(f"[!] get_messages_for_user_db error: {e}")
        return []


def update_application_status_db(app_id, new_status):
    conn = get_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("UPDATE app.applications SET status = %s WHERE id = %s RETURNING *",
                  (new_status, app_id))
        row = c.fetchone()
        conn.commit()
        c.close()
        conn.close()
        if row:
            return {
                "id": row[0], "vacancy_id": row[1], "user_id": str(row[2]),
                "username": row[3] or "", "cv_filename": row[4] or "",
                "cover_letter": row[5] or "", "status": row[6] or "pending",
                "created_at": str(row[7]) if row[7] else "",
            }
        return None
    except Exception as e:
        print(f"[!] update_application_status_db error: {e}")
        return None
