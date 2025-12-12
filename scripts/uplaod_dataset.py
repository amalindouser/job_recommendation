import psycopg2
import pandas as pd
import os
from dotenv import load_dotenv
from tqdm import tqdm   # PROGRESS BAR

load_dotenv()
DB_URL = os.getenv("DB_URL")

# ====== 1. LOAD DATASET ======
df = pd.read_csv("jobs_skills_1.csv")

# ====== 2. KONEKSI ======
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

# ====== 3. LOOP INSERT + PROGRESS BAR ======
for _, row in tqdm(df.iterrows(), total=len(df), desc="Uploading jobs_skills"):
    cur.execute("""
        INSERT INTO jobs_skills (
            job_title,
            company,
            search_country,
            search_city,
            search_position,
            job_level,
            job_type,
            skills,
            job_link,
            job_location,
            first_seen,
            description
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        row["job_title"],
        row["company"],
        row["search_country"],
        row["search_city"],
        row["search_position"],
        row["job_level"],
        row["job_type"],
        row["skills"],
        row["job_link"],
        row["job_location"],
        row["first_seen"],
        None  
    ))

conn.commit()
cur.close()
conn.close()

print("🔥 Upload selesai tanpa description!")
