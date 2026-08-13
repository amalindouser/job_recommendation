import json
import re
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "all_jobs_clean.db"
JSONL_PATH = DATA_DIR / "all_jobs_clean.jsonl"

_conn = None
_categories_cache = None
_fts_ready = False
_location_variants_cache = None


_LOCATION_PREFIX_REGIONS = {
    "jakarta": ("jakarta",),
    "tangerang": ("tangerang",),
    "bekasi": ("bekasi",),
    "depok": ("depok",),
    "bogor": ("bogor",),
    "bandung": ("bandung",),
    "cikarang": ("cikarang",),
    "karawang": ("karawang",),
    "surabaya": ("surabaya",),
    "yogyakarta": ("yogyakarta",),
    "semarang": ("semarang",),
    "malang": ("malang",),
    "medan": ("medan",),
    "makassar": ("makassar",),
    "batam": ("batam",),
    "pekanbaru": ("pekanbaru",),
    "palembang": ("palembang",),
    "balikpapan": ("balikpapan",),
    "denpasar": ("denpasar",),
    "badung": ("badung",),
    "padang": ("padang",),
    "lampung": ("lampung",),
}

_LOCATION_EXACT_REGIONS = {
    "bali": ("bali",),
    "banten": ("banten",),
}


def _build_location_variants():
    """Map region key -> set of lowercase exact location strings in the DB."""
    global _location_variants_cache
    if _location_variants_cache is not None:
        return _location_variants_cache
    conn = _get_conn()
    distinct = [
        str(r[0]) for r in conn.execute(
            "SELECT DISTINCT location FROM clean_jobs WHERE location IS NOT NULL AND location != ''"
        )
    ]
    variants = {}
    for region, keys in _LOCATION_PREFIX_REGIONS.items():
        matched = set()
        for loc in distinct:
            ll = loc.lower()
            toks = re.findall(r"[a-z0-9]+", ll)
            if any(t.startswith(k) for k in keys for t in toks):
                matched.add(ll)
        variants[region] = matched
    for region, keys in _LOCATION_EXACT_REGIONS.items():
        matched = set()
        for loc in distinct:
            ll = loc.lower()
            toks = re.findall(r"[a-z0-9]+", ll)
            if any(t == k for k in keys for t in toks):
                matched.add(ll)
        variants[region] = matched
    _location_variants_cache = variants
    return variants


def get_location_variants(region: str) -> set:
    """Exact location strings belonging to a region key (e.g. 'jakarta')."""
    return _build_location_variants().get(region.lower().strip(), set())


def _ensure_fts(conn):
    """Create/populate the FTS5 index over clean_jobs once."""
    global _fts_ready
    if _fts_ready:
        return True
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS clean_jobs_fts USING fts5("
            "job_title, company, skills, description, categorized_skills, location, "
            "id UNINDEXED, tokenize='unicode61')"
        )
        total = conn.execute("SELECT COUNT(*) FROM clean_jobs").fetchone()[0]
        indexed = conn.execute("SELECT COUNT(*) FROM clean_jobs_fts").fetchone()[0]
        if indexed != total:
            conn.execute("DELETE FROM clean_jobs_fts")
            conn.executemany(
                "INSERT INTO clean_jobs_fts (job_title, company, skills, description,"
                " categorized_skills, location, id) VALUES (?,?,?,?,?,?,?)",
                conn.execute(
                    "SELECT job_title, company, skills, description, categorized_skills, location, id"
                    " FROM clean_jobs"
                ),
            )
            conn.commit()
        _fts_ready = True
        return True
    except Exception:
        _fts_ready = False
        return False


def _fts_match_string(query: str) -> str:
    """Build a safe FTS5 MATCH phrase string mirroring LIKE '%q%' semantics."""
    phrase = re.sub(r"[^\w\s]", " ", query.lower().strip())
    phrase = re.sub(r"\s+", " ", phrase).strip()
    if not phrase:
        return ""
    if " " in phrase:
        return '"' + phrase.replace('"', '""') + '"'
    return phrase


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def _row_to_dict(row) -> dict:
    j = dict(row)
    for col in ("categories", "skills", "categorized_skills"):
        if isinstance(j.get(col), str):
            j[col] = json.loads(j[col])
    return j


def _parse_skills(skills_json: str) -> list:
    if not skills_json:
        return []
    return json.loads(skills_json)


def count_clean_jobs() -> int:
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM clean_jobs").fetchone()[0]


def get_clean_job_by_index(index: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM clean_jobs WHERE id = ?", (index,)).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def suggest_job_titles(term: str = "", limit: int = 10) -> list[str]:
    """Return the most frequent job titles matching `term` (substring, case-insensitive).

    Digunakan untuk autocomplete agar user tidak menebak-nebak judul pekerjaan.
    """
    conn = _get_conn()
    like = f"%{term.strip().lower()}%"
    rows = conn.execute(
        "SELECT MIN(job_title) AS title, COUNT(*) AS c FROM clean_jobs "
        "WHERE LOWER(job_title) LIKE ? "
        "GROUP BY LOWER(job_title) "
        "ORDER BY c DESC "
        "LIMIT ?",
        (like, int(limit)),
    ).fetchall()
    return [r["title"] for r in rows if r["title"]]


def search_clean_jobs(
    query: str = "",
    category: str = "",
    location: str = "",
    page: int = 1,
    per_page: int = 20,
    user_skills: set = None,
) -> dict:
    conn = _get_conn()

    q = query.lower().strip() if query else ""
    cat = category.lower().strip() if category else ""
    loc = location.lower().strip() if location else ""

    # Build WHERE clause
    wheres = []
    params = []

    if q:
        fts_ok = _ensure_fts(conn)
        match_str = _fts_match_string(q)
        if fts_ok and match_str:
            wheres.append("id IN (SELECT id FROM clean_jobs_fts WHERE clean_jobs_fts MATCH ?)")
            params.append(match_str)
        else:
            clauses = []
            for col in ("job_title", "company", "description", "skills"):
                clauses.append(f"LOWER({col}) LIKE ?")
                params.append(f"%{q}%")
            wheres.append("(" + " OR ".join(clauses) + ")")

    # For category filter, search the JSON text of categorized_skills
    if cat:
        wheres.append("LOWER(categorized_skills) LIKE ?")
        params.append(f"%{cat}%")

    # Location filter: match any of the exact location strings for the region
    if loc:
        loc_variants = get_location_variants(loc)
        if loc_variants:
            wheres.append(
                "LOWER(location) IN (" + ",".join("?" * len(loc_variants)) + ")"
            )
            params.extend(loc_variants)

    where_sql = " AND ".join(wheres) if wheres else "1=1"

    # Count total matching
    total = conn.execute(
        f"SELECT COUNT(*) FROM clean_jobs WHERE {where_sql}", params
    ).fetchone()[0]

    if total == 0:
        return {"results": [], "total": 0, "page": page, "pages": 0}

    # If user has skills, score all matching results and sort.
    # Exact per-row Jaccard scoring requires parsing every row's skill JSON, so
    # it is only affordable for small result sets. For broad matches (> limit)
    # we fall back to plain id order to keep the page responsive.
    SKILL_SCORE_LIMIT = 5000
    if user_skills and total <= SKILL_SCORE_LIMIT:
        # Load IDs and skills for all matching jobs
        rows = conn.execute(
            f"SELECT id, skills FROM clean_jobs WHERE {where_sql} ORDER BY id",
            params,
        ).fetchall()

        scored = []
        for row in rows:
            job_skills = _parse_skills(row["skills"])
            job_set = set(s.lower() for s in job_skills)
            overlap = len(user_skills & job_set)
            union = len(user_skills | job_set)
            score = round(overlap / max(union, 1) * 100) if job_set else 0
            scored.append((score, row["id"]))

        scored.sort(key=lambda x: (-x[0], x[1]))

        total = len(scored)
        pages = max(1, (total + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        page_ids = [sid for _, sid in scored[start:end]]

        # Fetch full data for page IDs
        if page_ids:
            placeholders = ",".join("?" for _ in page_ids)
            rows = conn.execute(
                f"SELECT * FROM clean_jobs WHERE id IN ({placeholders}) ORDER BY id",
                page_ids,
            ).fetchall()
            results_map = {r["id"]: _row_to_dict(r) for r in rows}
            results = [results_map[sid] for sid in page_ids]
            for r in results:
                r["match_score"] = next(
                    s for s, iid in scored if iid == r["id"]
                )
        else:
            results = []
    else:
        # No user skills - just return page ordered by id
        pages = max(1, (total + per_page - 1) // per_page)
        start = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT * FROM clean_jobs WHERE {where_sql} ORDER BY id LIMIT ? OFFSET ?",
            params + [per_page, start],
        ).fetchall()
        results = [_row_to_dict(r) for r in rows]
        for r in results:
            r["match_score"] = 0

    return {
        "results": results,
        "total": total,
        "page": page,
        "pages": pages,
    }


def get_all_categories() -> list:
    global _categories_cache
    if _categories_cache is not None:
        return _categories_cache
    conn = _get_conn()
    cats = set()
    # Scan categorized_skills JSON text for category names
    rows = conn.execute("SELECT categorized_skills FROM clean_jobs").fetchall()
    for row in rows:
        val = row["categorized_skills"]
        if val:
            try:
                obj = json.loads(val)
                for k in obj:
                    cats.add(k)
            except json.JSONDecodeError:
                pass
    _categories_cache = sorted(cats, key=lambda x: (x == "Lainnya", x))
    return _categories_cache
