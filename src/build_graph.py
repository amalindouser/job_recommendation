from flask import Flask, render_template, request
import os
import pandas as pd
import psycopg2
import networkx as nx
import functools
from dotenv import load_dotenv
from recommender_sentence import recommend_jobs_sentence

# ==========================
# App Init
# ==========================
app = Flask(__name__)
load_dotenv()
DB_URL = os.getenv("DB_URL")


# ==========================
# Load Graph (cache)
# ==========================
@functools.lru_cache(maxsize=1)
def load_graph():
    base_dir = os.path.dirname(__file__)
    clean_path = os.path.join(base_dir, "graph_jobs_clean.graphml")
    default_path = os.path.join(base_dir, "graph_jobs.graphml")

    if os.path.exists(clean_path):
        graph_file = clean_path
    elif os.path.exists(default_path):
        graph_file = default_path
    else:
        raise FileNotFoundError("No graph file found (graph_jobs_clean.graphml or graph_jobs.graphml)")

    G = nx.read_graphml(graph_file)
    print(f"✔ Graph loaded from {graph_file}")
    return G


# ==========================
# Helper DB
# ==========================
def get_jobs(country=None, city=None):
    conn = psycopg2.connect(DB_URL)
    query = "SELECT * FROM jobs_skills WHERE 1=1"
    params = []

    if country:
        query += " AND LOWER(search_country)=LOWER(%s)"
        params.append(country)

    if city:
        query += " AND LOWER(search_city)=LOWER(%s)"
        params.append(city)

    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df


# ==========================
# ✅ NORMALIZER (KUNCI UTAMA)
# ==========================
def normalize_job(job, score=None, reason=None):
    return {
        "job_title": job.get("job_title"),
        "company": job.get("company"),
        "location": (
            job.get("job_location")
            or ", ".join(
                filter(None, [
                    job.get("search_city"),
                    job.get("search_country")
                ])
            )
        ),
        "skills": job.get("skills"),
        "match_percent": score,
        "reason_text": reason,
        "first_seen": job.get("first_seen"),
        "link": job.get("job_link", "#")
    }


# ==========================
# Location Helper
# ==========================
def get_countries_cities():
    df = get_jobs()
    if df.empty:
        return [], {}

    countries = sorted(df["search_country"].dropna().unique())
    cities = {
        c: sorted(
            df[df["search_country"] == c]["search_city"]
            .dropna()
            .unique()
        )
        for c in countries
    }
    return countries, cities


# ==========================
# Route
# ==========================
@app.route("/", methods=["GET", "POST"])
def index():
    error = None
    results = []

    countries, countries_cities = get_countries_cities()
    selected_country = ""
    selected_city = ""
    skills_text = ""

    if request.method == "POST":
        skills_text = request.form.get("skills", "").strip()
        selected_country = request.form.get("country", "").strip()
        selected_city = request.form.get("city", "").strip()

        try:
            # ==========================
            # ✅ MODE 1 — Sentence Matching
            # ==========================
            if skills_text:
                G = load_graph()
                raw_results = recommend_jobs_sentence(
                    G,
                    skills_text,
                    top_n=12,
                    filter_country=selected_country,
                    filter_city=selected_city
                )

                results = [
                    normalize_job(
                        job=r["job"],
                        score=r.get("score"),
                        reason=r.get("reason")
                    )
                    for r in raw_results
                ]

                if not results:
                    error = "Tidak ditemukan pekerjaan yang relevan."

            # ==========================
            # ✅ MODE 2 — Lokasi saja
            # ==========================
            elif selected_country or selected_city:
                df = get_jobs(
                    country=selected_country,
                    city=selected_city
                )

                if df.empty:
                    error = "Tidak ada pekerjaan di lokasi tersebut."
                else:
                    results = [
                        normalize_job(row)
                        for _, row in df.head(12).iterrows()
                    ]

            else:
                error = "Masukkan skill atau pilih lokasi terlebih dahulu."

        except Exception as e:
            print("SYSTEM ERROR:", e)
            error = "Terjadi kesalahan sistem."

    return render_template(
        "index.html",
        results=results,
        skills=skills_text,
        error=error,
        countries=countries,
        countries_cities=countries_cities,
        selected_country=selected_country,
        selected_city=selected_city,
        cities=countries_cities.get(selected_country, [])
    )


if __name__ == "__main__":
    app.run(debug=True)
