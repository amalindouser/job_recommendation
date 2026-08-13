import csv
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

ESCO_DIR = Path(__file__).parent.parent.parent / "data" / "ontology"
ESCO_RAW_DIR = ESCO_DIR / "esco_raw"
ESCO_PARSED_DIR = ESCO_DIR / "esco_parsed"

TABIYA_API = "https://api.github.com/repos/tabiya-tech/tabiya-open-dataset"
TABIYA_ZIP_URL = f"{TABIYA_API}/zipball/main"
TABIYA_CSV_URL = "https://raw.githubusercontent.com/tabiya-tech/tabiya-open-dataset/main/tabiya-esco-v1.1.1/csv"

ESCO_OCCUPATIONS_JSON = ESCO_PARSED_DIR / "occupations.json"
ESCO_SKILLS_JSON = ESCO_PARSED_DIR / "skills.json"
ESCO_OCCUPATION_SKILLS_JSON = ESCO_PARSED_DIR / "occupation_skills.json"
ESCO_ONTOLOGY_JSON = ESCO_DIR / "esco_ontology.json"


def download_tabiya(force: bool = False) -> Optional[Path]:
    ESCO_RAW_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = ESCO_RAW_DIR / "tabiya-open-dataset.zip"

    if zip_path.exists() and not force:
        print(f"[OK] Tabiya dataset already exists at {zip_path}")
        return zip_path

    print(f"[...] Downloading Tabiya open dataset from GitHub ...")
    try:
        r = requests.get(TABIYA_ZIP_URL, stream=True, timeout=300)
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = int(downloaded / total * 100)
                    print(f"\r  Downloaded {pct}%", end="", flush=True)
        print(f"\n[OK] Downloaded {zip_path} ({downloaded // 1024 // 1024} MB)")
        return zip_path
    except Exception as e:
        print(f"[!] GitHub download failed: {e}")
        print("[!] Trying individual CSV files directly ...")
        return None


def _find_csv_dir(extract_root: Path) -> Optional[Path]:
    for p in extract_root.rglob("*.csv"):
        return p.parent
    for p in extract_root.iterdir():
        if p.is_dir():
            result = _find_csv_dir(p)
            if result:
                return result
    return None


def download_csv_direct(force: bool = False) -> Optional[Path]:
    ESCO_RAW_DIR.mkdir(parents=True, exist_ok=True)
    csv_files = [
        "occupations.csv", "skills.csv", "occupation_skill_relations.csv",
        "skill_skill_relations.csv", "ISCOGroups.csv", "occupations_hierarchy.csv",
        "skillGroups.csv", "skills_hierarchy.csv",
    ]
    all_ok = True
    for fname in csv_files:
        dest = ESCO_RAW_DIR / fname
        if dest.exists() and not force:
            print(f"[OK] {fname} already exists")
            continue
        url = f"{TABIYA_CSV_URL}/{fname}"
        print(f"[...] Downloading {fname} ...")
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            dest.write_bytes(r.content)
            print(f"[OK] Downloaded {fname} ({len(r.content) // 1024} KB)")
        except Exception as e:
            print(f"[!] Failed to download {fname}: {e}")
            all_ok = False
    return ESCO_RAW_DIR if all_ok else None


def extract_tabiya(zip_path: Path) -> Optional[Path]:
    ESCO_RAW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(ESCO_RAW_DIR / "_extracted")
        csv_dir = _find_csv_dir(ESCO_RAW_DIR / "_extracted")
        if csv_dir:
            import shutil
            for f in csv_dir.glob("*.csv"):
                shutil.copy2(f, ESCO_RAW_DIR / f.name)
            print(f"[OK] Extracted CSVs to {ESCO_RAW_DIR}")
            return ESCO_RAW_DIR
        else:
            print("[!] No CSV files found in extracted zip")
            return None
    except Exception as e:
        print(f"[!] Extraction failed: {e}")
        return None


def _read_csv(filename: str) -> List[Dict[str, str]]:
    filepath = ESCO_RAW_DIR / filename
    if not filepath.exists():
        print(f"[!] File not found: {filepath}")
        return []
    content = filepath.read_text(encoding="utf-8", errors="replace")
    rows = []
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        rows.append({k.strip(): v.strip() for k, v in row.items() if k})
    print(f"[OK] Read {filename}: {len(rows)} rows")
    return rows


def parse_occupations() -> Dict[str, dict]:
    rows = _read_csv("occupations.csv")
    occupations = {}
    for r in rows:
        code = (r.get("ORIGINURI", "") or r.get("CODE", "")).strip()
        title = (r.get("PREFERREDLABEL", "") or "").strip()
        occ_id = (r.get("ID", "") or "").strip()
        alt_labels = (r.get("ALTLABELS", "") or "").strip()
        description = (r.get("DESCRIPTION", "") or r.get("DEFINITION", "") or "").strip()
        isco_group = (r.get("ISCOGROUPCODE", "") or "").strip()
        if occ_id and title:
            occupations[occ_id] = {
                "title": title,
                "code": code,
                "alt_labels": alt_labels,
                "description": description,
                "isco_group": isco_group,
            }
    with open(ESCO_OCCUPATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(occupations, f, indent=2)
    print(f"[OK] Saved {len(occupations)} ESCO occupations to {ESCO_OCCUPATIONS_JSON}")
    return occupations


def parse_skills() -> Dict[str, dict]:
    rows = _read_csv("skills.csv")
    skills = {}
    for r in rows:
        sid = (r.get("ID", "") or "").strip()
        name = (r.get("PREFERREDLABEL", "") or "").strip()
        uri = (r.get("ORIGINURI", "") or "").strip()
        alt_labels = (r.get("ALTLABELS", "") or "").strip()
        description = (r.get("DESCRIPTION", "") or r.get("DEFINITION", "") or "").strip()
        skill_type = (r.get("SKILLTYPE", "") or "").strip()
        reuse = (r.get("REUSELEVEL", "") or "").strip()
        if sid and name:
            skills[sid] = {
                "name": name,
                "uri": uri,
                "alt_labels": alt_labels,
                "description": description,
                "skill_type": skill_type,
                "reusability": reuse,
            }
    with open(ESCO_SKILLS_JSON, "w", encoding="utf-8") as f:
        json.dump(skills, f, indent=2)
    print(f"[OK] Saved {len(skills)} ESCO skills to {ESCO_SKILLS_JSON}")
    return skills


def parse_occupation_skills(
    occupations: Dict[str, dict],
    skills: Dict[str, dict],
) -> Dict[str, dict]:
    rows = _read_csv("occupation_skill_relations.csv")
    occ_skills: Dict[str, dict] = {}

    for occ_id in occupations:
        occ_skills[occ_id] = {
            "title": occupations[occ_id]["title"],
            "essential_skills": [],
            "optional_skills": [],
            "all_skills": [],
        }

    for r in rows:
        occ_id = (r.get("OCCUPATIONID", "") or "").strip()
        skill_id = (r.get("SKILLID", "") or "").strip()
        relation = (r.get("RELATIONTYPE", "") or "essential").strip().lower()

        if occ_id not in occ_skills:
            if occ_id in occupations:
                occ_skills[occ_id] = {
                    "title": occupations[occ_id]["title"],
                    "essential_skills": [],
                    "optional_skills": [],
                    "all_skills": [],
                }
            else:
                continue

        if skill_id in skills:
            skill_name = skills[skill_id]["name"]
        else:
            skill_name = skill_id

        entry = {"id": skill_id, "name": skill_name}
        if "optional" in relation:
            occ_skills[occ_id]["optional_skills"].append(entry)
        else:
            occ_skills[occ_id]["essential_skills"].append(entry)
        occ_skills[occ_id]["all_skills"].append(entry)

    with open(ESCO_OCCUPATION_SKILLS_JSON, "w", encoding="utf-8") as f:
        json.dump(occ_skills, f, indent=2)
    print(f"[OK] Saved occupation-skills mapping for {len(occ_skills)} occupations")
    return occ_skills


def _norm_name(name: str) -> str:
    n = name.lower().strip()
    n = n.replace(",", "").replace("-", "_").replace("/", "_")
    n = n.replace("(", "").replace(")", "").replace(".", "")
    n = "_".join(n.split())
    return n


def build_esco_ontology(
    occupations: Dict[str, dict],
    skills: Dict[str, dict],
    occ_skills: Dict[str, dict],
) -> dict:
    job_to_skills = {}
    skill_relations = {
        "related_to": [],
        "substitutes": [],
        "prerequisite_of": [],
    }
    all_skill_names = set()

    for code, data in occ_skills.items():
        title = data.get("title", "")
        key = _norm_name(title)
        top_skills = []
        seen = set()
        for s in data.get("all_skills", []):
            name_norm = _norm_name(s["name"])
            if name_norm not in seen:
                seen.add(name_norm)
                top_skills.append(name_norm)
        if top_skills:
            job_to_skills[key] = top_skills

    for sid, info in skills.items():
        name = _norm_name(info["name"])
        all_skill_names.add(name)
    for skills_list in job_to_skills.values():
        for s in skills_list:
            all_skill_names.add(s)

    rel_rows = _read_csv("skill_skill_relations.csv")
    for r in rel_rows:
        requiring = r.get("REQUIRINGID", "").strip()
        required = r.get("REQUIREDID", "").strip()
        rel_type = r.get("RELATIONTYPE", "").strip().lower()
        if requiring in skills and required in skills:
            req_name = _norm_name(skills[requiring]["name"])
            reqd_name = _norm_name(skills[required]["name"])
            if "essential" in rel_type or "mandatory" in rel_type:
                skill_relations["prerequisite_of"].append((reqd_name, req_name))
            elif "optional" in rel_type:
                pass
            else:
                skill_relations["related_to"].append((req_name, reqd_name))

    return {
        "job_to_skills": job_to_skills,
        "skill_relations": skill_relations,
        "all_skill_names": sorted(all_skill_names),
    }


def run(force_download: bool = False):
    ESCO_PARSED_DIR.mkdir(parents=True, exist_ok=True)

    csv_dir = download_csv_direct(force=force_download)
    if csv_dir is None:
        zip_path = download_tabiya(force=force_download)
        if zip_path:
            csv_dir = extract_tabiya(zip_path)
        else:
            existing_csv = all((ESCO_RAW_DIR / f).exists() for f in
                             ["occupations.csv", "skills.csv", "occupation_skills.csv"])
            if existing_csv:
                print("[OK] Using existing CSV files")
                csv_dir = ESCO_RAW_DIR
            else:
                print("[!] Please download the ESCO dataset manually and place CSVs in:")
                print(f"    {ESCO_RAW_DIR}")
                print("    Required files: occupations.csv, skills.csv, occupation_skills.csv")
                print("    Available at: https://github.com/tabiya-tech/tabiya-open-dataset")
                return None

    if csv_dir:
        ESCO_RAW_DIR.mkdir(parents=True, exist_ok=True)

    occupations = parse_occupations()
    skills = parse_skills()
    occ_skills = parse_occupation_skills(occupations, skills)

    ontology = build_esco_ontology(occupations, skills, occ_skills)

    with open(ESCO_ONTOLOGY_JSON, "w", encoding="utf-8") as f:
        json.dump(ontology, f, indent=2)
    print(f"[OK] Saved ESCO ontology to {ESCO_ONTOLOGY_JSON}")
    print(f"     {len(occupations)} occupations")
    print(f"     {len(skills)} skills")
    print(f"     {len(ontology['job_to_skills'])} job-to-skills mappings")
    print(f"     {len(ontology['all_skill_names'])} unique skill names")

    return ontology


if __name__ == "__main__":
    force = "--force" in sys.argv
    run(force_download=force)
