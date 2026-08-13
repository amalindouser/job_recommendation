"""Daftarkan seluruh perusahaan hasil scrape sebagai akun employer + impor semua lowongan.

- Skills dibersihkan dengan pipeline clean_skills (EXTRA_STOP_SKILLS, normalize, dedup)
- Deskripsi direkonstruksi dari judul + skill + kategori + lokasi + gaji (bukan boilerplate asli)
- Password dummy sama untuk semua akun, hash dihitung sekali lalu dipakai ulang

Sumber: data/all_jobs_clean.db (clean_jobs)
Target : PostgreSQL app.users / app.companies / app.vacancies
Output : data/employer_accounts.csv (username, password, company, job_count)

Cara pakai: ./venv/bin/python scripts/migrate_scraped_to_employers.py [--force] [--limit N]
"""
import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from werkzeug.security import generate_password_hash

from src.clean_skills import clean_and_dedup_skills
from src.db_service import get_connection

BASE = Path(__file__).parent.parent
SQLITE_DB = BASE / "data" / "all_jobs_clean.db"
ACCOUNTS_CSV = BASE / "data" / "employer_accounts.csv"
PASSWORD = "employer123"
CHUNK = 5000

JUNK_COMPANIES = {"", "false", "none", "nan", "null", "-", "0", "unknown", "tbd", "n/a", "na"}
KEEP_TITLES = {"pt", "cv", "tbk", "inc", "ltd", "llc", "co", "pvt", "sdn", "bhd"}

EMPLOYMENT_LABELS = {
    "full_time": "Full-time",
    "part_time": "Part-time",
    "contract": "Contract",
    "temporary": "Temporary",
    "internship": "Internship",
}

JOB_LEVEL_KEYWORDS = [
    (("senior", "lead", "principal", "staff", "expert", "sr "), "Senior"),
    (("junior", "entry", "fresh graduate", "jr", "trainee"), "Junior"),
    (("manager", "supervisor", "head of", "director", "vp"), "Managerial"),
]

PERIOD_LABEL = {
    "monthly": "/bulan",
    "yearly": "/tahun",
    "weekly": "/minggu",
    "hourly": "/jam",
}


def clean_company_name(raw):
    s = (raw or "").strip()
    if not s or s.lower() in JUNK_COMPANIES or s.isdigit():
        return None
    # buang suffix lokasi "(Jakarta)" di akhir nama
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    words = []
    for w in s.split():
        low = w.lower()
        if low in KEEP_TITLES:
            words.append(low.upper())
        else:
            words.append(low.capitalize())
    out = " ".join(words).strip()
    return out if out else None


def parse_json_list(val):
    if not val:
        return []
    try:
        v = json.loads(val)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def parse_json_dict(val):
    if not val:
        return {}
    try:
        v = json.loads(val)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def clean_skills(parsed, job_title):
    if not parsed:
        return []
    return clean_and_dedup_skills(",".join(parsed), desc_lower="", job_title=job_title)


def format_salary(smin, smax, currency, period):
    parts = []
    for x in (smin, smax):
        if x is None or x == "":
            continue
        try:
            x = float(x)
        except (ValueError, TypeError):
            continue
        parts.append(f"Rp {int(x):,}".replace(",", "."))
    if not parts:
        return ""
    text = " - ".join(parts)
    return text + PERIOD_LABEL.get(period or "", "")


def build_description(job_title, company, location, job_type, salary_text,
                      categories, cat_skills, skills):
    lines = [f"Lowongan: {job_title}", f"Perusahaan: {company}"]
    if location:
        lines.append(f"Lokasi: {location}")
    if job_type:
        lines.append(f"Tipe: {job_type}")
    if salary_text:
        lines.append(f"Gaji: {salary_text}")
    if categories:
        lines.append("Kategori: " + ", ".join(categories))
    if cat_skills:
        lines.append("Bidang Keterampilan:")
        for cat, sk in cat_skills.items():
            if sk:
                lines.append(f"- {cat}: {', '.join(sk)}")
    if skills:
        lines.append("Kualifikasi:")
        for s in skills:
            lines.append(f"- {s}")
    else:
        lines.append("Kualifikasi: Tidak disebutkan.")
    return "\n".join(lines)


def infer_job_level(title):
    t = (title or "").lower()
    for kws, label in JOB_LEVEL_KEYWORDS:
        if any(k in t for k in kws):
            return label
    return ""


def map_job_type(employment):
    if not employment or employment.lower() in ("false", "none"):
        return ""
    labels = []
    for part in str(employment).split(","):
        part = part.strip().lower()
        if part in EMPLOYMENT_LABELS:
            labels.append(EMPLOYMENT_LABELS[part])
    return ", ".join(labels)


def parse_posted_at(val):
    if not val:
        return None
    s = str(val).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s
    return None


def to_num_str(val):
    if val in (None, ""):
        return ""
    try:
        return f"{float(val):.0f}"
    except (ValueError, TypeError):
        return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="jalankan ulang walau CSV akun sudah ada")
    parser.add_argument("--limit", type=int, default=0,
                        help="batasi jumlah lowongan yang diproses (0 = semua, untuk tes)")
    args = parser.parse_args()

    if ACCOUNTS_CSV.exists() and not args.force:
        print(f"[STOP] {ACCOUNTS_CSV.name} sudah ada. Jalankan dengan --force untuk mengulang.")
        return

    print("[1/5] Baca data dari SQLite...")
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    total = sqlite_conn.execute("SELECT COUNT(*) FROM clean_jobs").fetchone()[0]
    print(f"      total baris: {total}")
    if args.limit:
        total = min(total, args.limit)

    companies = {}
    company_jobs = {}
    t0 = time.time()
    offset = 0
    while True:
        if args.limit and offset >= args.limit:
            break
        rows = sqlite_conn.execute(
            "SELECT id, job_title, company FROM clean_jobs ORDER BY id LIMIT ? OFFSET ?",
            (CHUNK, offset),
        ).fetchall()
        if not rows:
            break
        for jid, title, raw_company in rows:
            name = clean_company_name(raw_company)
            if not name:
                continue
            key = name.lower()
            if key not in companies:
                companies[key] = name
                company_jobs[key] = 0
            company_jobs[key] += 1
        offset += CHUNK
        if offset % 100000 < CHUNK:
            print(f"      scan {offset}/{total}")

    print(f"      perusahaan unik: {len(companies)} "
          f"({time.time() - t0:.1f}s)")

    print("[2/5] Buka koneksi PostgreSQL...")
    pg_conn = get_connection()
    if not pg_conn:
        print("[FAIL] Tidak bisa konek PostgreSQL.")
        return
    cur = pg_conn.cursor()

    print("[3/5] Daftarkan akun employer + perusahaan...")
    hash_pwd = generate_password_hash(PASSWORD)
    ordered = sorted(companies.keys())
    t0 = time.time()
    cur.executemany(
        "INSERT INTO app.users (username, email, password, role) "
        "VALUES (%s, %s, %s, 'employer') ON CONFLICT (username) DO NOTHING",
        [(f"emp{i:05d}", f"emp{i:05d}@research.local", hash_pwd) for i in range(len(ordered))],
    )
    cur.execute("SELECT username, id FROM app.users WHERE username LIKE 'emp%'")
    id_by_username = dict(cur.fetchall())
    user_map = {key: id_by_username[f"emp{i:05d}"] for i, key in enumerate(ordered)}
    cur.executemany(
        "INSERT INTO app.companies (user_id, name, description) VALUES (%s, %s, %s) "
        "ON CONFLICT (user_id) DO NOTHING",
        [(user_map[key], companies[key], "Perusahaan hasil impor data penelitian.") for key in ordered],
    )
    pg_conn.commit()
    print(f"      {len(ordered)} akun + perusahaan siap ({time.time() - t0:.1f}s)")

    print("[4/5] Impor lowongan (bersihkan skill + rekonstruksi deskripsi)...")
    vac_count = 0
    skipped = 0
    t0 = time.time()
    offset = 0
    while True:
        if args.limit and offset >= args.limit:
            break
        sql_rows = sqlite_conn.execute(
            """SELECT id, job_title, company, location, employment, salary_min, salary_max,
                      salary_currency, salary_period, posted_at, job_url, categories,
                      skills, categorized_skills, description
               FROM clean_jobs ORDER BY id LIMIT ? OFFSET ?""",
            (CHUNK, offset),
        ).fetchall()
        if not sql_rows:
            break
        batch = []
        for r in sql_rows:
            (jid, job_title, raw_company, location, employment, salary_min, salary_max,
             salary_currency, salary_period, posted_at, job_url, categories,
             skills_raw, cat_skills_raw, _desc) = r
            name = clean_company_name(raw_company)
            if not name:
                skipped += 1
                continue
            key = name.lower()
            uid = user_map.get(key)
            if uid is None:
                skipped += 1
                continue

            skills = clean_skills(parse_json_list(skills_raw), job_title)
            cat_skills = {k: [s for s in v if s] for k, v in parse_json_dict(cat_skills_raw).items()}
            cats = [c for c in parse_json_list(categories) if c]
            salary_text = format_salary(salary_min, salary_max, salary_currency, salary_period)
            job_type = map_job_type(employment)
            description = build_description(
                job_title, name, location, job_type, salary_text,
                cats, cat_skills, skills,
            )
            vid = "jsv_" + hashlib.md5((job_url or f"r{jid}").encode()).hexdigest()[:14]
            sal_min = to_num_str(salary_min)
            sal_max = to_num_str(salary_max)
            batch.append((
                vid, uid, job_title, name, description, skills,
                sal_min, sal_max, infer_job_level(job_title), job_type,
                location or "", parse_posted_at(posted_at),
            ))
        cur.executemany(
            """INSERT INTO app.vacancies (id, user_id, job_title, company, description, skills,
                                          salary_min, salary_max, job_level, job_type, location, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            batch,
        )
        pg_conn.commit()
        vac_count += len(batch)
        offset += CHUNK
        if offset % 100000 < CHUNK or vac_count == len(batch):
            print(f"      {vac_count}/{total - skipped} lowongan ({time.time() - t0:.1f}s)")
    pg_conn.commit()
    print(f"      selesai: {vac_count} lowongan ({time.time() - t0:.1f}s)")

    print("[5/5] Tulis daftar akun + index...")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_user_id ON app.vacancies(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_vacancies_company ON app.vacancies(company)")
    pg_conn.commit()
    with open(ACCOUNTS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["username", "password", "company", "job_count"])
        for i, key in enumerate(ordered):
            w.writerow([f"emp{i:05d}", PASSWORD, companies[key], company_jobs[key]])
    print(f"      daftar akun: {ACCOUNTS_CSV}")

    cur.close()
    pg_conn.close()
    sqlite_conn.close()
    print(f"\n[DONE] {len(ordered)} perusahaan, {vac_count} lowongan, {skipped} baris diskip.")


if __name__ == "__main__":
    main()
