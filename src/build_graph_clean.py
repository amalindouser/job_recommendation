import os
import pandas as pd
import numpy as np

# Compatibility shim for NumPy 2.0 removal of alias types (used by networkx GraphML writer)
if not hasattr(np, "float_"):
    np.float_ = np.float64
if not hasattr(np, "int_"):
    np.int_ = np.int64
import networkx as nx
try:
    import pycountry
except Exception:
    pycountry = None
from pathlib import Path

ROOT = Path(__file__).parent
CSV_PATH = ROOT / "jobs_skills_1.csv"
OUT_GRAPH = ROOT / "graph_jobs_clean.graphml"


def normalize_text(s):
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return s.strip()


def build_graph_from_csv(csv_path=CSV_PATH, out_path=OUT_GRAPH):
    print(f"Reading CSV: {csv_path}")
    df = pd.read_csv(csv_path, dtype=str)

    # Replace NaN with empty string for all columns
    df = df.fillna("")

    G = nx.DiGraph()

    for idx, row in df.iterrows():
        job_node = f"job_{idx}"

        # Clean fields
        job_title = normalize_text(row.get("job_title", ""))
        company = normalize_text(row.get("company", ""))
        job_location = normalize_text(row.get("job_location", ""))
        first_seen = normalize_text(row.get("first_seen", ""))
        search_city = normalize_text(row.get("search_city", ""))
        search_country = normalize_text(row.get("search_country", ""))
        search_position = normalize_text(row.get("search_position", ""))
        job_level = normalize_text(row.get("job_level", ""))
        job_type = normalize_text(row.get("job_type", ""))
        job_link = normalize_text(row.get("job_link", ""))
        skills_raw = normalize_text(row.get("skills", ""))

        # Backfill search_country from job_location when missing
        if search_country.lower() in ("", "nan", "none"):
            # try to infer from job_location last segment
            guessed = ""
            if job_location:
                parts = [p.strip() for p in job_location.split(",") if p.strip()]
                if parts:
                    # try to find a country token in any segment, prefer last but scan all
                    country_aliases = {
                        'united states': 'United States', 'usa': 'United States', 'us': 'United States', 'u.s.': 'United States',
                        'united kingdom': 'United Kingdom', 'england': 'United Kingdom', 'uk': 'United Kingdom',
                        'canada': 'Canada', 'mexico': 'Mexico', 'australia': 'Australia'
                    }
                    us_states = {
                        'al','ak','az','ar','ca','co','ct','de','fl','ga','hi','id','il','in','ia','ks','ky','la','me','md','ma','mi','mn','ms','mo','mt','ne','nv','nh','nj','nm','ny','nc','nd','oh','ok','or','pa','ri','sc','sd','tn','tx','ut','vt','va','wa','wv','wi','wy'
                    }

                    # scan segments from last to first to prefer country-like endings
                    for seg in reversed(parts):
                        token = seg.lower()
                        token_clean = token
                        # if segment contains parentheses or extra tokens, take last word
                        if "," in token_clean:
                            token_clean = token_clean.split(",")[-1].strip()
                        words = [w.strip() for w in token_clean.replace("/"," ").split() if w.strip()]
                        # test full segment first
                        candidate = token_clean
                        if candidate in country_aliases:
                            guessed = country_aliases[candidate]
                            break
                        if len(candidate) > 2 and candidate.isalpha():
                            guessed = candidate.title()
                            # let pycountry validate later
                            break
                        # test words inside segment
                        for w in reversed(words):
                            wlow = w.lower().strip().strip('.')
                            if wlow in country_aliases:
                                guessed = country_aliases[wlow]
                                break
                            if wlow in us_states:
                                guessed = 'United States'
                                break
                            if len(wlow) > 2 and wlow.isalpha():
                                guessed = wlow.title()
                                break
                        if guessed:
                            break
            # try pycountry lookup on guessed token for better normalization
            if guessed:
                country_norm = guessed
                if pycountry is not None:
                    try:
                        # try lookup by name or alpha_2/alpha_3
                        c = None
                        try:
                            c = pycountry.countries.lookup(guessed)
                        except Exception:
                            # try title-case name
                            try:
                                c = pycountry.countries.lookup(guessed.title())
                            except Exception:
                                c = None
                        if c is not None:
                            country_norm = c.name
                    except Exception:
                        pass
                search_country = country_norm
            else:
                search_country = 'Unknown'
        if search_city.lower() in ("", "nan", "none"):
            # leave empty or set to Unknown? keep empty to avoid bogus values
            search_city = ""

        # If we couldn't infer a country and there's no job_location, skip this job
        if (not search_country or str(search_country).strip().lower() in ("", "nan", "none", "unknown")) and not job_location:
            # skip adding noisy/empty job entries
            continue

        # Add job node with string attributes only
        G.add_node(job_node, **{
            "type": "job",
            "job_id": str(idx),
            "job_title": job_title,
            "job_title_norm": job_title.lower(),
            "skills_raw": skills_raw,
            "company": company,
            "job_location": job_location,
            "first_seen": first_seen,
            "search_city": search_city,
            "search_country": search_country,
            "search_position": search_position,
            "job_level": job_level,
            "job_type": job_type,
            "job_link": job_link,
        })

        # Add skill nodes and edges
        if skills_raw:
            seen = set()
            for s in skills_raw.split(","):
                sk = normalize_text(s).lower()
                if not sk or sk in ("nan", "none"):
                    continue
                if sk in seen:
                    continue
                seen.add(sk)
                # use skill string as node id
                skill_node = sk
                if not G.has_node(skill_node):
                    G.add_node(skill_node, **{"type": "skill", "label": sk})
                # connect job -> skill
                G.add_edge(job_node, skill_node)

    # Save graph
    print(f"Writing GraphML to: {out_path}")
    nx.write_graphml(G, out_path)
    print("Done")


if __name__ == "__main__":
    build_graph_from_csv()
