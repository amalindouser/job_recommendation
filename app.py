from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify
import os
import pandas as pd
import psycopg2
import psycopg2.extras
import sqlite3
import networkx as nx
from src.recommender_sentence import recommend_jobs_sentence
from src.employer_routes import employer_bp
from src.decorators import job_seeker_required, employer_required
from dotenv import load_dotenv
import time
import functools
import json
from pathlib import Path
import re
from dotenv import load_dotenv


from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


load_dotenv()


# ==========================
# App Init & Config
# ==========================
app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-prod')
DB_URL = os.getenv("DB_URL")
if DB_URL and DB_URL.strip():
    conn = psycopg2.connect(DB_URL, sslmode='require')
else:
    conn = None

# Register Employer Blueprint
app.register_blueprint(employer_bp)

# Determine database type
USE_SQLITE = not DB_URL or DB_URL.strip() == ""
SQLITE_DB_PATH = Path(os.path.dirname(__file__)) / "database" / "users.db"

if USE_SQLITE:
    print("[*] Using SQLite for user database")
    # Ensure database directory exists
    SQLITE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
    print("[*] Using PostgreSQL for user database")

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
    if USE_SQLITE:
        try:
            conn = sqlite3.connect(str(SQLITE_DB_PATH))
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            print(f"SQLite connection error: {e}")
            return None
    else:
        try:
            conn = psycopg2.connect(DB_URL)
            return conn
        except Exception as e:
            print(f"PostgreSQL connection error: {e}")
            return None


def init_user_db():
    """Initialize user database (PostgreSQL or SQLite)."""
    try:
        conn = get_db_connection()
        if not conn:
            print("[!] Could not connect to database.")
            return
        
        c = conn.cursor()
        
        if USE_SQLITE:
            # SQLite table structure
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT DEFAULT 'job_seeker',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        else:
            # PostgreSQL table structure
            c.execute('CREATE SCHEMA IF NOT EXISTS app')
            c.execute('''
                CREATE TABLE IF NOT EXISTS app.users (
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
        db_type = "SQLite" if USE_SQLITE else "PostgreSQL"
        print(f"[OK] {db_type} user database initialized successfully")
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
            if USE_SQLITE:
                c.execute('SELECT id, username, email, role FROM users WHERE username = ?', (username,))
            else:
                c.execute('SELECT id, username, email, role FROM app.users WHERE username = %s', (username,))
            row = c.fetchone()
            c.close()
            conn.close()
            if row:
                if USE_SQLITE:
                    return User(row[0], row[1], row[2], row[3] or 'job_seeker')
                else:
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
            if USE_SQLITE:
                c.execute('SELECT id, username, email, role FROM users WHERE id = ?', (user_id,))
            else:
                c.execute('SELECT id, username, email, role FROM app.users WHERE id = %s', (user_id,))
            row = c.fetchone()
            c.close()
            conn.close()
            if row:
                if USE_SQLITE:
                    return User(row[0], row[1], row[2], row[3] or 'job_seeker')
                else:
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
            if USE_SQLITE:
                c.execute('SELECT id, password FROM users WHERE username = ?', (username,))
            else:
                c.execute('SELECT id, password FROM app.users WHERE username = %s', (username,))
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
            if USE_SQLITE:
                c.execute('INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)',
                         (username, email, hashed_pwd, role))
            else:
                c.execute('INSERT INTO app.users (username, email, password, role) VALUES (%s, %s, %s, %s)',
                         (username, email, hashed_pwd, role))
            conn.commit()
            c.close()
            conn.close()
            print(f'register: user {username} created successfully')
            return True
        except (psycopg2.IntegrityError if not USE_SQLITE else sqlite3.IntegrityError) as ie:
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
    recommend_path = os.path.join(base_dir, "data", "graph_recommend.graphml")
    clean_path = os.path.join(base_dir, "data", "graph_jobs_clean.graphml")
    default_path = os.path.join(base_dir, "data", "graph_jobs.graphml")

    if os.path.exists(recommend_path):
        graph_file = recommend_path
    elif os.path.exists(clean_path):
        graph_file = clean_path
    elif os.path.exists(default_path):
        graph_file = default_path
    else:
        raise FileNotFoundError("No graph file found (data/graph_recommend.graphml or data/graph_jobs_clean.graphml or data/graph_jobs.graphml)")

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

# Initialize all DB tables
print("[*] Initializing database tables...")
try:
    from src.db_service import init_all_tables
    init_all_tables()
    print("[OK] Database tables ready!")
except Exception as e:
    print(f"[!] DB table init error: {e}")


# ==========================
# Saved jobs helpers (per-user) — DB first, JSON fallback
# ==========================
SAVED_PATH = Path(os.path.dirname(__file__)) / "database" / "saved_jobs.json"
RECO_LOG_PATH = Path(os.path.dirname(__file__)) / "database" / "recommendation_logs.json"

from src.db_service import (
    get_saved_jobs_db, save_job_db, remove_saved_job_db, clear_saved_jobs_db,
)


def _ensure_user_structure():
    pass


def read_saved_jobs(username=None):
    """Read saved jobs — DB first, JSON fallback."""
    if username:
        db_jobs = get_saved_jobs_db(username)
        if db_jobs is not None:
            return db_jobs
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
    """Write saved jobs — DB first, JSON fallback."""
    clear_saved_jobs_db(username)
    for job in jobs:
        save_job_db(username, job)
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
    """Read recommendation logs — DB first, JSON fallback."""
    if username:
        db_logs = get_reco_logs_db(username)
        if db_logs is not None:
            return db_logs
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
    """Append a recommendation log — DB first, JSON fallback."""
    if append_reco_log_db(username, entry):
        return True
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
        role = request.form.get("role", "job_seeker").strip()
        
        if role not in ("job_seeker", "employer"):
            role = "job_seeker"
        
        if not username or not email or not password:
            flash("Semua bidang harus diisi.", "error")
            return redirect(url_for('register'))
        
        if password != password_confirm:
            flash("Kata sandi tidak cocok.", "error")
            return redirect(url_for('register'))
        
        if len(password) < 6:
            flash("Kata sandi minimal 6 karakter.", "error")
            return redirect(url_for('register'))
        
        if User.register(username, email, password, role):
            flash("Pendaftaran berhasil! Silakan masuk.", "success")
            return redirect(url_for('login'))
        else:
            flash("Nama pengguna atau email sudah ada.", "error")
            return redirect(url_for('register'))
    
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if not username or not password:
            flash("Nama pengguna dan kata sandi diperlukan.", "error")
            return redirect(url_for('login'))
        
        if User.check_password(username, password):
            user = User.get_by_username(username)
            if user:
                login_user(user)
                if user.role == 'employer':
                    return redirect(url_for('employer.dashboard'))
                return redirect(url_for('jobs'))
            else:
                flash("Pengguna tidak ditemukan. Coba lagi.", "error")
                return redirect(url_for('login'))
        else:
            flash("Nama pengguna atau kata sandi salah.", "error")
            return redirect(url_for('login'))
    
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Berhasil keluar.", "success")
    return redirect(url_for('landing'))


@app.route("/search", methods=["GET", "POST"])
@login_required
@job_seeker_required
def search_redirect():
    if request.method == "POST":
        skills_text = request.form.get("skills", "").strip()
        if skills_text:
            return redirect(url_for("jobs", q=skills_text))
    return redirect(url_for("jobs"))


@app.route("/save_job", methods=["POST"])
@login_required
@job_seeker_required
def save_job():
    try:
        data = request.get_json(force=True)
        if not data:
            return {"success": False, "message": "No job data provided"}, 400

        jobs = read_saved_jobs(current_user.username)
        link = data.get("link")
        exists = False
        def _norm(v):
            return (v or "").strip().lower()
        for j in jobs:
            if link and j.get("link") == link:
                exists = True
                break
            if (_norm(j.get("job_title")) == _norm(data.get("job_title"))
                    and _norm(j.get("company")) == _norm(data.get("company"))):
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
@job_seeker_required
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


@app.route("/track_feedback", methods=["POST"])
@login_required
@job_seeker_required
def track_feedback():
    """Track user interaction with job recommendations — DB first, JSON fallback."""
    try:
        data = request.get_json(force=True)
        if not data:
            return {"success": False}, 400

        feedback_entry = {
            'ts': time.time(),
            'username': current_user.username,
            'action': data.get('action', 'click'),
            'job_title': data.get('job_title', ''),
            'company': data.get('company', ''),
            'link': data.get('link', ''),
            'match_percent': data.get('match_percent'),
        }

        if not append_feedback_log_db(feedback_entry):
            feedback_path = Path(os.path.dirname(__file__)) / "database" / "feedback_logs.json"
            if not feedback_path.exists():
                feedback_path.write_text(json.dumps([], ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                logs = json.loads(feedback_path.read_text(encoding="utf-8"))
            except Exception:
                logs = []
            logs.append(feedback_entry)
            feedback_path.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")

        return {"success": True}
    except Exception as e:
        print("track_feedback error:", e)
        return {"success": False, "message": str(e)}, 500


@app.route("/saved")
@login_required
@job_seeker_required
def saved_jobs_old_alias():
    return redirect(url_for("saved_jobs"))


@app.route("/saved_jobs", methods=["GET"])
@login_required
@job_seeker_required
def saved_jobs():
    from src.clean_skills import categorize_skills, is_stop_skill, SKILL_NORMALIZE
    jobs = read_saved_jobs(current_user.username)

    def _parse_skills(val):
        if isinstance(val, list):
            return [str(s) for s in val]
        if isinstance(val, dict):
            out = []
            for v in val.values():
                if isinstance(v, list):
                    out.extend(str(s) for s in v)
                else:
                    out.append(str(v))
            return out
        if isinstance(val, str):
            s = val.strip()
            if not s:
                return []
            try:
                parsed = json.loads(s)
            except Exception:
                toks = [t.strip("{}[]\"' \t\n") for t in re.split(r"[,;\n]", s)]
                return [t for t in toks if t]
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
            if isinstance(parsed, dict):
                out = []
                for v in parsed.values():
                    if isinstance(v, list):
                        out.extend(str(x) for x in v)
                    else:
                        out.append(str(v))
                return out
            return [str(parsed)]
        return []

    for job in jobs:
        raw = _parse_skills(job.get("skills", []))
        cleaned = []
        seen = set()
        for s in raw:
            key = s.strip().lower()
            norm = SKILL_NORMALIZE.get(key, key)
            if norm in seen or is_stop_skill(norm):
                continue
            seen.add(norm)
            cleaned.append(norm)
        job["skills"] = cleaned
        job["categorized_skills"] = categorize_skills(cleaned)

    # Look up company logos by company name
    try:
        from src.db_service import get_connection
        conn = get_connection()
        if conn:
            c = conn.cursor()
            company_names = [j.get("company", "") for j in jobs if j.get("company")]
            if company_names:
                placeholders = ",".join(["%s"] * len(company_names))
                c.execute(f"SELECT name, logo_url FROM app.companies WHERE LOWER(name) IN ({placeholders})",
                          [n.lower() for n in company_names])
                logo_map = {}
                for row in c.fetchall():
                    logo_map[row[0].lower()] = row[1]
                for job in jobs:
                    company = job.get("company", "")
                    if company:
                        job["logo_url"] = logo_map.get(company.lower())
            c.close()
            conn.close()
    except Exception as e:
        print(f"[!] Logo lookup for saved jobs error: {e}")

    return render_template("saved.html", saved=jobs)


# Redirect old /browse to /jobs
@app.route("/browse", methods=["GET"])
def browse_redirect():
    q = request.args.get("q", "")
    cat = request.args.get("cat", "")
    dst = url_for("jobs")
    params = []
    if q:
        params.append(f"q={q}")
    if cat:
        params.append(f"cat={cat}")
    if params:
        dst += "?" + "&".join(params)
    return redirect(dst)


# ==========================
# Unified Jobs Page
# ==========================

# Known skills set built once for title/description skill extraction
_KNOWN_SKILLS_CACHE = None
def _build_known_skills():
    global _KNOWN_SKILLS_CACHE
    if _KNOWN_SKILLS_CACHE is None:
        from src.clean_skills import SKILL_NORMALIZE, SKILL_CATEGORIES
        s = set()
        for cat, skills in SKILL_CATEGORIES.items():
            for sk in skills:
                s.add(sk.lower().strip())
        for k in SKILL_NORMALIZE:
            s.add(k.lower().strip())
        _KNOWN_SKILLS_CACHE = s
    return _KNOWN_SKILLS_CACHE

def _extract_skills_from_job(job):
    """Augment job skills by extracting tech keywords from title + description."""
    from src.clean_skills import is_stop_skill
    known = _build_known_skills()
    existing = set(s.lower() for s in (job.get("skills") or []))
    extracted = set()

    text = ((job.get("job_title") or "") + " " + (job.get("description") or "")).lower()

    # Whole-word match saja. Substring match menghasilkan false positive:
    # "gin" di "engineering", "api" di "rapid", "law" di "lawencon".
    for skill in known:
        sk = skill.lower().strip()
        if len(sk) < 3 or is_stop_skill(sk):
            continue
        if re.search(r"\b" + re.escape(sk) + r"\b", text):
            extracted.add(sk)

    merged = list(existing | extracted)
    return merged

LOCATIONS = [
    ("Jakarta", "jakarta"),
    ("Tangerang", "tangerang"),
    ("Bekasi", "bekasi"),
    ("Depok", "depok"),
    ("Bogor", "bogor"),
    ("Bandung", "bandung"),
    ("Cikarang", "cikarang"),
    ("Surabaya", "surabaya"),
    ("Yogyakarta", "yogyakarta"),
    ("Semarang", "semarang"),
    ("Malang", "malang"),
    ("Medan", "medan"),
    ("Makassar", "makassar"),
    ("Batam", "batam"),
    ("Pekanbaru", "pekanbaru"),
    ("Palembang", "palembang"),
    ("Balikpapan", "balikpapan"),
    ("Bali", "bali"),
    ("Denpasar", "denpasar"),
]

@app.route("/api/job_title_suggestions")
@login_required
@job_seeker_required
def job_title_suggestions():
    from src.clean_jobs_service import suggest_job_titles
    term = request.args.get("q", "").strip()
    limit = min(max(int(request.args.get("limit", 10)), 1), 20)
    titles = suggest_job_titles(term, limit)
    return jsonify({"titles": titles, "term": term})


@app.route("/jobs", methods=["GET", "POST"])
@login_required
@job_seeker_required
def jobs():
    from src.clean_jobs_service import search_clean_jobs, get_all_categories, get_location_variants
    from src.db_service import get_profile_by_user_id
    from src.employer_service import list_vacancies as get_emp_vacs
    from src.clean_skills import categorize_skills, is_stop_skill, SKILL_NORMALIZE
    from src.recommender_sentence import fuzzy_correct_query, _preprocess_query

    q = request.args.get("q", "")
    cat = request.args.get("cat", "")
    loc = request.args.get("loc", "")
    page = request.args.get("page", 1, type=int)
    skills_text = request.form.get("skills", "").strip()

    # Normalize compound terms (node js → node.js)
    if q:
        q = _preprocess_query(q)
    if skills_text:
        skills_text = _preprocess_query(skills_text)

    # Fuzzy-correct misspellings in search query
    if q:
        corrected = fuzzy_correct_query(q)
        if corrected != q:
            print(f"[*] Spell corrected query: '{q}' -> '{corrected}'")
        q = corrected
    if skills_text:
        corrected = fuzzy_correct_query(skills_text)
        if corrected != skills_text:
            print(f"[*] Spell corrected skills_text: '{skills_text}' -> '{corrected}'")
        skills_text = corrected

    # User skills
    user_skills = set()
    profile = get_profile_by_user_id(int(current_user.id))
    if profile and profile.get("skills"):
        user_skills = set(s.lower().strip() for s in profile["skills"] if s)

    # CSV jobs
    csv_result = search_clean_jobs(query=q, category=cat, location=loc, page=page, per_page=18, user_skills=user_skills)
    csv_start = (page - 1) * 18
    for i, j in enumerate(csv_result["results"]):
        j["_index"] = csv_start + i

    # Employer vacancies
    emp_vacs = get_emp_vacs(search=q)
    if loc:
        loc_variants = get_location_variants(loc)
        if loc_variants:
            emp_vacs = [
                v for v in emp_vacs
                if str(v.get("location", "")).lower() in loc_variants
            ]
    company_logos = {}
    try:
        from src.db_service import get_connection
        conn = get_connection()
        if conn:
            c = conn.cursor()
            c.execute("SELECT user_id, logo_url FROM app.companies WHERE logo_url IS NOT NULL AND logo_url != ''")
            for row in c.fetchall():
                company_logos[row[0]] = row[1]
            c.close()
            conn.close()
    except Exception as e:
        print(f"[!] Batch logo lookup error: {e}")

    # Hydrate lowongan CSV dengan kembar employer-nya di app.vacancies,
    # supaya kartu mengarah ke detail vacancy (bisa melamar) bukan link eksternal
    emp_twin = {}
    csv_keys = []
    for _j in csv_result["results"]:
        _t = (_j.get("job_title") or "").strip().lower()
        _c = (_j.get("company") or "").strip().lower()
        if _t and _c:
            csv_keys.append((_t, _c))
    try:
        from src.db_service import get_connection as _pgc
        _conn = _pgc()
        if _conn and csv_keys:
            _cur = _conn.cursor()
            clauses = []
            params = []
            for _t, _c in csv_keys:
                clauses.append("(LOWER(job_title) = %s AND LOWER(company) = %s)")
                params.extend([_t, _c])
            _cur.execute(
                "SELECT id, job_title, company, description, skills, job_type, location, "
                "created_at, salary_min, salary_max, user_id FROM app.vacancies WHERE "
                + " OR ".join(clauses) + " LIMIT 500",
                params,
            )
            for _row in _cur.fetchall():
                emp_twin[(_row[1].strip().lower(), _row[2].strip().lower())] = _row
            _cur.close()
            _conn.close()
    except Exception as e:
        print(f"[!] Employer twin lookup error: {e}")

    for v in emp_vacs:
        raw = v.get("skills", [])
        if isinstance(raw, str):
            raw = [s.strip() for s in raw.split(",") if s.strip()]
        cleaned = []
        seen = set()
        for s in raw:
            key = s.strip().lower()
            norm = SKILL_NORMALIZE.get(key, key)
            if norm in seen or is_stop_skill(norm):
                continue
            seen.add(norm)
            cleaned.append(norm)
        v["categorized_skills"] = categorize_skills(cleaned)
        v["skills"] = cleaned
        if user_skills and cleaned:
            overlap = len(user_skills & set(s.lower() for s in cleaned))
            v["match_score"] = round(overlap / max(len(user_skills | set(s.lower() for s in cleaned)), 1) * 100)
        else:
            v["match_score"] = 0
        v["_employer"] = True
        v["logo_url"] = company_logos.get(v.get("user_id"))

    # Filter employer vacancies by selected category (penting saat cari
    # kategori tanpa teks query, supaya daftarnya relevan bukan semua lowongan)
    if cat:
        _cat_key = cat.lower().strip()
        emp_vacs = [
            v for v in emp_vacs
            if _cat_key in {str(k).lower() for k in (v.get("categorized_skills") or {})}
        ]

    # Merge employer vacancies + CSV jobs into single unified list
    all_jobs = []
    for v in emp_vacs:
        all_jobs.append({
            'job_title': v.get('job_title', ''),
            'company': v.get('company', ''),
            'location': v.get('location', ''),
            'job_type': v.get('job_type', ''),
            'match_score': v.get('match_score', 0),
            'skills': v.get('skills', []),
            'categorized_skills': v.get('categorized_skills', {}),
            'description': v.get('description', '') or '',
            'date': v.get('created_at', '')[:10],
            'salary_min': v.get('salary_min'),
            'salary_max': v.get('salary_max'),
            'logo_url': v.get('logo_url'),
            '_source': 'employer',
            '_id': v.get('id'),
        })
    for j in csv_result["results"]:
        key = ((j.get("job_title") or "").strip().lower(), (j.get("company") or "").strip().lower())
        twin = emp_twin.get(key)
        if twin:
            twin_skills = twin[4] or []
            if isinstance(twin_skills, str):
                twin_skills = [s.strip() for s in twin_skills.strip("{}").split(",") if s.strip()]
            _seen = set()
            _cleaned = []
            for _s in twin_skills:
                _k = str(_s).strip().lower()
                _norm = SKILL_NORMALIZE.get(_k, _k)
                if _norm in _seen or is_stop_skill(_norm):
                    continue
                _seen.add(_norm)
                _cleaned.append(_norm)
            all_jobs.append({
                'job_title': twin[1],
                'company': twin[2],
                'location': twin[6] or '',
                'job_type': twin[5] or '',
                'match_score': j.get('match_score', 0),
                'skills': _cleaned,
                'categorized_skills': categorize_skills(_cleaned),
                'description': twin[3] or '',
                'date': (str(twin[7])[:10]) if twin[7] else '',
                'salary_min': twin[8] or '',
                'salary_max': twin[9] or '',
                'logo_url': company_logos.get(twin[10]),
                '_source': 'employer',
                '_id': twin[0],
                'job_url': j.get('job_url', ''),
            })
        else:
            _csv_skills = j.get('skills', [])
            if isinstance(_csv_skills, str):
                _csv_skills = [s.strip() for s in _csv_skills.split(",") if s.strip()]
            _seen = set()
            _cleaned = []
            for _s in _csv_skills:
                _k = str(_s).strip().lower()
                _norm = SKILL_NORMALIZE.get(_k, _k)
                if _norm in _seen or is_stop_skill(_norm):
                    continue
                _seen.add(_norm)
                _cleaned.append(_norm)
            all_jobs.append({
                'job_title': j.get('job_title', ''),
                'company': j.get('company', ''),
                'location': j.get('location', ''),
                'job_type': j.get('employment', ''),
                'match_score': j.get('match_score', 0),
                'skills': _cleaned,
                'categorized_skills': categorize_skills(_cleaned),
                'description': j.get('description', '') or '',
                'date': j.get('posted_at', '')[:10],
                'salary_min': j.get('salary_min'),
                'salary_max': j.get('salary_max'),
                '_source': 'csv',
                '_index': j.get('id'),
                'job_url': j.get('job_url', ''),
            })
    
    # Augment poor skills with tech keywords from title + description
    for job in all_jobs:
        raw_skills = job.get("skills") or []
        if isinstance(raw_skills, str):
            raw_skills = [s.strip() for s in raw_skills.split(",") if s.strip()]
        if len(raw_skills) <= 2:
            augmented = _extract_skills_from_job(job)
            if len(augmented) > len(raw_skills):
                job["skills"] = augmented
                job["categorized_skills"] = categorize_skills(augmented)

    # Re-score all jobs: query relevance + Jaccard skill similarity
    _query_for_score = skills_text or q
    query_words = set(_query_for_score.lower().split()) if _query_for_score else set()
    for job in all_jobs:
        raw = job.get("skills", [])
        if isinstance(raw, str):
            raw = [s.strip() for s in raw.split(",") if s.strip()]
        job_skills = set(s.lower() for s in raw)

        # 1) Query relevance: fraction of query words found in title, skills, or description
        query_score = 0
        if query_words and (job.get("job_title") or job_skills or job.get("description")):
            text = " ".join([
                job.get("job_title") or "",
                " ".join(job_skills),
                job.get("description") or ""
            ]).lower()
            matches = sum(1 for w in query_words if len(w) > 1 and w in text)
            query_score = matches / max(len(query_words), 1)

        # 2) Jaccard similarity with user profile skills
        skill_score = 0
        if user_skills and job_skills:
            overlap = len(user_skills & job_skills)
            union = len(user_skills | job_skills)
            skill_score = overlap / max(union, 1)

        # Combine: query relevance dominates when search is active
        if _query_for_score:
            job["match_score"] = round((0.7 * query_score + 0.3 * skill_score) * 100)
        else:
            job["match_score"] = round(skill_score * 100)

    # Tanpa query aktif, jangan buang semua job (skor 0) — tampilkan apa adanya
    if _query_for_score:
        all_jobs = [j for j in all_jobs if j["match_score"] >= 6]
    else:
        all_jobs.sort(key=lambda x: (x.get("date") or ""), reverse=True)

    # Deduplicate by title + company, keep highest score then latest date
    seen = {}
    for job in all_jobs:
        key = (job["job_title"].lower().strip(), job["company"].lower().strip())
        existing = seen.get(key)
        if existing:
            # prefer salinan employer (bisa dilamar di aplikasi)
            if job["_source"] == "employer" and existing["_source"] != "employer":
                seen[key] = job
            elif job["_source"] != "employer" and existing["_source"] == "employer":
                pass
            elif job["match_score"] > existing["match_score"] or \
                 (job["match_score"] == existing["match_score"] and (job.get("date") or "") > (existing.get("date") or "")):
                seen[key] = job
        else:
            seen[key] = job
    all_jobs = list(seen.values())

    all_jobs.sort(key=lambda x: (-x['match_score'], (x.get('date') or ''), x.get('job_title', '') or ''))

    # Recommendation engine: runs for ALL queries, supplements text search.
    # Saat user hanya memilih kategori/lokasi tanpa teks, pakai kategori sebagai query rekomendasi.
    reco_results = []
    reco_query = skills_text or q or cat
    if reco_query:
        try:
            G = load_graph()
            results = recommend_jobs_sentence(
                G, reco_query, top_n=40 if loc else 12,
                DB_URL=DB_URL, username=current_user.username,
                use_cross_encoder=False, use_kg_enhanced=False,
                alpha=0.8, beta=0.25,
            )
            for r in results:
                raw = r.get('skills', [])
                if isinstance(raw, str):
                    raw = [s.strip() for s in raw.split(",") if s.strip()]
                cleaned = []
                seen = set()
                for s in raw:
                    key = s.strip().lower()
                    norm = SKILL_NORMALIZE.get(key, key)
                    if norm in seen or is_stop_skill(norm):
                        continue
                    seen.add(norm)
                    cleaned.append(norm)
                reco_results.append({
                    'job_title': r.get('job_title', 'Unknown Job'),
                    'company': r.get('company', 'Unknown'),
                    'location': r.get('location', 'TBD'),
                    'job_type': r.get('job_type', 'Full-time'),
                    'match_percent': r.get('match_percent', 0),
                    'skills': cleaned,
                    'categorized_skills': categorize_skills(cleaned),
                    'description': (r.get('description', '') or '')[:300],
                    'reason_text': r.get('reason_text', ''),
                    'link': r.get('link', '#'),
                    'date': r.get('date', ''),
                    '_reco': True,
                })
        except Exception as e:
            print(f"[!] Reco error: {e}")

    if loc and reco_results:
        _region = loc.lower().strip()
        if _region:
            # Lokasi hasil rekomendasi ternormalisasi ("Jakarta Selatan, Indonesia").
            # Cocokkan: region (mis. "jakarta", "bandung") harus muncul sebagai
            # whole word di string lokasi job — bukan exact match terhadap variants
            # mentah berantai yang formatnya beda.
            _loc_pat = re.compile(
                r"(^|[\s,])" + re.escape(_region) + r"($|[\s,])"
            )
            reco_results = [
                r for r in reco_results
                if _loc_pat.search((r.get("location") or "").lower())
            ]

    # Post-filter reco_results: keep only if a query word appears as whole word in title/skills
    # or has a decent semantic score (multilingual model handles non-english queries)
    if reco_results and reco_query:
        q_words = set(w for w in reco_query.lower().split() if len(w) > 1)
        filtered = []
        for r in reco_results:
            title = r.get("job_title", "").lower()
            skills = r.get("skills", [])
            words = set(title.split() + " ".join(skills).lower().split())
            has_match = any(w in words for w in q_words)
            score = r.get("match_percent", 0)
            if has_match or score >= 45:
                filtered.append(r)
        if filtered:
            reco_results = filtered

    # Arahkan kartu rekomendasi ke detail vacancy internal (bisa dilamar)
    # jika lowongan tersebut sudah terimpor sebagai employer vacancy
    if reco_results:
        try:
            from src.db_service import get_connection as _pgc3
            _conn = _pgc3()
            if _conn:
                _cur = _conn.cursor()
                _keys = []
                for _r in reco_results:
                    _t = (_r.get("job_title") or "").strip().lower()
                    _c = (_r.get("company") or "").strip().lower()
                    if _t and _c:
                        _keys.append((_t, _c))
                if _keys:
                    clauses = ["(LOWER(job_title) = %s AND LOWER(company) = %s)"] * len(_keys)
                    params = []
                    for _t, _c in _keys:
                        params.extend([_t, _c])
                    _cur.execute(
                        "SELECT id, LOWER(job_title), LOWER(company) FROM app.vacancies WHERE "
                        + " OR ".join(clauses) + " LIMIT 500",
                        params,
                    )
                    _link_map = {(_row[1], _row[2]): _row[0] for _row in _cur.fetchall()}
                    for _r in reco_results:
                        _k = ((_r.get("job_title") or "").strip().lower(),
                              (_r.get("company") or "").strip().lower())
                        if _k in _link_map:
                            _r["link"] = "/vacancies/" + _link_map[_k]
                _cur.close()
                _conn.close()
        except Exception as e:
            print(f"[!] Reco link hydration error: {e}")

    categories = get_all_categories()

    return render_template("jobs.html",
                           reco_results=reco_results,
                           reco_query=reco_query,
                           all_jobs=all_jobs,
                           csv_total=csv_result["total"],
                           csv_page=csv_result["page"],
                           csv_pages=csv_result["pages"],
                           query=q,
                           selected_cat=cat,
                           selected_loc=loc,
                           locations=LOCATIONS,
                           categories=categories,
                           user_skills=list(user_skills))


# ==========================
# Clean Job Detail
# ==========================

@app.route("/clean-job/<int:job_index>", methods=["GET"])
@login_required
@job_seeker_required
def clean_job_detail(job_index):
    from src.clean_jobs_service import get_clean_job_by_index
    from src.clean_skills import categorize_skills, is_stop_skill, SKILL_NORMALIZE
    from src.db_service import get_profile_by_user_id

    job = get_clean_job_by_index(job_index)
    if job is None:
        abort(404)

    # User skills for match score
    user_skills = set()
    profile = get_profile_by_user_id(int(current_user.id))
    if profile and profile.get("skills"):
        user_skills = set(s.lower().strip() for s in profile["skills"] if s)

    # Re-categorize skills (clean_jobs.jsonl may have old categories)
    raw = job.get("skills", [])
    cleaned = []
    seen = set()
    for s in raw:
        key = s.strip().lower()
        norm = SKILL_NORMALIZE.get(key, key)
        if norm in seen or is_stop_skill(norm):
            continue
        seen.add(norm)
        cleaned.append(norm)
    job["categorized_skills"] = categorize_skills(cleaned)
    job["skills"] = cleaned

    # Match score (Jaccard similarity)
    if user_skills and cleaned:
        cleaned_set = set(s.lower() for s in cleaned)
        overlap = len(user_skills & cleaned_set)
        union = len(user_skills | cleaned_set)
        match_score = round(overlap / max(union, 1) * 100)
    else:
        match_score = 0

    return render_template("clean_job_detail.html",
                           job=job,
                           job_index=job_index,
                           match_score=match_score,
                           user_skills=list(user_skills))


# Application System
# ==========================

@app.route("/vacancies", methods=["GET"])
@login_required
@job_seeker_required
def list_vacancies():
    return redirect(url_for("jobs"))



@app.route("/vacancies/<vacancy_id>", methods=["GET"])
@login_required
@job_seeker_required
def vacancy_detail(vacancy_id):
    from src.employer_service import get_vacancy
    from src.application_service import get_applications_for_vacancy, get_applications_for_user
    from src.db_service import get_profile_by_user_id
    from src.clean_skills import categorize_skills, is_stop_skill, SKILL_NORMALIZE
    v = get_vacancy(vacancy_id)
    if not v:
        flash("Lowongan tidak ditemukan.", "error")
        return redirect(url_for("list_vacancies"))
    # Add categorized skills (cleaned first)
    if "categorized_skills" not in v:
        raw = v.get("skills", [])
        if isinstance(raw, str):
            raw = [s.strip() for s in raw.split(",") if s.strip()]
        cleaned = []
        seen = set()
        for s in raw:
            key = s.strip().lower()
            norm = SKILL_NORMALIZE.get(key, key)
            if norm in seen or is_stop_skill(norm):
                continue
            seen.add(norm)
            cleaned.append(norm)
        v["categorized_skills"] = categorize_skills(cleaned)
    has_applied = any(
        a["user_id"] == str(current_user.id) and a["vacancy_id"] == vacancy_id
        for a in get_applications_for_user(str(current_user.id))
    )

    profile = get_profile_by_user_id(int(current_user.id))

    match_score = None
    if profile and profile.get("skills"):
        vac_skills = set()
        raw = v.get("skills", [])
        if isinstance(raw, str):
            vac_skills = {s.strip().lower() for s in raw.split(",") if s.strip()}
        else:
            vac_skills = {s.strip().lower() if isinstance(s, str) else str(s).lower() for s in raw if s}

        user_skills = {s.lower() for s in profile["skills"] if s}
        if vac_skills:
            overlap = user_skills & vac_skills
            union = user_skills | vac_skills
            match_score = round(len(overlap) / max(len(union), 1) * 100)

    similar_jobs = []
    try:
        from src.graph_enricher import load_enriched_graph
        from src.employer_graph_service import find_similar_jobs_by_title
        G = load_enriched_graph()
        sim = find_similar_jobs_by_title(v.get("job_title", ""), G, top_n=6)
        similar_jobs = [{
            "job_title": s.get("job_title", ""),
            "company": s.get("company", ""),
            "skills": s.get("skills", [])[:5],
            "id": f"hist_{s.get('node_id', '')}" if s.get("node_id") else None,
        } for s in sim if s.get("job_title", "").lower() != v.get("job_title", "").lower()]
    except Exception as e:
        print(f"[!] Similar jobs error: {e}")

    # Look up company logo from DB
    company_logo = None
    try:
        from src.db_service import get_connection
        conn = get_connection()
        if conn:
            c = conn.cursor()
            # Try by user_id (DB vacancy) or company name
            user_id = v.get("user_id")
            if user_id:
                c.execute("SELECT logo_url FROM app.companies WHERE user_id = %s", (user_id,))
            else:
                c.execute("SELECT logo_url FROM app.companies WHERE LOWER(name) = LOWER(%s)", (v.get("company", ""),))
            row = c.fetchone()
            if row and row[0]:
                company_logo = row[0]
            c.close()
            conn.close()
    except Exception as e:
        print(f"[!] Company logo lookup error: {e}")

    return render_template("vacancy_detail.html", vacancy=v, has_applied=has_applied,
                           similar_jobs=similar_jobs, match_score=match_score, company_logo=company_logo)


@app.route("/vacancies/<vacancy_id>/apply", methods=["POST"])
@login_required
@job_seeker_required
def apply_vacancy(vacancy_id):
    from src.application_service import apply_to_vacancy
    from src.employer_service import get_vacancy
    from src.notification_service import notify_new_application
    cv = request.files.get("cv")
    cover = request.form.get("cover_letter", "").strip()
    app_obj, err = apply_to_vacancy(vacancy_id, str(current_user.id), current_user.username, cv, cover)
    if err:
        flash(err, "error")
    else:
        flash("Lamaran berhasil dikirim!", "success")
        # Notify employer
        v = get_vacancy(vacancy_id)
        if v:
            owner_id = v.get("user_id", 0)
            v_title = v.get("job_title", "Lowongan")
            notify_new_application(owner_id, current_user.username, v_title, vacancy_id)
    return redirect(url_for("vacancy_detail", vacancy_id=vacancy_id))


@app.route("/my-applications", methods=["GET"])
@login_required
@job_seeker_required
def my_applications():
    from src.application_service import get_applications_for_user, get_vacancy_title
    apps = get_applications_for_user(str(current_user.id))
    from src.employer_service import get_vacancy
    from src.db_service import get_connection
    conn = get_connection()
    employer_ids = set()
    for a in apps:
        a["vacancy_title"] = get_vacancy_title(a["vacancy_id"])
        v = get_vacancy(a["vacancy_id"])
        emp_id = v.get("user_id", 0) if v else 0
        if emp_id == 0 and conn and v:
            try:
                c2 = conn.cursor()
                c2.execute("SELECT user_id FROM app.companies WHERE name = %s LIMIT 1", (v.get("company", ""),))
                r2 = c2.fetchone()
                if r2:
                    emp_id = r2[0]
                c2.close()
            except Exception:
                pass
        a["employer_id"] = emp_id
        if emp_id:
            employer_ids.add(emp_id)

    # Batch load company logos
    company_logos = {}
    if conn and employer_ids:
        try:
            c = conn.cursor()
            ids = tuple(employer_ids)
            c.execute(f"SELECT user_id, logo_url FROM app.companies WHERE user_id IN {ids}")
            for row in c.fetchall():
                company_logos[row[0]] = row[1]
            c.close()
        except Exception as e:
            print(f"[!] Logo lookup error: {e}")

    for a in apps:
        a["logo_url"] = company_logos.get(a.get("employer_id"))

    if conn:
        conn.close()
    return render_template("my_applications.html", applications=apps)


@app.route("/api/messages/<vacancy_id>", methods=["GET"])
@login_required
def api_get_conversation_seeker(vacancy_id):
    from src.db_service import get_connection
    # Cari semua pesan di vacancy ini yang melibatkan current user
    conn = get_connection()
    if not conn:
        return jsonify({"messages": []})
    try:
        c = conn.cursor()
        c.execute("""
            SELECT id, vacancy_id, sender_id, receiver_id, message, created_at
            FROM app.messages
            WHERE vacancy_id = %s AND (sender_id = %s OR receiver_id = %s)
            ORDER BY created_at ASC
        """, (vacancy_id, current_user.id, current_user.id))
        rows = c.fetchall()
        c.close()
        conn.close()
        return jsonify({"messages": [{
            "id": r[0], "vacancy_id": r[1], "sender_id": r[2],
            "receiver_id": r[3], "message": r[4], "created_at": str(r[5]) if r[5] else "",
        } for r in rows]})
    except Exception as e:
        print(f"[!] get_conversation error: {e}")
        return jsonify({"messages": []})


@app.route("/api/messages/send", methods=["POST"])
@login_required
def api_send_message_seeker():
    from src.message_service import send_message
    from src.notification_service import notify_new_message
    from src.db_service import get_connection
    data = request.get_json(force=True)
    vacancy_id = data.get("vacancy_id", "")
    receiver_id = data.get("receiver_id", 0)
    message = data.get("message", "")
    if not vacancy_id or not receiver_id:
        return jsonify({"error": "Data tidak lengkap"}), 400
    result, error = send_message(vacancy_id, current_user.id, receiver_id, message)
    if error:
        return jsonify({"error": error}), 400

    try:
        conn = get_connection()
        if conn:
            c = conn.cursor()
            c.execute("SELECT job_title, user_id FROM app.vacancies WHERE id = %s", (vacancy_id,))
            vrow = c.fetchone()
            vacancy_title = vrow[0] if vrow else vacancy_id
            c.execute("SELECT full_name FROM app.job_seeker_profiles WHERE user_id = %s", (current_user.id,))
            prow = c.fetchone()
            sender_name = prow[0] if prow else "Pelamar"
            c.close()
            conn.close()
            notify_new_message(receiver_id, sender_name, vacancy_title, vacancy_id)
    except Exception as e:
        print(f"[!] Gagal mengirim notifikasi pesan: {e}")

    return jsonify({"success": True, "message": result})


@app.route("/api/messages/unread/<int:user_id>", methods=["GET"])
@login_required
def api_unread_count(user_id):
    from src.message_service import get_user_messages
    msgs = get_user_messages(user_id)
    unread = sum(1 for m in msgs if m["receiver_id"] == user_id)
    return jsonify({"unread": unread})


@app.route("/api/notifications", methods=["GET"])
@login_required
def api_get_notifications():
    from src.notification_service import get_notifications, get_unread_count
    limit = request.args.get("limit", 20, type=int)
    notifs = get_notifications(current_user.id, limit)
    unread = get_unread_count(current_user.id)
    return jsonify({"notifications": notifs, "unread": unread})


@app.route("/api/notifications/read/<int:notif_id>", methods=["POST"])
@login_required
def api_read_notification(notif_id):
    from src.notification_service import read_notification
    read_notification(notif_id, current_user.id)
    return jsonify({"success": True})


@app.route("/api/notifications/read-all", methods=["POST"])
@login_required
def api_read_all_notifications():
    from src.notification_service import read_all_notifications
    read_all_notifications(current_user.id)
    return jsonify({"success": True})


@app.route("/download-cv/<app_id>")
@login_required
def download_cv(app_id):
    from src.application_service import get_applications_for_user
    from src.db_service import get_connection
    from flask import send_from_directory

    cv_filename = None
    owner_user_id = None
    owner_username = None

    # Try DB first
    try:
        conn = get_connection()
        if conn:
            c = conn.cursor()
            c.execute("SELECT user_id, username, cv_filename FROM app.applications WHERE id = %s", (app_id,))
            row = c.fetchone()
            if row:
                owner_user_id, owner_username, cv_filename = row[0], row[1], row[2]
            c.close()
            conn.close()
    except Exception:
        pass

    # Fallback to JSON
    if not cv_filename:
        from src.application_service import _read
        apps = _read()
        for a in apps:
            if a["id"] == app_id:
                owner_user_id = a.get("user_id")
                owner_username = a.get("username", "")
                cv_filename = a.get("cv_filename", "")
                break

    if not cv_filename:
        flash("CV tidak ditemukan.", "error")
        return redirect(url_for("landing"))

    if str(current_user.id) != str(owner_user_id) and current_user.role != "employer":
        flash("Akses ditolak.", "error")
        return redirect(url_for("landing"))

    return send_from_directory(
        str(Path(__file__).parent / "uploads" / "cvs"),
        cv_filename,
        as_attachment=True,
        download_name=f"cv_{owner_username}.pdf",
    )
    return redirect(url_for("landing"))


@app.route("/dashboard", methods=["GET"])
@login_required
@job_seeker_required
def dashboard():
    from src.db_service import get_profile_by_user_id
    from src.application_service import get_applications_for_user
    from src.employer_service import get_vacancy

    profile = get_profile_by_user_id(int(current_user.id))
    user_skills = profile.get("skills", []) if profile else []
    user_name = profile.get("full_name", "") if profile else ""

    # Personal Stats
    all_apps = get_applications_for_user(str(current_user.id)) or []
    status_counts = {"pending": 0, "reviewed": 0, "accepted": 0, "rejected": 0}
    for a in all_apps:
        s = a.get("status", "pending")
        if s in status_counts:
            status_counts[s] += 1

    saved_list = read_saved_jobs(current_user.username) or []

    # Auto Recommendation based on profile skills
    recommendations = []
    if user_skills:
        try:
            query = " ".join(user_skills[:6])
            G = load_graph()
            recommendations = recommend_jobs_sentence(
                G, query, top_n=6,
                DB_URL=DB_URL, username=current_user.username,
                use_cross_encoder=False, use_kg_enhanced=False,
                alpha=0.8, beta=0.25,
            )
        except Exception as e:
            print(f"[!] Auto-recommend error: {e}")

    # Recent Applications
    recent_apps = []
    for a in sorted(all_apps, key=lambda x: x.get("created_at", ""), reverse=True)[:5]:
        v = get_vacancy(a["vacancy_id"])
        recent_apps.append({
            "vacancy_title": v.get("job_title", "Unknown") if v else "Unknown",
            "company": v.get("company", "-") if v else "-",
            "status": a.get("status", "pending"),
            "created_at": a.get("created_at", ""),
            "vacancy_id": a["vacancy_id"]
        })

    # Recent Saved
    recent_saved = saved_list[-5:] if saved_list else []

    # Quick Actions
    has_cv = bool(profile and profile.get("cv_filename"))

    return render_template(
        "dashboard.html",
        user_name=user_name or current_user.username,
        stats={
            "total_applied": len(all_apps),
            "pending": status_counts["pending"],
            "reviewed": status_counts["reviewed"],
            "accepted": status_counts["accepted"],
            "rejected": status_counts["rejected"],
            "saved": len(saved_list),
        },
        recommendations=recommendations,
        recent_applications=recent_apps,
        recent_saved=recent_saved,
        has_cv=has_cv,
        profile_complete=bool(user_skills),
    )


@app.route("/profile", methods=["GET", "POST"])
@login_required
@job_seeker_required
def profile():
    from src.db_service import get_profile_by_user_id, upsert_profile
    from src.db_service import search_job_titles

    profile = get_profile_by_user_id(int(current_user.id))

    if request.method == "POST":
        skills_raw = request.form.get("skills", "")
        skills = [s.strip().lower() for s in skills_raw.split(",") if s.strip()]
        exp = request.form.get("experience_years", 0)
        salary = request.form.get("expected_salary_min", 0)
        ok = upsert_profile(
            user_id=int(current_user.id),
            full_name=request.form.get("full_name", ""),
            phone=request.form.get("phone", ""),
            skills=skills,
            experience_years=int(exp) if exp else 0,
            education=request.form.get("education", ""),
            expected_salary_min=float(salary) if salary else 0,
            location=request.form.get("location", ""),
            portfolio_url=request.form.get("portfolio_url", ""),
            headline=request.form.get("headline", ""),
            about=request.form.get("about", ""),
        )
        if ok:
            flash("Profil berhasil disimpan!", "success")
        else:
            flash("Gagal menyimpan profil.", "error")
        return redirect(url_for("profile"))

    return render_template("profile.html", profile=profile)


@app.route("/profile/<int:user_id>")
@login_required
def profile_view(user_id):
    from src.db_service import get_profile_by_user_id
    p = get_profile_by_user_id(user_id)
    if not p:
        flash("Profil tidak ditemukan.", "error")
        return redirect(url_for("landing"))
    profile_owner = user_id == int(current_user.id)
    return render_template("profile_view.html", profile=p, profile_owner=profile_owner)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
