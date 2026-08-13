
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
JSONL_PATH = DATA_DIR / "all_jobs_clean.jsonl"

EMPLOYMENT_LABELS = {
    "full_time": "Full Time",
    "part_time": "Part Time",
    "contract": "Kontrak",
    "internship": "Magang",
    "temporary": "Temporary",
}


def fmt_salary(j):
    def to_num(v):
        try:
            return float(v)
        except (ValueError, TypeError):
            return None
    mn = to_num(j.get("salary_min"))
    mx = to_num(j.get("salary_max"))
    period = j.get("salary_period") or ""
    if mn is not None and mx is not None:
        s = f"Rp {mn:,.0f} - Rp {mx:,.0f}"
    elif mn is not None:
        s = f"Rp {mn:,.0f}+"
    elif mx is not None:
        s = f"s.d. Rp {mx:,.0f}"
    else:
        s = ""
    if s and period:
        s += f" per {period}"
    return s


def generate_description(j):
    parts = []

    title = j.get("job_title", "").strip()
    company = j.get("company", "").strip()
    location = j.get("location", "").strip()
    employment = j.get("employment", "").strip()
    categories = j.get("categories", [])
    skills = j.get("skills", [])
    salary_text = fmt_salary(j)

    if company and title:
        parts.append(f"{company} membuka lowongan untuk posisi {title}.")
    elif title:
        parts.append(f"Lowongan untuk posisi {title}.")
    else:
        parts.append("Lowongan tersedia.")

    details = []
    if location:
        details.append(f"Lokasi: {location}")
    if employment and employment in EMPLOYMENT_LABELS:
        details.append(f"Jenis: {EMPLOYMENT_LABELS[employment]}")
    if categories and isinstance(categories, list):
        cat_str = ", ".join(c for c in categories[:3] if c)
        if cat_str:
            details.append(f"Bidang: {cat_str}")
    if salary_text:
        details.append(f"Gaji: {salary_text}")
    if details:
        parts.append(" ".join(details) + ".")

    if skills:
        skills_str = ", ".join(skills)
        parts.append(f"Kualifikasi yang dibutuhkan: {skills_str}.")

    if company:
        parts.append(f"Segera daftarkan dirimu dan kembangkan karir bersama {company}!")
    else:
        parts.append("Segera daftarkan dirimu!")

    return " ".join(parts)


def main():
    if not JSONL_PATH.exists():
        print(f"[!] {JSONL_PATH} not found")
        return

    tmp_path = JSONL_PATH.with_suffix(".jsonl.tmp")
    updated = 0
    skipped = 0
    total = 0

    with open(JSONL_PATH, "r", encoding="utf-8") as fin, \
         open(tmp_path, "w", encoding="utf-8") as fout:
        for line in fin:
            j = json.loads(line)
            total += 1
            desc_raw = (j.get("description_raw") or "").strip()
            desc = (j.get("description") or desc_raw).strip()

            # Regenerate if description is missing or very short (< 200 chars)
            if not desc or len(desc) < 200:
                new_desc = generate_description(j)
                j["description_raw"] = new_desc
                j["description"] = new_desc
                updated += 1
            else:
                j["description"] = desc
                j["description_raw"] = desc
                skipped += 1

            fout.write(json.dumps(j, ensure_ascii=False) + "\n")

    tmp_path.replace(JSONL_PATH)
    print(f"[OK] Total: {total}")
    print(f"[OK] Updated (short desc): {updated}")
    print(f"[OK] Skipped (already long): {skipped}")


if __name__ == "__main__":
    main()
