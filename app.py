from flask import Flask, render_template, request
import os
import pandas as pd
import psycopg2
import networkx as nx
from recommender import recommend_jobs
from dotenv import load_dotenv
import functools

app = Flask(__name__)

# =======================================================
# 🔧 LOAD ENV
# =======================================================
load_dotenv()
DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise ValueError("❌ DB_URL tidak ditemukan. Flask tidak bisa load graph dari Neon.")

# =======================================================
# 🔥 LOAD GRAPH DARI FILE GRAPHML (READ-ONLY)
# =======================================================
@functools.lru_cache(maxsize=1)
def load_graph():
    graph_file = os.path.join(os.path.dirname(__file__), "knowledge_graph_light.graphml")
    if not os.path.exists(graph_file):
        raise FileNotFoundError(f"❌ File GraphML tidak ditemukan: {graph_file}")
    try:
        G = nx.read_graphml(graph_file)
        print("✔ Graph berhasil dimuat dari GraphML!")
        return G
    except Exception as e:
        raise RuntimeError(f"❌ Gagal load GraphML: {e}")

# =======================================================
# 🗂 AMBIL DATA JOB DARI DATABASE
# =======================================================
def get_jobs(country=None, city=None):
    try:
        conn = psycopg2.connect(DB_URL)
        query = "SELECT * FROM jobs_skills WHERE 1=1"
        params = []

        if country:
            query += " AND LOWER(search_country) = LOWER(%s)"
            params.append(country)
        if city:
            query += " AND LOWER(search_city) = LOWER(%s)"
            params.append(city)

        df = pd.read_sql(query, conn, params=params)
        conn.close()
        return df

    except Exception as e:
        print("❌ DB Error:", e)
        return pd.DataFrame()

# =======================================================
# 🌍 LIST NEGARA & KOTA
# =======================================================
def get_countries_cities():
    df = get_jobs()
    if df.empty:
        return [], {}

    df.columns = [c.lower() for c in df.columns]
    df.rename(columns={
        "country": "search_country",
        "city": "search_city"
    }, inplace=True, errors="ignore")

    countries = sorted(df["search_country"].dropna().unique())
    cities_by_country = {
        c: sorted(df[df["search_country"] == c]["search_city"].dropna().unique())
        for c in countries
    }

    return countries, cities_by_country

# =======================================================
# 🔎 FILTER JOBS BERDASARKAN LOKASI (LIMIT 12)
# =======================================================
def filter_jobs(df, country=None, city=None, limit=12):
    if country:
        df = df[df["search_country"].str.lower() == country.lower()]
    if city:
        df = df[df["search_city"].str.lower() == city.lower()]
    return df.head(limit)


@app.route("/", methods=["GET", "POST"])
def index():
    error = None
    results = []
    skills_input = []
    selected_country = ""
    selected_city = ""

    countries, countries_cities = get_countries_cities()

    if request.method == "POST":
        skills_text = request.form.get("skills", "")
        skills_input = [s.strip().lower() for s in skills_text.split(",") if s.strip()]

        selected_country = request.form.get("country", "").strip()
        selected_city = request.form.get("city", "").strip()

        # =======================================================
        # CASE 1: User tidak memasukkan skill → tampilkan job by lokasi
        # =======================================================
        if not skills_input:
            df_filtered = filter_jobs(get_jobs(), selected_country, selected_city, limit=12)
            if df_filtered.empty:
                error = "Tidak ditemukan pekerjaan di lokasi tersebut."
            else:
                results = []
                for _, row in df_filtered.iterrows():
                    job_skills = [
                        s.strip() for s in str(row.get("skills", "")).split(",") if s.strip()
                    ][:6]  # 🔥 Batasi skill di tampilan juga

                    results.append({
                        "job_title": row.get("job_title", ""),
                        "company": row.get("company", ""),
                        "location": f"{row.get('search_city','')}, {row.get('search_country','')}",
                        "job_type": row.get("job_type", ""),
                        "date": row.get("first_seen", ""),
                        "link": row.get("job_link", "#"),
                        "skills_job": job_skills,
                        "match_percent": None,
                        "matched_skills": [],
                        "missing_skills": [],
                        "reason_text": "Pekerjaan ini direkomendasikan berdasarkan lokasi."
                    })

        # =======================================================
        # CASE 2: User memasukkan skill → gunakan Knowledge Graph
        # =======================================================
        else:
            try:
                G = load_graph()
                results = recommend_jobs(G, skills_input, top_n=12)

            except Exception as e:
                print("⚠️ Error:", e)
                error = "Terjadi kesalahan saat menghasilkan rekomendasi."

    return render_template(
        "index.html",
        results=results,
        skills=skills_input,
        error=error,
        countries=countries,
        countries_cities=countries_cities,
        selected_country=selected_country,
        selected_city=selected_city,
        cities=countries_cities.get(selected_country, []),
    )


# if __name__ == "__main__":
#     app.run(debug=True)
