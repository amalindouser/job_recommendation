import os
import re
import json
import hashlib
import numpy as np
import networkx as nx
from sklearn.metrics.pairwise import cosine_similarity
import psycopg2
import pandas as pd
import pickle
from pathlib import Path
from collections import Counter

from src.clean_skills import is_stop_skill, SKILL_NORMALIZE, categorize_skills, EXTRA_STOP_SKILLS, EXTRA_STOP_PATTERNS

import numpy as np
if not hasattr(np, "float_"):
    np.float_ = np.float64

if not hasattr(np, "int_"):
    np.int_ = np.int64

model = None
cross_encoder_model = None
_model_name_in_use = None

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
FALLBACK_MODEL_NAME = "all-MiniLM-L6-v2"


def _multilingual_ready() -> bool:
    """True bila file bobot model multilingual sudah lengkap di cache."""
    try:
        from huggingface_hub import try_to_load_from_cache
        for f in ("pytorch_model.bin", "model.safetensors"):
            p = try_to_load_from_cache(MODEL_NAME, f)
            if p and not str(p).endswith(".incomplete"):
                return True
        return False
    except Exception:
        return False

JOB_EMBEDDINGS = {}
JOB_EMB_ARRAY = None
JOB_NODE_IDS = []
JOB_METAS = []
NODEID_TO_INDEX = {}
JOB_DB_CACHE = {}
USER_SKILL_EMBS_CACHE = {}


def get_model():
    global model, _model_name_in_use
    if model is None:
        from sentence_transformers import SentenceTransformer
        name = MODEL_NAME if _multilingual_ready() else FALLBACK_MODEL_NAME
        if name != MODEL_NAME:
            print(f"[!] Multilingual model belum ter-download, fallback ke {FALLBACK_MODEL_NAME}")
        model = SentenceTransformer(name)
        _model_name_in_use = name
    return model


def get_active_model_name():
    if _model_name_in_use is None:
        get_model()
    return _model_name_in_use


def get_cross_encoder():
    global cross_encoder_model
    if cross_encoder_model is None:
        from sentence_transformers import CrossEncoder
        cross_encoder_model = CrossEncoder(
            'cross-encoder/ms-marco-MiniLM-L-6-v2',
            max_length=256
        )
    return cross_encoder_model


def normalize(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9+\-.\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_KNOWN_VOCAB = None


def _build_known_vocab() -> set:
    """Build a set of known skill words for fuzzy spell correction."""
    from src.clean_skills import SKILL_NORMALIZE
    vocab = set()
    for k, v in SKILL_NORMALIZE.items():
        for term in (k, v):
            vocab.add(term.lower())
            for w in term.split():
                if len(w) > 2:
                    vocab.add(w.lower())
    extra = {
        "python","java","javascript","typescript","golang","rust",
        "react","angular","vue","node","django","flask","rails",
        "docker","kubernetes","aws","azure","gcp","terraform",
        "machine","learning","deep","nlp","computer","vision",
        "tensorflow","pytorch","keras","scikit","pandas","numpy",
        "scipy","matplotlib","seaborn","plotly","dash","spark",
        "hadoop","kafka","airflow","mlops","ci","cd","jenkins",
        "gitlab","github","bitbucket","jira","confluence",
        "linux","unix","bash","powershell","vscode","pycharm",
        "mongodb","postgresql","mysql","redis","elasticsearch",
        "nosql","sqlite","mariadb","cassandra","dynamodb",
        "kotlin","swift","scala","r","ruby","php","perl","lua",
        "html","css","sass","less","webpack","babel","eslint",
        "rest","graphql","grpc","api","microservices",
        "sagemaker","lambda","ec2","s3","cloudfront","route53",
        "pytorch","opencv","nltk","spacy","gensim","transformers",
        "huggingface","langchain","llm","gpt","bert","roberta",
        "tableau","powerbi","looker","qlik","snowflake",
        "excel","word","powerpoint","outlook","sharepoint",
        "photoshop","illustrator","figma","sketch","adobe",
        "autocad","revit","solidworks","matlab","simulink",
        "quickbooks","oracle","sap","salesforce","hubspot",
        # Common job/skill terms – prevent false correction
        "marketing","digital","programming","programmer","coding",
        "sales","selling","accounting","finance","financial","banking",
        "human","resources","product","project","quality","operations",
        "logistics","supply","chain","procurement","legal","compliance",
        "audit","tax","customer","service","support","data","analytics",
        "analysis","admin","administrative","secretary","receptionist",
        "teaching","nurse","nursing","doctor","medical","healthcare",
        "pharmacy","hospitality","hotel","restaurant","chef","retail",
        "warehouse","mechanic","electrician","security","cleaning",
        "network","networking","server","web","mobile","android","ios",
        "design","designing","graphic","content","writing","editing",
        "social","media","communication","public","relations","event",
        "strategy","planning","research","development","testing",
        "training","recruitment","hiring","interview","payroll",
        # Common job title words – prevent false correction
        "developer","engineer","manager","analyst","specialist",
        "consultant","director","designer","scientist","architect",
        "coordinator","assistant","associate","intern","lead",
        "senior","junior","staff","principal","chief","head",
        "officer","supervisor","technician","representative",
        "advisor","agent","clerk","operator","planner","analyst",
        "frontend","backend","fullstack","full stack","devops",
        "node.js","react.js","vue.js","next.js","nuxt.js","express.js","angular.js",
        "administrator","specialist","trainer","instructor",
        "teacher","professor","researcher","fellow","intern",
        "apprentice","trainee","entry level","mid level",
    }
    vocab.update(extra)
    return vocab


def fuzzy_correct_query(query: str) -> str:
    """Correct common misspellings in user query against known skill vocabulary."""
    global _KNOWN_VOCAB
    if _KNOWN_VOCAB is None:
        _KNOWN_VOCAB = _build_known_vocab()
    words = query.split()
    corrected = []
    for w in words:
        w_clean = w.strip(".,;:!?\"'()[]{}").lower()
        if len(w_clean) <= 3 or w_clean in _KNOWN_VOCAB:
            corrected.append(w)
            continue
        if w_clean in _ID_SKIP_WORDS:
            corrected.append(w)
            continue
        from difflib import get_close_matches
        matches = get_close_matches(w_clean, _KNOWN_VOCAB, n=1, cutoff=0.75)
        if matches:
            match = matches[0]
            if w[0].isupper():
                match = match[0].upper() + match[1:]
            corrected.append(match)
        else:
            corrected.append(w)
    return " ".join(corrected)


_ID_SKIP_WORDS = {
    "yang", "untuk", "dengan", "dari", "saya", "aku", "dan", "atau",
    "sebagai", "mencari", "kerja", "pekerjaan", "lowongan", "bidang",
    "bisa", "mampu", "mahir", "pengalaman", "ingin", "mau", "suka",
    "perawat", "pasien", "guru", "dosen", "karyawan", "perusahaan",
    "bagian", "tentang", "dimana", "sampai", "setiap", "sudah", "belum",
    "lebih", "kurang", "harus", "akan", "dalam", "adalah", "ini", "itu",
    "juga", "tidak", "ada", "ke", "di", "pada", "secara", "serta",
    "pembuatan", "pengembangan", "manajemen", "pemasaran", "penjualan",
    "keuangan", "akuntansi", "perawatan", "pelayanan", "pelanggan",
    "informasi", "teknologi", "sistem", "jaringan", "aplikasi", "website",
    "konten", "media", "analisis", "analis", "laporan", "administrasi", "staff",
    "staf", "posisi", "jabatan", "pekerja", "bekerja", "lapangan",
    "produk", "layanan", "bagian", "tim", "team", "kemampuan", "keahlian",
    "skill", "skills", "tahun", "bahasa", "inggris", "indonesia",
    "selamat", "terima", "kasih", "tolong", "bantu", "beritahu",
    "program", "pengalaman kerja", "fresh", "graduate", "lulusan",
    "rapi", "jago", "jeli", "cekatan", "telaten", "teliti", "trampil",
    "terampil", "pandai", "pintar", "cerdas", "rajin", "tekun", "sabar",
    "ramah", "jujur", "sopan", "kreatif", "inovatif", "aktif", "handal",
    "tangkas", "waspada", "cermat", "antusias", "percaya", "diri",
    "mudah", "cepat", "lambat", "baik", "benar", "salah", "besar",
    "kecil", "baru", "lama", "muda", "tua", "tinggi", "rendah", "banyak",
    "sedikit", "bersih", "sehat", "senang", "gemar", "gampang", "sulit",
    "mengobati", "merawat", "melayani", "menjual", "membeli", "membuat",
    "menulis", "membaca", "menghitung", "menggambar", "menyusun",
    "berbicara", "berkomunikasi", "menjelaskan", "mengajar", "belajar",
    "melatih", "menjaga", "mengatur", "mengerjakan", "menyelesaikan",
    "bekerjasama", "berpikir", "memahami", "mengetahui", "memiliki",
    "senang", "nyaman", "bersemangat", "terbiasa", "mampu",
    "pernah", "sedang", "masih", "sangat", "sekali", "paling", "lagi",
    "bahwa", "ketika", "karena", "agar", "supaya", "sehingga",
    "meskipun", "walaupun", "jika", "kalau", "tanpa", "melalui",
    "antara", "hingga", "sejak", "selama", "beberapa", "semua",
    "seluruh", "masing", "sendiri", "bersama", "kamu", "dia", "kami",
    "kita", "mereka", "anda", "orang", "anak", "kantor", "tempat",
    "teman", "rekan", "satu", "dua", "tiga", "empat", "lima", "enam",
    "tujuh", "delapan", "sembilan", "sepuluh",
}


_COMPOUND_SKILLS = {
    "node js": "node.js",
    "react js": "react.js",
    "vue js": "vue.js",
    "next js": "next.js",
    "nuxt js": "nuxt.js",
    "express js": "express.js",
    "angular js": "angular.js",
    "front end": "frontend",
    "back end": "backend",
    "full stack": "fullstack",
}

_ALIAS_SKILLS = {
    "nodejs": "node.js",
    "reactjs": "react.js",
    "vuejs": "vue.js",
    "nextjs": "next.js",
    "nuxtjs": "nuxt.js",
    "expressjs": "express.js",
    "angularjs": "angular.js",
    "postgres": "postgresql",
}

def _preprocess_query(text: str) -> str:
    import re
    t = text.lower().strip()
    # Replace multi-word compounds first (space-separated)
    for compound, replacement in _COMPOUND_SKILLS.items():
        pattern = r'\b' + re.escape(compound) + r'\b'
        t = re.sub(pattern, replacement, t)
    # Replace single-word aliases
    words = t.split()
    corrected = []
    for w in words:
        w_clean = w.strip(".,;:!?\"'()[]{}")
        replacement = _ALIAS_SKILLS.get(w_clean, w)
        corrected.append(replacement)
    return " ".join(corrected)

def extract_skills_from_text(text: str) -> set:
    text = _preprocess_query(text)
    words = normalize(text).split()
    cleaned = set()
    for w in words:
        w = w.strip(".,;:!?\"'()[]{}")
        if len(w) > 1:
            cleaned.add(w)
    return cleaned


_EXTRA_STOP = {
    "telework", "standard position description", "spd94102",
    "irs telework program", "supervisory probationary period",
    "governmentissued charge card", "one year specialized experience",
    "nonbargaining unit position", "day shift",
    "alternative work schedule or telework", "nte 1 yr appointment",
    "open continuous announcement", "quality group rating",
    "selection interview", "career transition assistance plan (ctap)",
    "resume", "online application questionnaire", "education",
    "registration/license", "performance appraisal",
    "irs reassignment preference program (rpp)",
    "proof of employment through sf50",
    "ability to travel", "ability to meet deadlines",
    "ability to prioritize tasks", "ability to handle stress",
    "ability to work in a fastpaced environment",
    "ability to work under pressure",
    "ability to work independently and as part of a team",
    "u.s. department of education accredited college or university",
    "foreign education credentialing",
    "obtain transcripts or equivalent documentation",
    "time after competitive appointment (taca)",
    "current and former federal employees",
    "5 pages resume",
    "online questionnaire",
}


import re as _re

_EXTRA_STOP_PATTERNS_COMPILED = [_re.compile(p, _re.IGNORECASE) for p in EXTRA_STOP_PATTERNS]

def _is_extra_stop(skill):
    s = skill.lower().strip()
    if s in EXTRA_STOP_SKILLS:
        return True
    for p in _EXTRA_STOP_PATTERNS_COMPILED:
        if p.search(s):
            return True
    return False


def clean_job_skills(skills_raw_list, max_skills=6):
    if not skills_raw_list:
        return []
    cleaned = []
    seen = set()
    for s in skills_raw_list:
        key = s.strip().lower()
        norm = SKILL_NORMALIZE.get(key, key)
        if norm in seen:
            continue
        if norm in _EXTRA_STOP:
            continue
        if is_stop_skill(norm):
            continue
        if _is_extra_stop(norm):
            continue
        seen.add(norm)
        cleaned.append(norm)
    return cleaned[:max_skills]


# ===============================
# Database cache
# ===============================
def load_db_jobs_cache(DB_URL=None):
    global JOB_DB_CACHE
    if not DB_URL or JOB_DB_CACHE:
        return
    try:
        conn = psycopg2.connect(DB_URL)
        df = pd.read_sql("SELECT job_title, company_name, search_city, search_country, first_seen, job_link, job_type FROM jobs_skills", conn)
        conn.close()
        for _, row in df.iterrows():
            key = (str(row.get('job_title')).lower(), str(row.get('company_name')).lower())
            JOB_DB_CACHE[key] = {
                "location": f"{row.get('search_city')}, {row.get('search_country')}",
                "date": str(row.get("first_seen")) if pd.notna(row.get("first_seen")) else "",
                "link": row.get("job_link", "#"),
                "job_type": row.get("job_type", ""),
            }
        print(f"[OK] Cached {len(JOB_DB_CACHE)} jobs from database")
    except Exception as e:
        print(f"[!] DB cache load skipped (using graph data only): {e}")


def get_job_from_cache(job_title, company):
    key = (str(job_title).lower(), str(company).lower())
    return JOB_DB_CACHE.get(key)


# ===============================
# Embeddings loading
# ===============================
def _graph_fingerprint(G):
    ids = []
    for node_id, data in G.nodes(data=True):
        if data.get("type") == "job":
            ids.append(str(node_id))
    ids.sort()
    return hashlib.md5(",".join(ids[:200000]).encode()).hexdigest()


def load_and_cache_embeddings(G, batch_size=256, DB_URL=None, force_refresh=False):
    global JOB_EMBEDDINGS, JOB_EMB_ARRAY, JOB_NODE_IDS, JOB_METAS, NODEID_TO_INDEX

    if JOB_EMB_ARRAY is not None and not force_refresh:
        print("[OK] Embeddings already loaded, skipping")
        return

    cache_path = Path(__file__).parent.parent / "embeddings_cache.pkl"
    fp = _graph_fingerprint(G)
    if cache_path.exists() and not force_refresh:
        try:
            with open(cache_path, 'rb') as f:
                cache_data = pickle.load(f)
            if cache_data.get("model") != get_active_model_name() or cache_data.get("fingerprint") != fp:
                print(f"[!] Embedding cache stale (model/data changed), regenerating...")
            else:
                JOB_EMB_ARRAY = cache_data['embs']
                JOB_NODE_IDS = cache_data['node_ids']
                JOB_METAS = cache_data['metas']
                NODEID_TO_INDEX = cache_data['nodeid_to_index']
                print(f"[OK] Loaded {len(JOB_METAS)} embeddings from cache")
                return
        except Exception as e:
            print(f"[!] Cache load failed, will regenerate: {e}")

    load_db_jobs_cache(DB_URL=DB_URL)

    sentences = []
    node_ids = []
    metas = []

    for node_id, data in G.nodes(data=True):
        if data.get("type") != "job":
            continue

        job_title = data.get("job_title", "")
        company = data.get("company", "")

        skills_raw = data.get("skills_raw", "")
        if isinstance(skills_raw, str) and skills_raw:
            skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
        else:
            skills = []

        location = data.get("job_location", "")
        search_city = data.get("search_city", "")
        search_country = data.get("search_country", "")
        if search_city and search_country:
            location = f"{search_city}, {search_country}"

        date_str = data.get("first_seen", "")
        link = data.get("job_link", "#")
        job_type = data.get("job_type", "")

        text = f"{job_title} {company} {' '.join(skills)} {location}"
        text = normalize(text)

        if text.strip():
            sentences.append(text)
            node_ids.append(node_id)

            db_data = get_job_from_cache(job_title, company)
            meta = {
                "job_title": job_title,
                "company": company,
                "skills": skills,
                "location": db_data.get("location") if db_data else location,
                "link": db_data.get("link") if db_data else link,
                "date": db_data.get("date") if db_data else date_str,
                "job_type": db_data.get("job_type") if db_data else job_type,
                "match_percent": None
            }
            metas.append(meta)

    if not sentences:
        JOB_EMB_ARRAY = None
        JOB_NODE_IDS = []
        JOB_METAS = []
        NODEID_TO_INDEX = {}
        return

    print(f"[*] Encoding {len(sentences)} job sentences...")
    embs = get_model().encode(sentences, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs = embs / (norms + 1e-12)

    JOB_EMB_ARRAY = embs
    JOB_NODE_IDS = node_ids
    JOB_METAS = metas
    NODEID_TO_INDEX = {nid: i for i, nid in enumerate(node_ids)}

    try:
        with open(cache_path, 'wb') as f:
            pickle.dump({
                'embs': JOB_EMB_ARRAY,
                'node_ids': JOB_NODE_IDS,
                'metas': JOB_METAS,
                'nodeid_to_index': NODEID_TO_INDEX,
                'model': get_active_model_name(),
                'fingerprint': fp,
            }, f)
        print(f"[OK] Saved embeddings to cache")
    except Exception as e:
        print(f"[!] Cache save failed: {e}")

    print(f"[OK] Loaded {len(metas)} job embeddings")


# ===============================
# Skill matching improvements
# ===============================
def _encode_skills(skills_list):
    if not skills_list:
        return np.array([])
    enc = get_model().encode(skills_list, convert_to_numpy=True)
    norms = np.linalg.norm(enc, axis=1, keepdims=True)
    return enc / (norms + 1e-12)


def match_skills_semantic(user_skills_set, job_skills_list, threshold=0.45):
    if not job_skills_list or not user_skills_set:
        return [], []

    user_skills_list = list(user_skills_set)
    job_skills_norm = [normalize(s) for s in job_skills_list]

    us_embs = _encode_skills(user_skills_list)
    js_embs = _encode_skills(job_skills_list)

    if us_embs.size == 0 or js_embs.size == 0:
        return [], job_skills_norm

    sim_matrix = cosine_similarity(us_embs, js_embs)
    matched = []
    missing = []

    for j_idx, j_skill in enumerate(job_skills_norm):
        max_sim = np.max(sim_matrix[:, j_idx]) if sim_matrix.shape[1] > j_idx else 0
        if max_sim >= threshold:
            matched.append(j_skill)
        else:
            missing.append(j_skill)

    return matched, missing


def compute_hybrid_score(user_emb, job_emb, user_skills_set, job_skills_list, alpha=0.6):
    cos_sim = float(cosine_similarity(user_emb.reshape(1, -1), job_emb.reshape(1, -1))[0][0])

    skill_overlap = 0.0
    if job_skills_list and user_skills_set:
        job_skills_norm = [normalize(s) for s in job_skills_list]
        user_skills_norm = {normalize(s) for s in user_skills_set}
        matched_count = 0
        for js in job_skills_norm:
            # Exact match first
            if js in user_skills_norm:
                matched_count += 1
            else:
                # Word-level containment (e.g. "cloud" in "cloud computing")
                js_words = js.split()
                for us in user_skills_norm:
                    us_words = us.split()
                    if js_words == us_words:
                        matched_count += 1
                        break
                    # Check if one is fully contained in the other as multi-word
                    if len(js_words) >= 2 and len(us_words) >= 2:
                        if us in js or js in us:
                            matched_count += 1
                            break
        skill_overlap = matched_count / len(job_skills_norm) if job_skills_norm else 0

    return alpha * cos_sim + (1 - alpha) * skill_overlap


_JOB_SKILLS_NORM = None


def _get_job_skills_norm():
    """Pre-normalized job skills (norm_str, words_tuple) per job index, cached once."""
    global _JOB_SKILLS_NORM
    if _JOB_SKILLS_NORM is None and JOB_METAS:
        cache = []
        for meta in JOB_METAS:
            skills = meta.get("skills") or []
            cache.append([
                (normalize(s), tuple(normalize(s).split()))
                for s in skills if s and str(s).strip()
            ])
        _JOB_SKILLS_NORM = cache
    return _JOB_SKILLS_NORM


def _compute_skill_overlap(user_skills_norm, job_skills_norm):
    """Skill overlap fraction, same logic as compute_hybrid_score but using cached
    pre-normalized tuples so no per-job regex/split work is repeated."""
    if not job_skills_norm or not user_skills_norm:
        return 0.0
    user_set = {us for us, _ in user_skills_norm}
    user_multi = [(us, uw) for us, uw in user_skills_norm if len(uw) >= 2]
    matched = 0
    for js, jw in job_skills_norm:
        if js in user_set:
            matched += 1
            continue
        if len(jw) >= 2:
            for us, uw in user_multi:
                if us in js or js in us:
                    matched += 1
                    break
    return matched / len(job_skills_norm)


def compute_hybrid_scores_vectorized(user_emb, user_skills_set, job_indices, alpha=0.6):
    """Compute hybrid scores for many jobs at once.

    Cosine similarity is computed via a single vectorized matrix product instead
    of one sklearn call per job (~12s -> ~0.2s for 77k jobs), and skill overlap
    uses pre-normalized, cached job skill tuples.
    """
    job_emb_matrix = JOB_EMB_ARRAY[job_indices]
    cos_sims = np.dot(job_emb_matrix, user_emb)

    user_skills_norm = [
        (normalize(s), tuple(normalize(s).split())) for s in user_skills_set if s and str(s).strip()
    ]
    job_skills_norm = _get_job_skills_norm()

    overlap = np.empty(len(job_indices), dtype=np.float64)
    for k, idx in enumerate(job_indices):
        if idx < len(job_skills_norm):
            overlap[k] = _compute_skill_overlap(user_skills_norm, job_skills_norm[idx])
        else:
            overlap[k] = 0.0

    return alpha * cos_sims + (1 - alpha) * overlap


# ===============================
# MMR Diversity
# ===============================
def mmr_diversify(scores, embeddings, lambda_param=0.5, top_n=12):
    n = len(scores)
    if n <= top_n:
        return list(range(n))

    selected = []
    candidate_indices = list(range(n))
    selected_emb = None

    for _ in range(top_n):
        best_score = -float('inf')
        best_idx = -1

        for idx in candidate_indices:
            rel = scores[idx]
            if selected:
                sim_to_selected = cosine_similarity(
                    embeddings[idx].reshape(1, -1),
                    embeddings[selected].reshape(len(selected), -1)
                )
                diversity_penalty = np.max(sim_to_selected)
            else:
                diversity_penalty = 0

            mmr_score = lambda_param * rel - (1 - lambda_param) * diversity_penalty

            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx

        if best_idx >= 0:
            selected.append(best_idx)
            candidate_indices.remove(best_idx)

    return selected


# ===============================
# Personalization
# ===============================
def _get_user_profile(username):
    """Load user's saved jobs to build a profile embedding."""
    saved_path = Path(__file__).parent.parent / "database" / "saved_jobs.json"
    if not saved_path.exists():
        return None
    try:
        data = json.loads(saved_path.read_text(encoding="utf-8"))
        user_jobs = data.get(username, []) if isinstance(data, dict) else []
        if not user_jobs:
            return None

        texts = []
        for j in user_jobs:
            title = j.get("job_title", "")
            skills = " ".join(j.get("skills", []))
            texts.append(f"{title} {skills}")

        if not texts:
            return None

        embs = get_model().encode(texts, convert_to_numpy=True)
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        embs = embs / (norms + 1e-12)
        return np.mean(embs, axis=0)
    except Exception as e:
        print(f"[!] User profile error: {e}")
        return None


# ===============================
# Main recommendation function
# ===============================
def recommend_jobs_sentence(
    G,
    user_text: str,
    top_n: int = 12,
    filter_country: str = None,
    filter_city: str = None,
    DB_URL: str = None,
    username: str = None,
    use_cross_encoder: bool = False,
    alpha: float = 0.8,
    diversity_lambda: float = 0.7,
    use_kg_enhanced: bool = False,
    beta: float = 0.2,
):
    """
    Recommend jobs with hybrid scoring + MMR diversity + optional personalization.

    Args:
        G: NetworkX graph with job data
        user_text: User input skills/preferences
        top_n: Max number of recommendations
        filter_country: Filter by country
        filter_city: Filter by city
        DB_URL: Database connection URL
        username: Username for personalization (saved jobs)
        use_cross_encoder: Whether to use cross-encoder reranking (slower)
        alpha: Weight for cosine similarity (0-1). 1 = pure semantic, 0 = pure skill overlap
        diversity_lambda: MMR diversity parameter. 1 = pure relevance, 0 = pure diversity
        use_kg_enhanced: Whether to use KG-enhanced scoring (SBERT + skill_overlap + KG)
        beta: Weight for KG score, only used when use_kg_enhanced=True

    Returns:
        List of recommended jobs with match score
    """
    global JOB_EMB_ARRAY, JOB_METAS

    if JOB_EMB_ARRAY is None:
        load_and_cache_embeddings(G, DB_URL=DB_URL)

    if JOB_EMB_ARRAY is None or len(JOB_METAS) == 0:
        return []

    # Fuzzy correct misspellings in user query
    corrected_text = fuzzy_correct_query(user_text)
    if corrected_text != user_text:
        print(f"[*] Spell corrected query: '{user_text}' -> '{corrected_text}'")

    kg_service = None
    if use_kg_enhanced:
        try:
            from src.kge_service import get_kge_service
            kg_service = get_kge_service()
        except Exception as e:
            print(f"[!] KG service unavailable, falling back to standard scoring: {e}")
            use_kg_enhanced = False

    user_sentence = normalize(corrected_text)
    user_embedding = get_model().encode(user_sentence, convert_to_numpy=True)
    user_embedding = user_embedding / (np.linalg.norm(user_embedding) + 1e-12)

    user_skills_set = extract_skills_from_text(corrected_text)

    # Ontology expansion: add related/substitute/advanced skills from O*NET + ESCO
    try:
        from src.ontology_service import get_ontology
        ontology = get_ontology()
        expanded = set(user_skills_set)
        for s in list(user_skills_set):
            s_norm = s.replace(" ", "_")
            for rel in ontology.get_related_skills(s_norm):
                expanded.add(rel.replace("_", " "))
            for sub in ontology.get_substitute_skills(s_norm):
                expanded.add(sub.replace("_", " "))
            for adv in ontology.get_advanced_skills(s_norm):
                expanded.add(adv.replace("_", " "))
        user_skills_set = expanded
    except Exception:
        pass

    # Filter candidates by location
    candidates = list(range(len(JOB_METAS)))
    if filter_country or filter_city:
        fc = normalize(filter_country) if filter_country else None
        fcity = normalize(filter_city) if filter_city else None
        candidates = [
            i for i in candidates
            if (not fc or fc in normalize(JOB_METAS[i].get("location", "")))
            and (not fcity or fcity in normalize(JOB_METAS[i].get("location", "")))
        ]

    if not candidates:
        return []

    # Compute hybrid scores
    if use_kg_enhanced and kg_service is not None:
        hybrid_scores = []
        for idx in candidates:
            job_skills = JOB_METAS[idx].get("skills", [])
            job_node_id = JOB_NODE_IDS[idx] if idx < len(JOB_NODE_IDS) else None
            if job_node_id and job_node_id in G:
                score = kg_service.compute_enhanced_hybrid_score(
                    user_embedding,
                    JOB_EMB_ARRAY[idx],
                    user_skills_set,
                    job_skills,
                    job_node_id,
                    alpha=alpha,
                    beta=beta,
                )
            else:
                score = compute_hybrid_score(
                    user_embedding, JOB_EMB_ARRAY[idx],
                    user_skills_set, job_skills, alpha=alpha
                )
            hybrid_scores.append(score)
        hybrid_scores = np.array(hybrid_scores)
    else:
        hybrid_scores = compute_hybrid_scores_vectorized(
            user_embedding, user_skills_set, np.array(candidates), alpha=alpha
        )

    # Minimum threshold: filter out clearly irrelevant results
    min_score = 0.32
    valid_mask = hybrid_scores >= min_score
    candidates = [c for c, v in zip(candidates, valid_mask) if v]
    hybrid_scores = hybrid_scores[valid_mask]
    if len(candidates) == 0:
        return []

    # Get top candidates for reranking / diversity
    retrieval_count = min(top_n * 4, len(candidates))
    if retrieval_count < len(hybrid_scores):
        top_original = np.argsort(hybrid_scores)[::-1][:retrieval_count]
    else:
        top_original = np.argsort(hybrid_scores)[::-1]

    # Personalization boost: adjust scores based on user's saved jobs
    if username:
        try:
            user_profile_emb = _get_user_profile(username)
            if user_profile_emb is not None:
                for i, orig_idx in enumerate(top_original):
                    job_idx = candidates[orig_idx]
                    job_emb = JOB_EMB_ARRAY[job_idx]
                    profile_sim = float(cosine_similarity(
                        user_profile_emb.reshape(1, -1),
                        job_emb.reshape(1, -1)
                    )[0][0])
                    hybrid_scores[orig_idx] += 0.15 * profile_sim
        except Exception as e:
            print(f"[!] Personalization error: {e}")

    # Re-sort after personalization
    top_original = np.argsort(hybrid_scores)[::-1][:retrieval_count]

    # Optional cross-encoder reranking
    if use_cross_encoder:
        try:
            ce_model = get_cross_encoder()
            pairs = []
            ce_indices = []
            for i in top_original[:min(20, len(top_original))]:
                job_idx = candidates[i]
                job = JOB_METAS[job_idx]
                job_text = f"{job.get('job_title', '')} {' '.join(job.get('skills', []))} {job.get('location', '')}"
                pairs.append([user_text, job_text])
                ce_indices.append(i)

            if pairs:
                ce_scores = ce_model.predict(pairs, show_progress_bar=False)
                for i, orig_i in enumerate(ce_indices):
                    hybrid_scores[orig_i] = 0.7 * hybrid_scores[orig_i] + 0.3 * float(ce_scores[i])

                top_original = np.argsort(hybrid_scores)[::-1][:retrieval_count]
        except Exception as e:
            print(f"[!] Cross-encoder error (skipping): {e}")

    # MMR diversity
    candidate_embs = np.array([JOB_EMB_ARRAY[candidates[i]] for i in top_original])
    candidate_scores = hybrid_scores[top_original]
    diverse_order = mmr_diversify(candidate_scores, candidate_embs, lambda_param=diversity_lambda, top_n=top_n)

    # Build results
    results = []
    for pos in diverse_order:
        orig_rank = top_original[pos]
        job_idx = candidates[orig_rank]
        score = float(hybrid_scores[orig_rank])
        match_percent = int(min(100, max(0, score * 100)))

        job = JOB_METAS[job_idx].copy()
        job["match_percent"] = match_percent

        # Clean skills — remove noise, deduplicate, keep top N
        raw_skills = job.get("skills", [])
        clean_skills = clean_job_skills(raw_skills, max_skills=6)
        job["skills"] = clean_skills

        # Categorize skills for structured display
        job["categorized_skills"] = categorize_skills(clean_skills)

        # Generate structured description
        cat_descs = []
        for cat, skills in job["categorized_skills"].items():
            cat_descs.append(f"{cat}: {', '.join(skills)}")
        skills_desc = " | ".join(cat_descs[:3])
        job["description"] = f"{job.get('job_title', '')} @ {job.get('company', '')}\n{skills_desc}"

        # Semantic skill matching for display
        matched, missing = match_skills_semantic(user_skills_set, clean_skills)

        reason_parts = []

        if match_percent >= 80:
            reason_parts.append(f"[+] Excellent Match ({match_percent}%)")
            reason_parts.append(f"\nYou have {len(matched)}/{len(clean_skills)} required skills. You're a highly competitive candidate.")
        elif match_percent >= 65:
            reason_parts.append(f"[o] Strong Match ({match_percent}%)")
            reason_parts.append(f"\nYou have {len(matched)}/{len(clean_skills)} required skills. Ready to contribute with minimal ramp-up.")
        elif match_percent >= 45:
            reason_parts.append(f"[o] Fair Match ({match_percent}%)")
            reason_parts.append(f"\nYou have {len(matched)}/{len(clean_skills)} required skills. Good growth opportunity.")
        else:
            reason_parts.append(f"[o] Learning Opportunity ({match_percent}%)")
            reason_parts.append(f"\nYou have {len(matched)}/{len(clean_skills)} required skills. Strategic skill diversification opportunity.")

        if matched:
            matched_display = ", ".join(matched[:3])
            if len(matched) > 3:
                matched_display += f", +{len(matched)-3} more"
            reason_parts.append(f"\n\n[OK] Your strengths: {matched_display}")

        if missing:
            missing_display = ", ".join(missing[:3])
            if len(missing) > 3:
                missing_display += f", +{len(missing)-3} more"
            reason_parts.append(f"\n[!] Growth areas: {missing_display}")

        reason_parts.append(f"\nPOS: {job.get('location', 'TBD')}")
        if job.get('job_type'):
            reason_parts.append(f" | {job.get('job_type').title()}")

        if match_percent >= 75:
            reason_parts.append("\n\n-> Apply now! Strong candidate fit.")
        elif match_percent >= 55:
            reason_parts.append("\n\n-> Recommended for growth potential.")
        else:
            reason_parts.append("\n\n-> Worth exploring for career development.")

        job["reason_text"] = "".join(reason_parts)
        job["_matched_skills"] = matched
        job["_missing_skills"] = missing
        results.append(job)

    return results
