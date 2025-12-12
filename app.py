from flask import Flask, render_template, request, redirect, url_for, flash
import os
import pandas as pd
import psycopg2
import psycopg2.extras
import networkx as nx
from src.recommender_sentence import recommend_jobs_sentence
from dotenv import load_dotenv
import time
import functools
import json
from pathlib import Path
import re
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# ==========================
# App Init & Config
# ==========================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-prod')
load_dotenv()

DB_URL = os.getenv("DB_URL")

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

def get_db_connection():
    """Get PostgreSQL database connection"""
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn

def init_user_db():
    """Initialize PostgreSQL user database if not exists."""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.close()
        print("✓ Database initialized successfully")
    except Exception as e:
        print(f"Database init error: {e}")

init_user_db()

# User model
class User(UserMixin):
    def __init__(self, id, username, email):
        self.id = id
        self.username = username
        self.email = email
    
    @staticmethod
    def get_by_username(username):
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('SELECT id, username, email FROM users WHERE username = %s', (username,))
            row = c.fetchone()
            conn.close()
            if row:
                return User(row[0], row[1], row[2])
        except Exception as e:
            print('get_by_username error:', e)
        return None
    
    @staticmethod
    def get_by_id(user_id):
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('SELECT id, username, email FROM users WHERE id = %s', (user_id,))
            row = c.fetchone()
            conn.close()
            if row:
                return User(row[0], row[1], row[2])
        except Exception as e:
            print('get_by_id error:', e)
        return None
    
    @staticmethod
    def check_password(username, password):
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('SELECT password FROM users WHERE username = %s', (username,))
            row = c.fetchone()
            conn.close()
            if row and check_password_hash(row[0], password):
                return True
        except Exception as e:
            print('check_password error:', e)
        return False
    
    @staticmethod
    def register(username, email, password):
        try:
            hashed_pwd = generate_password_hash(password)
            conn = get_db_connection()
            c = conn.cursor()
            c.execute('INSERT INTO users (username, email, password) VALUES (%s, %s, %s)',
                     (username, email, hashed_pwd))
            conn.close()
            return True
        except psycopg2.IntegrityError:
            return False
        except Exception as e:
            print('User.register error:', e)
            return False

@login_manager.user_loader
def load_user(user_id):
    return User.get_by_id(int(user_id))


# ==========================
# Load Graph (cache 1x)
# ==========================
@functools.lru_cache(maxsize=1)
def load_graph():
    base_dir = os.path.dirname(__file__)
    clean_path = os.path.join(base_dir, "data", "graph_jobs_clean.graphml")
    default_path = os.path.join(base_dir, "data", "graph_jobs.graphml")

    if os.path.exists(clean_path):
        graph_file = clean_path
    elif os.path.exists(default_path):
        graph_file = default_path
    else:
        raise FileNotFoundError("No graph file found (data/graph_jobs_clean.graphml or data/graph_jobs.graphml)")

    G = nx.read_graphml(graph_file)
    print(f"✔ Graph loaded from {graph_file}")
    return G


# ==========================
# Helper DB
# ==========================
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
        print("DB Error:", e)
        return pd.DataFrame()


def get_countries_cities():
    df = get_jobs()
    if df.empty:
        return [], {}

    countries = sorted(df["search_country"].dropna().unique())
    cities_by_country = {
        c: sorted(
            df[df["search_country"] == c]["search_city"]
            .dropna()
            .unique()
        )
        for c in countries
    }

    return countries, cities_by_country


# ==========================
# Saved jobs helpers (per-user)
# ==========================
SAVED_PATH = Path(os.path.dirname(__file__)) / "database" / "saved_jobs.json"
RECO_LOG_PATH = Path(os.path.dirname(__file__)) / "database" / "recommendation_logs.json"

def _ensure_user_structure():
    """Ensure saved_jobs.json and recommendation_logs.json have proper structure."""
    # Ensure saved_jobs.json
    if not SAVED_PATH.exists():
        SAVED_PATH.write_text(json.dumps({}, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # Ensure recommendation_logs.json
    if not RECO_LOG_PATH.exists():
        RECO_LOG_PATH.write_text(json.dumps({}, ensure_ascii=False, indent=2), encoding="utf-8")


def read_saved_jobs(username=None):
    """Read saved jobs for a specific user or all users if username is None."""
    _ensure_user_structure()
    try:
        data = json.loads(SAVED_PATH.read_text(encoding="utf-8"))
        # handle legacy format where file was a list of jobs
        if isinstance(data, list):
            if username:
                # migrate legacy list into per-user map under current username
                new = {username: data}
                SAVED_PATH.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
                return data
            return data

        if username:
            return data.get(username, [])
        return data
    except Exception:
        return [] if username else {}


def write_saved_jobs(jobs, username):
    """Write saved jobs for a specific user."""
    _ensure_user_structure()
    try:
        data = json.loads(SAVED_PATH.read_text(encoding="utf-8"))
        # if data is a legacy list, convert to dict and assign under username
        if isinstance(data, list):
            data = {username: data}

        data[username] = jobs
        SAVED_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print("Failed to write saved jobs:", e)
        return False


def read_reco_logs(username=None):
    """Read recommendation logs for a specific user or all users if username is None."""
    _ensure_user_structure()
    try:
        data = json.loads(RECO_LOG_PATH.read_text(encoding="utf-8"))
        # migrate legacy list -> per-user mapping
        if isinstance(data, list):
            if username:
                new = {username: data}
                RECO_LOG_PATH.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
                return data
            return data

        if username:
            return data.get(username, [])
        return data
    except Exception:
        return [] if username else {}


def append_reco_log(entry: dict, username):
    """Append a recommendation log entry for a specific user."""
    _ensure_user_structure()
    try:
        data = json.loads(RECO_LOG_PATH.read_text(encoding="utf-8"))
        # if legacy list -> migrate into dict under username
        if isinstance(data, list):
            data = {username: data}

        if username not in data:
            data[username] = []
        data[username].append(entry)
        RECO_LOG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print("Failed to write reco log:", e)
        return False


# ==========================
# Route
# ==========================
@app.route("/", methods=["GET"])
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        password_confirm = request.form.get("password_confirm", "").strip()
        
        if not username or not email or not password:
            flash("All fields are required.", "error")
            return redirect(url_for('register'))
        
        if password != password_confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for('register'))
        
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return redirect(url_for('register'))
        
        if User.register(username, email, password):
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for('login'))
        else:
            flash("Username or email already exists.", "error")
            return redirect(url_for('register'))
    
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if not username or not password:
            flash("Username and password required.", "error")
            return redirect(url_for('login'))
        
        if User.check_password(username, password):
            user = User.get_by_username(username)
            login_user(user)
            return redirect(url_for('landing'))
        else:
            flash("Invalid username or password.", "error")
            return redirect(url_for('login'))
    
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "success")
    return redirect(url_for('landing'))


@app.route("/search", methods=["GET", "POST"])
@login_required
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
            # ==============================
            # MODE 1 → Sentence Matching
            # ==============================
            if skills_text:
                G = load_graph()
                t0 = time.time()
                results = recommend_jobs_sentence(
                    G,
                    skills_text,
                    top_n=12,
                    filter_country=selected_country,
                    filter_city=selected_city
                )
                t1 = time.time()
                duration = t1 - t0

                # log recommendation query for analytics
                try:
                    mp_vals = [r.get('match_percent') for r in results if r.get('match_percent') is not None]
                    avg_mp = round(sum(mp_vals) / len(mp_vals), 2) if mp_vals else None
                except Exception:
                    avg_mp = None

                # aggregate top skills from returned results
                skills_counter_local = {}
                try:
                    for r in results:
                        for s in r.get('skills', []) or []:
                            key = re.sub(r"[^a-z0-9+ #.+-]", " ", str(s).strip().lower()).strip()
                            if key:
                                skills_counter_local[key] = skills_counter_local.get(key, 0) + 1
                    top_sk_local = sorted(skills_counter_local.items(), key=lambda x: x[1], reverse=True)[:5]
                    top_sk_local = [k for k,_ in top_sk_local]
                except Exception:
                    top_sk_local = []

                try:
                    append_reco_log({
                        'ts': time.time(),
                        'query': skills_text,
                        'filter_country': selected_country,
                        'filter_city': selected_city,
                        'num_results': len(results),
                        'avg_match_percent': avg_mp,
                        'duration': round(duration, 3),
                        'top_skills': top_sk_local,
                    }, current_user.username)
                except Exception:
                    pass

                if not results:
                    error = "No relevant jobs found."

            
            elif selected_country or selected_city:
                df = get_jobs(
                    country=selected_country,
                    city=selected_city
                )

                if df.empty:
                    error = "No jobs found for that location."
                else:
                    results = []

                    for _, row in df.head(12).iterrows():
                        results.append({
                            "job_title": row.get("job_title"),
                            "company": row.get("company_name"),
                            "location": f"{row.get('search_city')}, {row.get('search_country')}",
                            "job_type": row.get("job_type"),
                            "date": str(row.get("first_seen")),
                            "skills": (
                            [s.strip() for s in row.get("skills").split(",")]
                            if pd.notna(row.get("skills"))
                            else []
                        ),

                            "matched_skills": [],
                            "missing_skills": [],
                            "match_percent": None,
                            "reason_text": f"🌍 Job in {selected_city}, {selected_country}. Matches your location preference. Check details for more information.",
                            "link": row.get("job_link", "#")
                        })


            
            else:
                error = "Please enter skills or select a location first."

        except Exception as e:
            print("System Error:", e)
            error = "A system error occurred."

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


@app.route("/saved", methods=["GET"])
@login_required
def saved_jobs():
    jobs = read_saved_jobs(current_user.username)
    return render_template("saved.html", saved=jobs)


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    # load graph to compute job count
    G = None
    total_jobs = 0
    try:
        G = load_graph()
        
        for _, d in G.nodes(data=True):
            if d.get("type") != "job":
                continue
            country = (d.get("search_country") or "").strip().lower()
            if country and country not in ("", "nan", "none", "unknown"):
                total_jobs += 1
    except Exception as e:
        print("dashboard: load_graph failed:", e)
        total_jobs = 0

    countries, countries_cities = get_countries_cities()
    saved = read_saved_jobs(current_user.username)

    # compute jobs per country and top skills
    jobs_per_country = {}
    skills_counter = {}
    try:
        if G is not None:
            for _, d in G.nodes(data=True):
                if d.get("type") != "job":
                    continue
                # Safely extract country, handling NaN/None
                country = d.get("search_country")
                if pd.isna(country):
                    country = d.get("job_location")
                # Normalize and guard against string 'nan' or empty
                country_str = str(country).strip() if country is not None else ""
                if country_str.lower() in ("", "nan", "none"):
                    country_str = "Unknown"

                jobs_per_country[country_str] = jobs_per_country.get(country_str, 0) + 1

                # Safely extract skills
                skills_raw = d.get("skills_raw") if d.get("skills_raw") is not None else d.get("skills")
                if pd.isna(skills_raw):
                    skills_raw = ""
                if skills_raw:
                    # soft-skill blacklist: common/high-frequency generic skills to ignore
                    SOFT_SKILLS_BLACKLIST = {
                        "communication",
                        "communication skills",
                        "strong communication",
                        "good communication",
                        "verbal communication",
                        "written communication",
                        "teamwork",
                        "team player",
                        "collaboration",
                        "leadership",
                        "problem solving",
                        "customer service",
                        "ability to",
                        "excellent",
                        "willingness",
                        "skill",
                        "skills",
                        "interpersonal",
                        "organizational",
                        "flexible",
                    }

                    for s in str(skills_raw).split(","):
                        sk = s.strip().lower()
                        if not sk or sk in ("nan", "none"):
                            continue

                        # normalize by removing punctuation and extra spaces
                        sk_norm = re.sub(r"[^a-z0-9+ #.+-]", " ", sk).strip()

                        # skip if any blacklist phrase appears inside the skill text
                        skip = False
                        for bad in SOFT_SKILLS_BLACKLIST:
                            if bad in sk_norm:
                                skip = True
                                break
                        if skip:
                            continue

                        skills_counter[sk_norm] = skills_counter.get(sk_norm, 0) + 1
    except Exception:
        pass

    # top skills list
    top_skills = sorted(skills_counter.items(), key=lambda x: x[1], reverse=True)[:12]

    # Remove unwanted keys so dashboard is clean (do not display Unknown/empty)
    for bad in ["Unknown", "", "nan", "none"]:
        jobs_per_country.pop(bad, None)

    # compute countries count excluding unknown/empty
    countries_count = len([k for k in jobs_per_country.keys() if str(k).strip() and str(k).strip().lower() not in ("nan", "none")])

    stats = {
        "total_jobs": total_jobs,
        "countries": countries_count,
        "saved_jobs": len(saved),
    }

    # debug log to help diagnose empty charts
    try:
        print(f"dashboard: total_jobs={total_jobs}, countries_in_payload={len(jobs_per_country)}, top_skills={top_skills[:5]}")
    except Exception:
        pass

    # Recommendation logs analytics
    reco_logs = read_reco_logs(current_user.username)
    recommend_stats = {}
    recommend_recent = []
    try:
        if reco_logs:
            total_q = len(reco_logs)
            total_results = sum((l.get('num_results') or 0) for l in reco_logs)
            avg_results = total_results / total_q if total_q else 0
            lat_sum = sum((l.get('duration') or 0) for l in reco_logs)
            avg_latency = lat_sum / total_q if total_q else 0
            match_vals = [l.get('avg_match_percent') for l in reco_logs if l.get('avg_match_percent') is not None]
            avg_match = (sum(match_vals) / len(match_vals)) if match_vals else None

            # top queries
            from collections import Counter
            qcounts = Counter([ (l.get('query') or '').strip().lower() for l in reco_logs ])
            top_queries = qcounts.most_common(8)

            # buckets for avg match percent
            buckets = {"0-19":0, "20-39":0, "40-59":0, "60-79":0, "80-100":0}
            for l in reco_logs:
                m = l.get('avg_match_percent')
                if m is None:
                    continue
                try:
                    m = float(m)
                except Exception:
                    continue
                if m < 20:
                    buckets['0-19'] += 1
                elif m < 40:
                    buckets['20-39'] += 1
                elif m < 60:
                    buckets['40-59'] += 1
                elif m < 80:
                    buckets['60-79'] += 1
                else:
                    buckets['80-100'] += 1

            recommend_stats = {
                'total_queries': total_q,
                'avg_results': round(avg_results,2),
                'avg_latency': round(avg_latency,3),
                'avg_match_percent': round(avg_match,2) if avg_match is not None else None,
                'top_queries': top_queries,
                'match_buckets': buckets
            }

            recent_raw = reco_logs[-10:]
            # reverse chronological
            recommend_recent = list(reversed([{
                'time': r.get('ts'), 'query': r.get('query'), 'num_results': r.get('num_results'),
                'avg_match_percent': r.get('avg_match_percent'), 'duration': r.get('duration')
            } for r in recent_raw]))

            timeseries_labels = []
            timeseries_values = []
            try:
                import datetime
                now_ts = time.time()
                thirty_days_ago = now_ts - (30 * 86400)

                daily_matches = {}
                for log in reco_logs:
                    ts = log.get('ts', 0)
                    if ts < thirty_days_ago:
                        continue
                    log_date = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                    if log_date not in daily_matches:
                        daily_matches[log_date] = []
                    m = log.get('avg_match_percent')
                    if m is not None:
                        try:
                            daily_matches[log_date].append(float(m))
                        except:
                            pass
                
                for date in sorted(daily_matches.keys()):
                    matches = daily_matches[date]
                    if matches:
                        avg_m = sum(matches) / len(matches)
                        timeseries_labels.append(date)
                        timeseries_values.append(round(avg_m,2))
                
                if timeseries_labels:
                    recommend_stats['timeseries'] = {
                        'labels': timeseries_labels,
                        'values': timeseries_values
                    }
            except Exception:
                pass

            # Latency percentiles
            try:
                latencies = [l.get('duration') or 0 for l in reco_logs if l.get('duration') is not None]
                if latencies:
                    latencies.sort()
                    n = len(latencies)
                    recommend_stats['latency_p50'] = round(latencies[int(n * 0.5)], 3)
                    recommend_stats['latency_p90'] = round(latencies[int(n * 0.9)], 3)
                    recommend_stats['latency_p99'] = round(latencies[int(n * 0.99)], 3)
            except Exception:
                pass

            # Top skills from queries
            try:
                skills_from_queries = {}
                for log in reco_logs:
                    skills = log.get('top_skills', []) or []
                    for skill in skills:
                        sk = skill.strip().lower()
                        skills_from_queries[sk] = skills_from_queries.get(sk, 0) + 1
                top_sk_q = sorted(skills_from_queries.items(), key=lambda x: x[1], reverse=True)[:8]
                if top_sk_q:
                    recommend_stats['top_skills_queries'] = top_sk_q
            except Exception:
                pass
    except Exception:
        recommend_stats = {}
        recommend_recent = []
        


    return render_template(
        "dashboard.html",
        stats=stats,
        jobs_per_country=jobs_per_country,
        top_skills=top_skills,
        recent_saved=saved[-8:][::-1],
        recommend_stats=recommend_stats,
        recommend_recent=recommend_recent
    )


@app.route("/save_job", methods=["POST"])
@login_required
def save_job():
    try:
        data = request.get_json(force=True)
        if not data:
            return {"success": False, "message": "No job data provided"}, 400

        jobs = read_saved_jobs(current_user.username)
        # dedupe by link if available, else by job title+company+location
        link = data.get("link")
        exists = False
        for j in jobs:
            if link and j.get("link") == link:
                exists = True
                break
            if (not link) and j.get("job_title") == data.get("job_title") and j.get("company") == data.get("company") and j.get("location") == data.get("location"):
                exists = True
                break

        if not exists:
            jobs.append(data)
            write_saved_jobs(jobs, current_user.username)

        return {"success": True, "saved_count": len(jobs)}
    except Exception as e:
        print("save_job error:", e)
        return {"success": False, "message": str(e)}, 500


@app.route("/remove_saved", methods=["POST"])
@login_required
def remove_saved():
    try:
        data = request.get_json(force=True)
        idx = data.get("index")
        jobs = read_saved_jobs(current_user.username)
        if idx is None or not (0 <= int(idx) < len(jobs)):
            return {"success": False, "message": "Invalid index"}, 400
        jobs.pop(int(idx))
        write_saved_jobs(jobs, current_user.username)
        return {"success": True, "saved_count": len(jobs)}
    except Exception as e:
        print("remove_saved error:", e)
        return {"success": False, "message": str(e)}, 500


if __name__ == "__main__":
    app.run(debug=True)
