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
login_manager.login_message = "Silakan login terlebih dahulu."
login_manager.login_message_category = "warning"

@login_manager.unauthorized_handler
def unauthorized():
    flash("Anda harus login terlebih dahulu.", "warning")
    return redirect(url_for('login'))

def get_db_connection():
    """Get PostgreSQL database connection for users"""
    try:
        conn = psycopg2.connect(DB_URL)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

def init_user_db():
    """Initialize PostgreSQL user database if not exists."""
    try:
        conn = get_db_connection()
        if not conn:
            print("[!] Could not connect to database. Using SQLite fallback.")
            return
        
        c = conn.cursor()
        
        # Users table
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'job_seeker',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        c.close()
        conn.close()
        print("[OK] PostgreSQL user database initialized successfully")
    except Exception as e:
        print(f"Database init error: {e}")

init_user_db()

# User model
class User(UserMixin):
    def __init__(self, id, username, email, role='job_seeker'):
        self.id = id
        self.username = username
        self.email = email
        self.role = role
    
    @property
    def is_active(self):
        return True
    
    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_anonymous(self):
        return False
    
    @staticmethod
    def get_by_username(username):
        try:
            conn = get_db_connection()
            if not conn:
                return None
            c = conn.cursor()
            c.execute('SELECT id, username, email, role FROM users WHERE username = %s', (username,))
            row = c.fetchone()
            c.close()
            conn.close()
            if row:
                return User(row[0], row[1], row[2], row[3] or 'job_seeker')
        except Exception as e:
            print('get_by_username error:', e)
        return None
    
    @staticmethod
    def get_by_id(user_id):
        try:
            conn = get_db_connection()
            if not conn:
                return None
            c = conn.cursor()
            c.execute('SELECT id, username, email, role FROM users WHERE id = %s', (user_id,))
            row = c.fetchone()
            c.close()
            conn.close()
            if row:
                return User(row[0], row[1], row[2], row[3] or 'job_seeker')
        except Exception as e:
            print('get_by_id error:', e)
        return None
    
    @staticmethod
    def check_password(username, password):
        try:
            conn = get_db_connection()
            if not conn:
                return False
            c = conn.cursor()
            c.execute('SELECT id, password FROM users WHERE username = %s', (username,))
            row = c.fetchone()
            c.close()
            conn.close()
            if row:
                try:
                    if check_password_hash(row[1], password):
                        return True
                except Exception as hash_err:
                    print(f'Password hash error: {hash_err}')
            return False
        except Exception as e:
            print('check_password error:', e)
            return False
    
    @staticmethod
    def register(username, email, password, role='job_seeker'):
        try:
            hashed_pwd = generate_password_hash(password)
            conn = get_db_connection()
            if not conn:
                print('register: connection failed')
                return False
            c = conn.cursor()
            c.execute('INSERT INTO users (username, email, password, role) VALUES (%s, %s, %s, %s)',
                     (username, email, hashed_pwd, role))
            conn.commit()
            c.close()
            conn.close()
            print(f'register: user {username} created successfully')
            return True
        except psycopg2.IntegrityError as ie:
            print(f'register: IntegrityError {ie}')
            return False
        except Exception as e:
            print(f'User.register error: {e}')
            import traceback
            traceback.print_exc()
            return False

@login_manager.user_loader
def load_user(user_id):
    try:
        user = User.get_by_id(int(user_id))
        if user is None:
            print(f"User {user_id} not found in database")
            return None
        return user
    except Exception as e:
        print(f"load_user error for user_id {user_id}: {e}")
        return None

@app.before_request
def before_request():
    """Ensure current_user is valid before processing request"""
    from flask_login import current_user
    if current_user and not current_user.is_authenticated:
        pass


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
    print(f"[OK] Graph loaded from {graph_file}")
    return G

# Pre-load embeddings at startup
print("[*] Initializing job embeddings (first run, may take 1-2 min)...")
try:
     from src.recommender_sentence import load_and_cache_embeddings
     G = load_graph()
     # Use force_refresh if needed (set to False for normal startup)
     FORCE_REFRESH_EMBEDDINGS = os.getenv("FORCE_REFRESH_EMBEDDINGS", "false").lower() == "true"
     load_and_cache_embeddings(G, DB_URL=DB_URL, force_refresh=FORCE_REFRESH_EMBEDDINGS)
     print("[OK] Job embeddings ready!")
except Exception as e:
     print(f"[!] Job embedding init error: {e}")


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
        if isinstance(data, list):
            if username:
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
# Routes
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
            if user:
                login_user(user)
                return redirect(url_for('landing'))
            else:
                flash("User not found. Please try again.", "error")
                return redirect(url_for('login'))
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
    """Job seeker searches for jobs using sentence matching."""
    error = None
    results = []
    matching_method = "none"

    # Get locations from graph data
    countries = []
    countries_cities = {}
    try:
        G = load_graph()
        cities_by_country = {}
        for node_id, data in G.nodes(data=True):
            if data.get('type') == 'job':
                city = data.get('search_city', '').strip()
                country = data.get('search_country', '').strip()
                
                if country:
                    if country not in cities_by_country:
                        cities_by_country[country] = set()
                    if city:
                        cities_by_country[country].add(city)
        
        countries = sorted(list(cities_by_country.keys()))
        countries_cities = {c: sorted(list(cities_by_country[c])) for c in cities_by_country}
        
        print(f"[OK] Loaded {len(countries)} countries and {sum(len(v) for v in countries_cities.values())} cities from graph")
    except Exception as e:
        print(f"Error loading graph for locations: {e}")
        countries = []
        countries_cities = {}
    
    selected_country = ""
    selected_city = ""
    skills_text = ""

    if request.method == "POST":
        skills_text = request.form.get("skills", "").strip()
        selected_country = request.form.get("country", "").strip()
        selected_city = request.form.get("city", "").strip()

        try:
            # Simple Sentence Matching
            if skills_text:
                matching_method = "sentence_matching"
                print(f"\n=== SEARCH REQUEST ===")
                print(f"Skills: {skills_text}")
                print(f"Country: {selected_country}")
                print(f"City: {selected_city}")
                
                # Load graph for job matching
                G = load_graph()
                
                t0 = time.time()
                print(f"\nCalling recommend_jobs_sentence...")
                results = recommend_jobs_sentence(
                    G,
                    skills_text,
                    top_n=12,
                    filter_country=selected_country,
                    filter_city=selected_city,
                    DB_URL=DB_URL
                )
                duration = time.time() - t0
                print(f"Results returned: {len(results)} jobs in {duration:.2f}s")
                
                # Log recommendation query
                try:
                    mp_vals = [r.get('match_percent') for r in results if r.get('match_percent') is not None]
                    avg_mp = round(sum(mp_vals) / len(mp_vals), 2) if mp_vals else None
                except Exception:
                    avg_mp = None

                # Extract top skills from query
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
                        'method': 'sentence_matching'
                    }, current_user.username)
                except Exception:
                    pass

                if not results:
                    error = f"No jobs matched your search. Try different keywords."
                else:
                    # Map results to template format
                    mapped_results = []
                    for result in results:
                        mapped_results.append({
                            'job_title': result.get('job_title', 'Unknown Job'),
                            'company': result.get('company', 'Unknown'),
                            'location': result.get('location', 'TBD'),
                            'job_type': result.get('job_type', 'Full-time'),
                            'match_percent': result.get('match_percent', 0),
                            'skills': result.get('skills', []),
                            'description': result.get('description', '')[:300] if result.get('description') else '',
                            'reason_text': result.get('reason_text', f"Matches {result.get('match_percent', 0)}% of your skills"),
                            'link': result.get('link', '#'),
                            'date': result.get('date', '')
                        })
                    
                    results = mapped_results
                    print(f"[OK] Found {len(results)} jobs using sentence matching in {duration:.2f}s")

            else:
                error = "Please enter skills."

        except Exception as e:
            print(f"Search error: {e}")
            import traceback
            traceback.print_exc()
            error = f"Error: {str(e)}"

    return render_template(
        "index.html",
        results=results,
        error=error,
        countries=countries,
        countries_cities=countries_cities,
        selected_country=selected_country,
        selected_city=selected_city,
        skills=skills_text
    )


@app.route("/save_job", methods=["POST"])
@login_required
def save_job():
    try:
        data = request.get_json(force=True)
        if not data:
            return {"success": False, "message": "No job data provided"}, 400

        jobs = read_saved_jobs(current_user.username)
        link = data.get("link")
        exists = False
        for j in jobs:
            if link and j.get("link") == link:
                exists = True
                break
            if (not link) and j.get("job_title") == data.get("job_title") and j.get("company") == data.get("company"):
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


@app.route("/saved_jobs", methods=["GET"])
@login_required
def saved_jobs():
    jobs = read_saved_jobs(current_user.username)
    return render_template("saved.html", saved=jobs)


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    stats = {}
    recommend_stats = {}
    recommend_recent = []
    jobs_per_country = {}
    top_skills = []
    recent_saved = []
    
    try:
        # Load graph for stats
        G = load_graph()
        
        # Count jobs per country and skills from graph edges
        jobs_per_country = {}
        top_skills_dict = {}
        
        for node_id, data in G.nodes(data=True):
            if data.get('type') == 'job':
                country = data.get('search_country', 'Unknown')
                jobs_per_country[country] = jobs_per_country.get(country, 0) + 1
                
                # Get skills connected to this job node
                successors = list(G.successors(node_id))
                for successor_id in successors:
                    succ_data = G.nodes.get(successor_id, {})
                    if succ_data.get('type') == 'skill':
                        skill_label = succ_data.get('label', successor_id)
                        top_skills_dict[skill_label] = top_skills_dict.get(skill_label, 0) + 1
        
        top_skills = sorted(top_skills_dict.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Get user's saved jobs
        recent_saved = read_saved_jobs(current_user.username)[-5:] if read_saved_jobs(current_user.username) else []
        
        # Get recommendation stats from logs
        reco_logs = read_reco_logs(current_user.username)
        if reco_logs:
            total_queries = len(reco_logs)
            match_percents = [r.get('avg_match_percent', 0) for r in reco_logs if r.get('avg_match_percent') is not None]
            avg_match = sum(match_percents) / len(match_percents) if match_percents else 0
            avg_results = sum(r.get('num_results', 0) for r in reco_logs) / len(reco_logs) if reco_logs else 0
            latencies = [r.get('duration', 0) for r in reco_logs]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0
            
            # Top queries
            query_counts = {}
            for r in reco_logs:
                q = r.get('query', 'Unknown')
                query_counts[q] = query_counts.get(q, 0) + 1
            top_queries = sorted(query_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            
            # Top skills from queries
            top_skills_queries = {}
            for r in reco_logs:
                for s in r.get('top_skills', []):
                    top_skills_queries[s] = top_skills_queries.get(s, 0) + 1
            top_skills_queries_list = sorted(top_skills_queries.items(), key=lambda x: x[1], reverse=True)[:5]
            
            # Match distribution buckets (0-20%, 20-40%, etc.)
            match_buckets = {'0-20%': 0, '20-40%': 0, '40-60%': 0, '60-80%': 0, '80-100%': 0}
            for mp in match_percents:
                if mp < 20:
                    match_buckets['0-20%'] += 1
                elif mp < 40:
                    match_buckets['20-40%'] += 1
                elif mp < 60:
                    match_buckets['40-60%'] += 1
                elif mp < 80:
                    match_buckets['60-80%'] += 1
                else:
                    match_buckets['80-100%'] += 1
            
            # 30-day timeseries
            from datetime import datetime, timedelta
            now = datetime.now()
            thirty_days_ago = now - timedelta(days=30)
            daily_matches = {}
            
            for r in reco_logs:
                ts = r.get('ts', 0)
                if ts:
                    date = datetime.fromtimestamp(ts).date()
                    if date >= thirty_days_ago.date():
                        if str(date) not in daily_matches:
                            daily_matches[str(date)] = []
                        mp = r.get('avg_match_percent', 0)
                        if mp is not None:
                            daily_matches[str(date)].append(mp)
            
            # Average match per day
            timeseries_labels = []
            timeseries_values = []
            for date in sorted(daily_matches.keys()):
                timeseries_labels.append(date)
                avg = sum(daily_matches[date]) / len(daily_matches[date])
                timeseries_values.append(round(avg, 1))
            
            # Latency percentiles
            if latencies:
                sorted_latencies = sorted(latencies)
                p50_idx = len(sorted_latencies) // 2
                p90_idx = int(len(sorted_latencies) * 0.9)
                p99_idx = int(len(sorted_latencies) * 0.99)
                latency_p50 = round(sorted_latencies[p50_idx] * 1000, 0)  # convert to ms
                latency_p90 = round(sorted_latencies[min(p90_idx, len(sorted_latencies)-1)] * 1000, 0)
                latency_p99 = round(sorted_latencies[min(p99_idx, len(sorted_latencies)-1)] * 1000, 0)
            else:
                latency_p50 = latency_p90 = latency_p99 = '-'
            
            recommend_stats = {
                'total_queries': total_queries,
                'avg_match_percent': round(avg_match, 1),
                'avg_results': round(avg_results),
                'avg_latency': round(avg_latency, 3),
                'top_queries': top_queries,
                'top_skills_queries': top_skills_queries_list,
                'match_buckets': match_buckets,
                'timeseries': {'labels': timeseries_labels, 'values': timeseries_values},
                'latency_p50': latency_p50,
                'latency_p90': latency_p90,
                'latency_p99': latency_p99
            }
            
            recommend_recent = sorted(reco_logs, key=lambda x: x.get('ts', 0), reverse=True)[:5]
        
        # Basic stats
        stats = {
            'total_jobs': len([n for n, d in G.nodes(data=True) if d.get('type') == 'job']),
            'countries': len(jobs_per_country),
            'saved_jobs': len(recent_saved)
        }
        
    except Exception as e:
        print(f"Dashboard stats error: {e}")
    
    return render_template(
        "dashboard.html",
        stats=stats,
        recommend_stats=recommend_stats,
        recommend_recent=recommend_recent,
        jobs_per_country=jobs_per_country,
        top_skills=top_skills,
        recent_saved=recent_saved
    )


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
