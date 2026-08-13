import io
import csv
import json
import os
import sys
import zipfile
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Optional, Tuple

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

ONET_DIR = Path(__file__).parent.parent.parent / "data" / "ontology"
ONET_RAW_DIR = ONET_DIR / "onet_raw"
ONET_PARSED_DIR = ONET_DIR / "onet_parsed"

ONET_VERSION = "30_3"
ONET_URL = f"https://www.onetcenter.org/dl_files/database/db_{ONET_VERSION}_text.zip"
ONET_ZIP = ONET_RAW_DIR / f"db_{ONET_VERSION}_text.zip"
ZIP_PREFIX = f"db_{ONET_VERSION}_text/"

ONET_OCCUPATIONS_JSON = ONET_PARSED_DIR / "occupations.json"
ONET_JOB_SKILLS_JSON = ONET_PARSED_DIR / "job_skills.json"
ONET_ALL_SKILLS_JSON = ONET_PARSED_DIR / "all_skills.json"
ONET_ONTOLOGY_JSON = ONET_DIR / "onet_ontology.json"
ONET_JOB_TITLES_JSON = ONET_PARSED_DIR / "job_titles.json"

SOFTWARE_DOMAINS = ["2.E.1", "2.E.2", "2.E.3", "2.E.4", "2.E.5", "2.E.6", "2.E.7", "2.E.8"]


def download_onet(force: bool = False) -> Optional[Path]:
    ONET_RAW_DIR.mkdir(parents=True, exist_ok=True)
    if ONET_ZIP.exists() and not force:
        print(f"[OK] O*NET zip already exists at {ONET_ZIP}")
        return ONET_ZIP

    print(f"[...] Downloading O*NET {ONET_VERSION} from {ONET_URL} ...")
    try:
        r = requests.get(ONET_URL, stream=True, timeout=(30, 600))
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        t0 = __import__('time').time()
        with open(ONET_ZIP, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    elapsed = __import__('time').time() - t0
                    speed = downloaded / elapsed / 1024 if elapsed > 0 else 0
                    print(f"\r  Downloaded {pct:.0f}% ({downloaded // 1024 // 1024} MB @ {speed:.0f} KB/s)", end="", flush=True)
        print()
        print(f"[OK] Downloaded {ONET_ZIP} ({downloaded // 1024 // 1024} MB)")
        return ONET_ZIP
    except Exception as e:
        print(f"[!] Download failed: {e}")
        print(f"[!] Please download manually from:")
        print(f"    https://www.onetcenter.org/database.html")
        print(f"    and place the text zip at: {ONET_ZIP}")
        return None


def read_tsv(filename: str) -> List[Dict[str, str]]:
    fpath = ZIP_PREFIX + filename
    with zipfile.ZipFile(ONET_ZIP, "r") as z:
        if fpath not in z.namelist():
            print(f"[!] File not found in ZIP: {fpath}")
            return []
        content = z.read(fpath).decode("utf-8", errors="replace")
    rows = []
    reader = csv.DictReader(io.StringIO(content), delimiter="\t")
    for row in reader:
        clean = {k.strip(): v.strip() for k, v in row.items() if k}
        rows.append(clean)
    print(f"[OK] Read {filename}: {len(rows)} rows")
    return rows


def parse_occupations() -> Dict[str, str]:
    rows = read_tsv("Occupation Data.txt")
    occupations = {}
    for r in rows:
        code = r.get("O*NET-SOC Code", "").strip()
        title = r.get("Title", "").strip()
        if code and title:
            occupations[code] = title
    ONET_PARSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(ONET_OCCUPATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(occupations, f, indent=2)
    print(f"[OK] Saved {len(occupations)} occupations to {ONET_OCCUPATIONS_JSON}")
    return occupations


def parse_job_titles() -> Dict[str, List[str]]:
    rows = read_tsv("Job Titles.txt")
    alt_titles: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        code = r.get("O*NET-SOC Code", "").strip()
        title = r.get("Job Title", "").strip()
        if code and title and title.lower() != "n/a":
            alt_titles[code].append(title)
    with open(ONET_JOB_TITLES_JSON, "w", encoding="utf-8") as f:
        json.dump(dict(alt_titles), f, indent=2)
    print(f"[OK] Saved {sum(len(v) for v in alt_titles.values())} alt job titles")
    return dict(alt_titles)


def build_ontology(occupations: Dict[str, str], alt_titles: Dict[str, List[str]]) -> dict:
    essential = read_tsv("Essential Skills.txt")
    transferable = read_tsv("Transferable Skills.txt")
    software = read_tsv("Software Skills.txt")
    knowledge_rows = read_tsv("Knowledge.txt")
    abilities_rows = read_tsv("Abilities.txt")

    job_skills: Dict[str, dict] = {}
    for code, title in occupations.items():
        job_skills[code] = {
            "title": title,
            "alt_titles": alt_titles.get(code, []),
            "essential_skills": [],
            "transferable_skills": [],
            "software_skills": [],
            "knowledge": [],
            "abilities": [],
            "all_skills": [],
        }

    def add_ratings(source_rows: str, target_key: str, min_importance: float = 3.0):
        """Add skills from rating-based source (Essential, Transferable, Knowledge, Abilities)."""
        for r in source_rows:
            code = r.get("O*NET-SOC Code", "").strip()
            eid = r.get("Element ID", "").strip()
            name = r.get("Element Name", "").strip()
            scale = r.get("Scale ID", "").strip()
            val_str = r.get("Data Value", "").strip()
            if code not in job_skills or not name or not val_str:
                continue
            try:
                val = float(val_str)
            except ValueError:
                continue
            if scale == "IM" and val < min_importance:
                continue
            if scale == "LV":
                continue
            entry = {"id": eid, "name": name, "importance": val}
            job_skills[code][target_key].append(entry)
            if val >= min_importance:
                job_skills[code]["all_skills"].append(entry)

    def add_software(source_rows: str):
        """Add software/technology skills."""
        seen_pairs: Set[Tuple[str, str]] = set()
        for r in source_rows:
            code = r.get("O*NET-SOC Code", "").strip()
            name = r.get("Element Name", "").strip()
            example = r.get("Workplace Example", "").strip()
            if code not in job_skills or not name:
                continue
            pair = (code, name)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            is_hot = r.get("Hot Technology", "N") == "Y"
            is_demand = r.get("In Demand", "N") == "Y"
            entry = {"id": r.get("Element ID", ""), "name": name, "example": example,
                     "hot_tech": is_hot, "in_demand": is_demand,
                     "importance": 4.0 if is_hot else 3.5 if is_demand else 3.0}
            job_skills[code]["software_skills"].append(entry)
            job_skills[code]["all_skills"].append(entry)

    add_ratings(essential, "essential_skills", min_importance=3.0)
    add_ratings(transferable, "transferable_skills", min_importance=3.0)
    add_ratings(knowledge_rows, "knowledge", min_importance=3.0)
    add_ratings(abilities_rows, "abilities", min_importance=3.5)
    add_software(software)

    for code in job_skills:
        job_skills[code]["all_skills"].sort(key=lambda x: -x["importance"])
        seen_names = set()
        unique_skills = []
        for s in job_skills[code]["all_skills"]:
            name_lower = s["name"].lower()
            if name_lower not in seen_names:
                seen_names.add(name_lower)
                unique_skills.append(s)
        job_skills[code]["all_skills"] = unique_skills

    ONET_PARSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(ONET_JOB_SKILLS_JSON, "w", encoding="utf-8") as f:
        json.dump(job_skills, f, indent=2)
    print(f"[OK] Saved job-skills mapping for {len(job_skills)} occupations")

    job_to_skills = {}
    all_skill_names: Set[str] = set()

    for code, data in job_skills.items():
        title = data["title"]
        key = title.lower().strip().replace(" ", "_")
        key = key.replace(",", "").replace("-", "_").replace("/", "_")
        key = key.replace("(", "").replace(")", "").replace(".", "")
        key = "_".join(key.split())
        top_skills = []
        seen = set()
        for s in data["all_skills"]:
            name_norm = s["name"].lower().replace(" ", "_").replace("-", "_")
            if name_norm not in seen:
                seen.add(name_norm)
                top_skills.append(name_norm)
                all_skill_names.add(name_norm)
        if top_skills:
            job_to_skills[key] = top_skills[:30]

        for alt in data.get("alt_titles", []):
            alt_key = alt.lower().strip().replace(" ", "_")
            alt_key = alt_key.replace(",", "").replace("-", "_").replace("/", "_")
            alt_key = alt_key.replace("(", "").replace(")", "").replace(".", "")
            alt_key = "_".join(alt_key.split())
            if alt_key not in job_to_skills:
                job_to_skills[alt_key] = top_skills[:20]

    seen_skill_names = set()
    skill_rows = essential + transferable
    skill_elements: Dict[str, str] = {}
    for r in skill_rows:
        eid = r.get("Element ID", "").strip()
        name = r.get("Element Name", "").strip()
        if eid and name and eid not in skill_elements:
            skill_elements[eid] = name

    know_elements: Dict[str, str] = {}
    for r in knowledge_rows:
        eid = r.get("Element ID", "").strip()
        name = r.get("Element Name", "").strip()
        if eid and name and eid not in know_elements:
            know_elements[eid] = name

    abil_elements: Dict[str, str] = {}
    for r in abilities_rows:
        eid = r.get("Element ID", "").strip()
        name = r.get("Element Name", "").strip()
        if eid and name and eid not in abil_elements:
            abil_elements[eid] = name

    related_to = build_skill_relations(job_skills, skill_elements, min_jaccard=0.4)

    ontology = {
        "job_to_skills": job_to_skills,
        "skill_relations": {
            "related_to": related_to,
            "substitutes": [],
            "prerequisite_of": [],
        },
        "all_skill_names": sorted(all_skill_names),
        "statistics": {
            "occupations": len(occupations),
            "essential_skills": len(set(r.get("Element ID", "") for r in essential)),
            "transferable_skills": len(set(r.get("Element ID", "") for r in transferable)),
            "software_skills": len(set(r.get("Element Name", "") for r in software)),
            "knowledge_areas": len(know_elements),
            "abilities": len(abil_elements),
            "job_to_skills_mappings": len(job_to_skills),
        },
    }

    with open(ONET_ONTOLOGY_JSON, "w", encoding="utf-8") as f:
        json.dump(ontology, f, indent=2)
    print(f"[OK] Saved O*NET ontology to {ONET_ONTOLOGY_JSON}")
    print(f"     {len(occupations)} occupations")
    print(f"     {len(skill_elements)} essential/transferable skill elements")
    print(f"     {len(know_elements)} knowledge areas")
    print(f"     {len(abil_elements)} abilities")
    print(f"     {len(job_to_skills)} job-to-skills mappings")
    print(f"     {len(related_to)} related skill pairs")
    print(f"     {len(all_skill_names)} unique skill names")

    return ontology


def build_skill_relations(
    job_skills: Dict[str, dict],
    skill_elements: Dict[str, str],
    min_jaccard: float = 0.4,
) -> List[List[str]]:
    from collections import defaultdict

    skill_job_sets: Dict[str, Set[str]] = defaultdict(set)
    for code, data in job_skills.items():
        for s in data["all_skills"]:
            skill_job_sets[s["name"].lower()].add(code)

    all_skill_names = list(skill_job_sets.keys())
    related_to = []

    for i in range(len(all_skill_names)):
        name_i = all_skill_names[i]
        jobs_i = skill_job_sets[name_i]
        for j in range(i + 1, len(all_skill_names)):
            name_j = all_skill_names[j]
            jobs_j = skill_job_sets[name_j]
            intersection = len(jobs_i & jobs_j)
            if intersection < 5:
                continue
            union = len(jobs_i | jobs_j)
            jaccard = intersection / union
            if jaccard >= min_jaccard:
                norm_i = name_i.replace(" ", "_").replace("-", "_")
                norm_j = name_j.replace(" ", "_").replace("-", "_")
                related_to.append([norm_i, norm_j])
                if len(related_to) >= 5000:
                    break
        if len(related_to) >= 5000:
            break

    print(f"[OK] Built {len(related_to)} skill relation pairs (jaccard >= {min_jaccard})")
    return related_to


def run(force_download: bool = False):
    ONET_PARSED_DIR.mkdir(parents=True, exist_ok=True)

    if not ONET_ZIP.exists():
        zip_path = download_onet(force=force_download)
        if zip_path is None:
            print("[!] O*NET data not available. Please download manually.")
            return None
    else:
        print(f"[OK] Using existing O*NET zip: {ONET_ZIP}")

    occupations = parse_occupations()
    alt_titles = parse_job_titles()
    ontology = build_ontology(occupations, alt_titles)

    stats = ontology.get("statistics", {})
    print(f"\n{'='*50}")
    print(f"  O*NET {ONET_VERSION} Import Summary")
    print(f"{'='*50}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"{'='*50}")

    return ontology


if __name__ == "__main__":
    force = "--force" in sys.argv
    run(force_download=force)
