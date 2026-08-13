import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from werkzeug.utils import secure_filename

from src.db_service import (
    apply_to_vacancy_db,
    get_applications_for_vacancy_db,
    get_applications_for_user_db,
    update_application_status_db,
)

DATA_DIR = Path(__file__).parent.parent / "data"
APPS_PATH = DATA_DIR / "applications.json"
UPLOAD_DIR = Path(__file__).parent.parent / "uploads" / "cvs"
ALLOWED_EXT = {"pdf", "doc", "docx"}


def _ensure():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not APPS_PATH.exists():
        APPS_PATH.write_text(json.dumps([], indent=2), encoding="utf-8")


def _read():
    _ensure()
    try:
        return json.loads(APPS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []

def _write(apps):
    APPS_PATH.write_text(json.dumps(apps, indent=2, ensure_ascii=False), encoding="utf-8")


MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

MAGIC_BYTES = {
    "pdf": b"%PDF",
    "doc": b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1",
    "docx": b"PK\x03\x04",
}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def validate_cv(cv_file):
    if not cv_file:
        return None
    if not allowed_file(cv_file.filename):
        return "Format file tidak didukung. Gunakan PDF, DOC, atau DOCX."
    cv_file.seek(0, os.SEEK_END)
    size = cv_file.tell()
    cv_file.seek(0)
    if size > MAX_FILE_SIZE:
        return f"Ukuran file maksimal 5MB."
    ext = cv_file.filename.rsplit(".", 1)[1].lower()
    header = cv_file.read(len(MAGIC_BYTES.get(ext, b"")))
    cv_file.seek(0)
    expected = MAGIC_BYTES.get(ext)
    if expected and not header.startswith(expected):
        return "File tidak valid atau rusak."
    return None


def apply_to_vacancy(vacancy_id, user_id, username, cv_file=None, cover_letter=""):
    cv_filename = ""
    if cv_file and cv_file.filename:
        err = validate_cv(cv_file)
        if err:
            return None, err
        ext = cv_file.filename.rsplit(".", 1)[1].lower()
        cv_filename = f"{uuid.uuid4().hex}.{ext}"
        cv_path = UPLOAD_DIR / cv_filename
        cv_file.save(str(cv_path))

    result, error = apply_to_vacancy_db(vacancy_id, user_id, username, cv_filename, cover_letter)
    if result:
        return result, None

    # Fallback to JSON
    import json
    apps = _read()
    existing = [a for a in apps if a["vacancy_id"] == vacancy_id and a["user_id"] == user_id]
    if existing:
        return None, "Anda sudah melamar lowongan ini."

    app = {
        "id": uuid.uuid4().hex[:12],
        "vacancy_id": vacancy_id,
        "user_id": user_id,
        "username": username,
        "cv_filename": cv_filename,
        "cover_letter": cover_letter,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }
    apps.append(app)
    _write(apps)
    return app, None


def get_applications_for_vacancy(vacancy_id):
    results = get_applications_for_vacancy_db(vacancy_id)
    if results:
        return results
    apps = _read()
    return [a for a in apps if a["vacancy_id"] == vacancy_id]


def get_applications_for_user(user_id):
    results = get_applications_for_user_db(user_id)
    if results:
        return results
    apps = _read()
    return [a for a in apps if a["user_id"] == user_id]


def update_application_status(app_id, new_status):
    result = update_application_status_db(app_id, new_status)
    if result:
        return result
    apps = _read()
    for a in apps:
        if a["id"] == app_id:
            a["status"] = new_status
            _write(apps)
            return a
    return None


def get_vacancy_title(vacancy_id):
    from src.employer_service import get_vacancy
    v = get_vacancy(vacancy_id)
    return v["job_title"] if v else "Unknown"
