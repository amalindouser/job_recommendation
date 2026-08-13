import os
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
import networkx as nx

from src.decorators import employer_required
from src.db_service import get_company_by_user_id

from src.employer_graph_service import (
    analyze_job_title,
    validate_job_skills,
    estimate_talent_availability,
    build_skill_subgraph,
    find_similar_jobs_by_title,
)

from src.db_service import (
    search_job_titles, get_all_job_titles,
    get_company_by_user_id, create_company,
)

from src.employer_service import (
    create_vacancy,
    list_vacancies,
    get_vacancy,
    get_vacancy_graph,
    get_graph_metrics,
    get_analytics_skills,
    get_analytics_companies,
    get_analytics_locations,
    get_analytics_levels,
    update_vacancy,
    delete_vacancy,
)
from src.graph_enricher import load_enriched_graph


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

def _load_clean_graph():
    path = os.path.join(DATA_DIR, "graph_jobs_clean.graphml")
    if not os.path.exists(path):
        path = os.path.join(DATA_DIR, "graph_jobs.graphml")
    G = nx.read_graphml(path)
    return G


employer_bp = Blueprint("employer", __name__, url_prefix="/employer")


@employer_bp.route("/dashboard")
@login_required
@employer_required
def dashboard():
    company = _get_current_company()
    if not company:
        return redirect(url_for("employer.company_setup"))
    return render_template("employer/dashboard.html", active_page="dashboard")


# === HTML Pages ===

@employer_bp.route("/vacancies")
@login_required
@employer_required
def vacancies_page():
    company = _get_current_company()
    if not company:
        return redirect(url_for("employer.company_setup"))
    search = request.args.get("search", "")
    tab = request.args.get("tab", "own")

    from src.employer_service import _read_vacancies
    from src.db_service import list_employer_vacancies_db
    own_vacancies = _read_vacancies()

    # Merge with DB vacancies (hanya milik employer yang login)
    db_vacs = list_employer_vacancies_db(user_id=current_user.id, search=search, limit=500)
    existing_ids = {v["id"] for v in own_vacancies}
    for v in db_vacs:
        if v["id"] not in existing_ids:
            own_vacancies.append(v)

    if search:
        s = search.lower()
        own_vacancies = [v for v in own_vacancies if s in v.get("job_title", "").lower()
                         or s in v.get("company", "").lower()
                         or s in " ".join(v.get("skills", [])).lower()]

    historical_vacancies = []
    if tab == "historical":
        try:
            from src.db_service import get_connection
            conn = get_connection()
            if conn:
                c = conn.cursor()
                q = "SELECT id, job_title, company, job_location, search_city, search_country, job_level, job_type, skills_raw, first_seen FROM app.jobs"
                params = []
                if search:
                    q += " WHERE LOWER(job_title) LIKE %s OR LOWER(company) LIKE %s OR LOWER(skills_raw) LIKE %s"
                    params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
                q += " ORDER BY first_seen DESC NULLS LAST LIMIT 500"
                c.execute(q, params)
                for row in c.fetchall():
                    skills = [s.strip().lower() for s in (row[8] or "").split(",") if s.strip()]
                    historical_vacancies.append({
                        "id": f"hist_{row[0]}", "job_title": row[1], "company": row[2] or "",
                        "skills": skills, "job_level": row[6] or "", "job_type": row[7] or "",
                        "location": f"{row[4]}, {row[5]}" if row[4] and row[5] else (row[3] or ""),
                        "created_at": row[9] or "", "historical": True,
                    })
                c.close(); conn.close()
        except Exception as e:
            print(f"[!] Gagal muat historical jobs: {e}")

    return render_template("employer/vacancies.html",
                           own_vacancies=own_vacancies,
                           historical_vacancies=historical_vacancies,
                           search=search, tab=tab, active_page="vacancies")


@employer_bp.route("/company/setup", methods=["GET", "POST"])
@login_required
@employer_required
def company_setup():
    company = get_company_by_user_id(current_user.id)
    if company:
        return redirect(url_for("employer.company_profile"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        industry = request.form.get("industry", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        website = request.form.get("website", "").strip()
        size = request.form.get("size", "").strip()
        hr_name = request.form.get("hr_name", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name:
            flash("Nama perusahaan wajib diisi.", "danger")
            return render_template("employer/company_setup.html", active_page="company_setup")

        result = create_company(current_user.id, name, industry, description,
                                location, website, size, "", hr_name, phone)
        if result:
            try:
                from src.employer_graph_service import add_company_node
                add_company_node({"id": result, "name": name, "industry": industry,
                                 "location": location, "website": website})
            except Exception as e:
                print(f"[!] Failed to add company node: {e}")
            flash("Profil perusahaan berhasil disimpan!", "success")
            return redirect(url_for("employer.dashboard"))
        else:
            flash("Gagal menyimpan profil perusahaan.", "danger")

    return render_template("employer/company_setup.html", active_page="company_setup")


@employer_bp.route("/company/profile", methods=["GET", "POST"])
@login_required
@employer_required
def company_profile():
    company = _get_current_company()
    if not company:
        return redirect(url_for("employer.company_setup"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        industry = request.form.get("industry", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        website = request.form.get("website", "").strip()
        size = request.form.get("size", "").strip()
        hr_name = request.form.get("hr_name", "").strip()
        phone = request.form.get("phone", "").strip()

        if not name:
            flash("Nama perusahaan wajib diisi.", "danger")
            return render_template("employer/company_profile.html", company=company, active_page="company_profile")

        # Handle logo upload
        logo_url = company.get("logo_url", "") if company else ""
        if "logo" in request.files:
            file = request.files["logo"]
            if file and file.filename:
                import os
                from werkzeug.utils import secure_filename
                ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
                if ext in {"png", "jpg", "jpeg", "gif", "webp", "svg"}:
                    filename = f"company_{current_user.id}_{secure_filename(file.filename)}"
                    upload_dir = os.path.join(current_app.root_path, "static", "uploads", "companies")
                    os.makedirs(upload_dir, exist_ok=True)
                    file.save(os.path.join(upload_dir, filename))
                    logo_url = f"/static/uploads/companies/{filename}"
                else:
                    flash("Format logo harus PNG, JPG, GIF, WebP, atau SVG.", "warning")

        result = create_company(current_user.id, name, industry, description,
                                location, website, size, logo_url, hr_name, phone)
        if result:
            flash("Profil perusahaan berhasil diperbarui!", "success")
            return redirect(url_for("employer.company_profile"))
        else:
            flash("Gagal memperbarui profil.", "danger")

        return redirect(url_for("employer.company_profile"))

    return render_template("employer/company_profile.html", company=company, active_page="company_profile")


def _get_current_company():
    try:
        return get_company_by_user_id(current_user.id)
    except Exception:
        return None


@employer_bp.context_processor
def inject_globals():
    company = _get_current_company()
    return dict(company=company)


@employer_bp.route("/vacancies/create")
@login_required
@employer_required
def create_vacancy_page():
    company = _get_current_company()
    company_name = company.get("name", "") if company else ""
    G = load_enriched_graph()
    levels = sorted(set(
        d.get("label", n) for n, d in G.nodes(data=True) if d.get("type") == "level"
    ))
    types = sorted(set(
        d.get("label", n) for n, d in G.nodes(data=True) if d.get("type") == "jobtype"
    ))
    locations = sorted(set(
        d.get("label", n) for n, d in G.nodes(data=True) if d.get("type") == "location"
    ))
    return render_template("employer/create.html", company_name=company_name, levels=levels, types=types, locations=locations, active_page="create")


@employer_bp.route("/vacancies/create-smart")
@login_required
@employer_required
def create_smart_vacancy_page():
    company = _get_current_company()
    company_name = company.get("name", "") if company else ""
    G = _load_clean_graph()
    companies = sorted(set(
        d.get("company", "") for n, d in G.nodes(data=True)
        if d.get("type") == "job" and d.get("company")
    ))
    return render_template("employer/create_smart.html", companies=companies, company_name=company_name, active_page="create_smart")


@employer_bp.route("/vacancies/<vacancy_id>")
@login_required
@employer_required
def vacancy_detail_page(vacancy_id):
    vacancy = get_vacancy(vacancy_id)
    if not vacancy:
        return "Lowongan tidak ditemukan", 404

    # Lowongan dari vacancies.json otomatis milik employer yang login
    if vacancy.get("historical"):
        return render_template(
            "employer/detail.html",
            vacancy=vacancy,
            graph_data=None,
            metrics={"total_nodes": 0, "total_edges": 0,
                     "company_nodes": 0, "skill_nodes": 0,
                     "job_nodes": 0, "location_nodes": 0,
                     "level_nodes": 0, "type_nodes": 0,
                     "degree": 0, "pagerank": 0},
        )

    G = load_enriched_graph()
    graph_data = get_vacancy_graph(vacancy_id, G) or {"nodes": [], "edges": []}
    metrics = get_graph_metrics(vacancy_id, G)

    # Tambah pelamar + skill mereka ke graph
    seen_ids = set(n["data"]["id"] for n in graph_data["nodes"])
    vacancy_node_id = f"vacancy_{vacancy_id}"

    # Kumpulkan skill wajib dari lowongan — untuk cross-connect dengan skill pelamar
    vacancy_skill_ids = set()
    for e in graph_data["edges"]:
        src, tgt = e["data"].get("source"), e["data"].get("target")
        if src == vacancy_node_id and e["data"].get("label") == "REQUIRES_SKILL":
            vacancy_skill_ids.add(tgt)

    try:
        from src.application_service import get_applications_for_vacancy
        from src.db_service import get_connection
        conn = get_connection()
        for app in get_applications_for_vacancy(vacancy_id):
            uid = app.get("user_id", "")
            if not uid or not uid.isdigit():
                continue
            if not conn:
                break
            try:
                c = conn.cursor()
                c.execute("SELECT full_name, skills FROM app.job_seeker_profiles WHERE user_id = %s", (int(uid),))
                row = c.fetchone()
                c.close()
                if not row:
                    continue
                name, skills_raw = row
                app_node_id = f"applicant_{uid}"
                if app_node_id not in seen_ids:
                    seen_ids.add(app_node_id)
                    graph_data["nodes"].append({
                        "data": {"id": app_node_id, "label": name or f"Pelamar #{uid}", "type": "applicant"}
                    })
                    graph_data["edges"].append({
                        "data": {"source": vacancy_node_id, "target": app_node_id, "label": "DILAMAR"}
                    })
                for sk in (skills_raw or []):
                    sk = sk.strip().lower()
                    if not sk:
                        continue
                    sk_id = f"skill_{sk.replace(' ', '_')}"
                    if sk_id not in seen_ids:
                        seen_ids.add(sk_id)
                        graph_data["nodes"].append({
                            "data": {"id": sk_id, "label": sk, "type": "skill"}
                        })
                    graph_data["edges"].append({
                        "data": {"source": app_node_id, "target": sk_id, "label": "PUNYA_SKILL"}
                    })
                    # Cross-connect: jika skill pelamar cocok dengan skill wajib lowongan
                    if sk_id in vacancy_skill_ids:
                        graph_data["edges"].append({
                            "data": {"source": sk_id, "target": app_node_id, "label": "MATCH"}
                        })
            except Exception:
                continue
        if conn:
            conn.close()
    except Exception as e:
        print(f"[!] Gagal muat pelamar ke graph: {e}")

    return render_template(
        "employer/detail.html",
        vacancy=vacancy,
        graph_data=graph_data,
        metrics=metrics,
    )


# === Edit / Delete Vacancy ===

@employer_bp.route("/vacancies/<vacancy_id>/edit", methods=["GET", "POST"])
@login_required
@employer_required
def edit_vacancy_page(vacancy_id):
    vacancy = get_vacancy(vacancy_id)
    if not vacancy or vacancy.get("historical"):
        return "Lowongan tidak ditemukan", 404

    if request.method == "POST":
        data = {
            "job_title": request.form.get("job_title", ""),
            "company": request.form.get("company", ""),
            "description": request.form.get("description", ""),
            "skills": request.form.get("skills", ""),
            "salary_min": request.form.get("salary_min", ""),
            "salary_max": request.form.get("salary_max", ""),
            "job_level": request.form.get("job_level", ""),
            "job_type": request.form.get("job_type", ""),
            "location": request.form.get("location", ""),
        }
        updated = update_vacancy(vacancy_id, data)
        if updated:
            flash("Lowongan berhasil diperbarui.", "success")
        else:
            flash("Gagal memperbarui lowongan.", "danger")
        return redirect(url_for("employer.vacancy_detail_page", vacancy_id=vacancy_id))

    return render_template("employer/edit.html", vacancy=vacancy)


@employer_bp.route("/vacancies/<vacancy_id>/delete", methods=["POST"])
@login_required
@employer_required
def delete_vacancy_route(vacancy_id):
    vacancy = get_vacancy(vacancy_id)
    if not vacancy or vacancy.get("historical"):
        flash("Lowongan tidak ditemukan atau tidak dapat dihapus.", "danger")
        return redirect(url_for("employer.vacancies_page"))

    try:
        if delete_vacancy(vacancy_id):
            flash("Lowongan berhasil dihapus.", "success")
        else:
            flash("Gagal menghapus lowongan. Coba lagi.", "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("employer.vacancies_page"))


# === Knowledge Graph API Endpoints ===

@employer_bp.route("/api/analyze-title", methods=["POST"])
@login_required
@employer_required
def api_analyze_title():
    data = request.get_json(force=True)
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Judul pekerjaan diperlukan"}), 400

    G = _load_clean_graph()
    result = analyze_job_title(title, G)
    return jsonify(result)


@employer_bp.route("/api/validate-skills", methods=["POST"])
@login_required
@employer_required
def api_validate_skills():
    data = request.get_json(force=True)
    title = data.get("title", "").strip()
    skills = data.get("skills", [])

    G = _load_clean_graph()
    result = validate_job_skills(title, skills, G)
    return jsonify(result)


@employer_bp.route("/api/talent-availability", methods=["POST"])
@login_required
@employer_required
def api_talent_availability():
    data = request.get_json(force=True)
    skills = data.get("skills", [])

    G = _load_clean_graph()
    result = estimate_talent_availability(skills, G)
    return jsonify(result)


@employer_bp.route("/api/graph-subgraph", methods=["POST"])
@login_required
@employer_required
def api_graph_subgraph():
    data = request.get_json(force=True)
    title = data.get("title", "").strip()
    skills = data.get("skills", [])

    G = _load_clean_graph()
    elements = build_skill_subgraph(title, skills, G)
    return jsonify({"elements": elements})


# === API Endpoints ===

@employer_bp.route("/api/jobs", methods=["POST"])
@login_required
@employer_required
def api_create_job():
    data = request.get_json(force=True)
    if not data or not data.get("job_title") or not data.get("company"):
        return jsonify({"error": "Judul pekerjaan dan perusahaan diperlukan"}), 400

    vacancy = create_vacancy(data, user_id=current_user.id)
    return jsonify({"success": True, "vacancy": vacancy}), 201


@employer_bp.route("/api/jobs", methods=["GET"])
@login_required
@employer_required
def api_list_jobs():
    search = request.args.get("search", "")
    company = request.args.get("company", "")
    vacancies = list_vacancies(search=search, company=company)
    return jsonify({"vacancies": vacancies})


@employer_bp.route("/api/jobs/<vacancy_id>", methods=["GET"])
@login_required
@employer_required
def api_get_job(vacancy_id):
    vacancy = get_vacancy(vacancy_id)
    if not vacancy:
        return jsonify({"error": "Lowongan tidak ditemukan"}), 404
    return jsonify(vacancy)


@employer_bp.route("/api/jobs/<vacancy_id>/graph", methods=["GET"])
@login_required
@employer_required
def api_get_job_graph(vacancy_id):
    G = load_enriched_graph()
    graph_data = get_vacancy_graph(vacancy_id, G)
    if graph_data is None:
        return jsonify({"error": "Lowongan tidak ditemukan"}), 404

    metrics = get_graph_metrics(vacancy_id, G)
    return jsonify({"elements": graph_data, "metrics": metrics})


@employer_bp.route("/api/jobs/<vacancy_id>/matching", methods=["GET"])
@login_required
@employer_required
def api_get_job_matching(vacancy_id):
    vacancy = get_vacancy(vacancy_id)
    if not vacancy:
        return jsonify({"error": "Lowongan tidak ditemukan"}), 404
    if vacancy.get("historical"):
        return jsonify({"error": "Akses ditolak"}), 403

    try:
        from src.application_service import get_applications_for_vacancy
        from src.db_service import get_connection

        vacancy_skills = set(s.lower().strip() for s in vacancy.get("skills", []))
        applicants = get_applications_for_vacancy(vacancy_id)

        results = []
        conn = get_connection()
        for app in applicants:
            uid = app.get("user_id", "")
            if not uid or not uid.isdigit():
                continue
            if not conn:
                continue
            try:
                c = conn.cursor()
                c.execute("SELECT full_name, skills, experience_years, education, expected_salary_min FROM app.job_seeker_profiles WHERE user_id = %s", (int(uid),))
                row = c.fetchone()
                c.close()
                if not row:
                    continue
                name, skills_raw, exp, edu, salary = row
                profile_skills = set(s.lower().strip() for s in (skills_raw or []) if s.strip())

                if vacancy_skills and profile_skills:
                    matched = vacancy_skills & profile_skills
                    match_count = len(matched)
                    score = int(match_count / max(len(vacancy_skills), 1) * 100)
                else:
                    matched = set()
                    score = 0

                results.append({
                    "full_name": name or f"Pelamar #{uid}",
                    "skills": sorted(profile_skills),
                    "matched_skills": sorted(matched),
                    "experience": exp or 0,
                    "education": edu or "",
                    "expected_salary": salary or 0,
                    "match_percent": min(100, score),
                    "user_id": uid,
                })
            except Exception:
                continue

        if conn:
            conn.close()

        results.sort(key=lambda x: x["match_percent"], reverse=True)
        return jsonify({"results": results})
    except Exception as e:
        print(f"[!] Matching error for {vacancy_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"results": [], "error": str(e)}), 200


# === Historical Job Search APIs ===

@employer_bp.route("/api/search-titles", methods=["GET"])
@login_required
@employer_required
def api_search_titles():
    query = request.args.get("q", "").strip()
    if not query or len(query) < 2:
        return jsonify([])
    results = search_job_titles(query)
    return jsonify(results)


@employer_bp.route("/api/all-titles", methods=["GET"])
@login_required
@employer_required
def api_all_titles():
    titles = get_all_job_titles()
    return jsonify(titles)


@employer_bp.route("/api/skill-detail", methods=["POST"])
@login_required
@employer_required
def api_skill_detail():
    data = request.get_json(force=True)
    skill_name = data.get("skill", "").strip().lower()
    if not skill_name:
        return jsonify({"error": "Skill diperlukan"}), 400

    G = _load_clean_graph()
    related_jobs = []
    related_companies = []

    for n, d in G.nodes(data=True):
        if d.get("type") != "job":
            continue
        skills_raw = (d.get("skills_raw") or "").lower()
        if skill_name in skills_raw:
            related_jobs.append({
                "title": d.get("job_title", ""),
                "company": d.get("company", ""),
            })
            company_name = d.get("company", "")
            if company_name and company_name not in [c["name"] for c in related_companies]:
                related_companies.append({"name": company_name})

    # Count skill frequency in graph
    skill_count = 0
    for _, _, edata in G.edges(data=True):
        pass
    for n, d in G.nodes(data=True):
        if d.get("type") == "job":
            skills_raw = (d.get("skills_raw") or "").lower()
            if skill_name in skills_raw:
                skill_count += 1

    return jsonify({
        "skill": skill_name,
        "frequency": skill_count,
        "related_jobs": sorted(related_jobs, key=lambda x: x["title"])[:20],
        "related_companies": sorted(related_companies, key=lambda x: x["name"])[:10],
        "candidate_estimate": skill_count * 3,
    })


# === Dashboard Graph API ===

@employer_bp.route("/api/dashboard/graph", methods=["GET"])
@login_required
@employer_required
def api_dashboard_graph():
    user_id = current_user.id
    elements = {"nodes": [], "edges": []}
    seen_ids = set()
    seen_edges = set()

    chart_data = {
        "skills": {}, "locations": {}, "levels": {},
    }

    try:
        from src.db_service import get_connection
        conn = get_connection()
        if conn:
            c = conn.cursor()
            company_node_id = "company_center"

            c.execute("SELECT id, name, industry, location FROM app.companies WHERE user_id = %s", (user_id,))
            company_row = c.fetchone()
            company_name = company_row[1] if company_row else "Perusahaan Saya"

            c.execute("""
                SELECT id, job_title, skills, job_level, job_type, location
                FROM app.vacancies
                WHERE user_id = %s OR company = %s
                ORDER BY created_at DESC
            """, (user_id, company_name))
            vacancies = c.fetchall()

            company_industry = company_row[2] if company_row and company_row[2] else ""
            company_loc = company_row[3] if company_row and company_row[3] else ""
            company_desc = company_name
            if company_industry:
                company_desc += f" · {company_industry}"
            if company_loc:
                company_desc += f" · {company_loc}"

            elements["nodes"].append({
                "group": "nodes",
                "data": {"id": company_node_id, "label": company_name, "type": "company", "desc": company_desc}
            })
            seen_ids.add(company_node_id)

            for vac in vacancies:
                vid, title, vac_skills, level, jtype, location = vac
                vac_node_id = f"vac_{vid}"
                if vac_node_id in seen_ids:
                    continue
                seen_ids.add(vac_node_id)

                vac_skill_count = len([s for s in (vac_skills or []) if s.strip()]) if vac_skills else 0
                vac_desc = title or "Unknown"
                vac_desc += f" · {level}" if level else ""
                vac_desc += f" · {location}" if location else ""
                vac_desc += f" · {vac_skill_count} skill"

                elements["nodes"].append({
                    "group": "nodes",
                    "data": {
                        "id": vac_node_id, "label": title or "Unknown",
                        "type": "vacancy", "level": level or "", "location": location or "",
                        "desc": vac_desc
                    }
                })
                ek_mb = f"company_node_id||{vac_node_id}||MEMBUKA"
                if ek_mb not in seen_edges:
                    seen_edges.add(ek_mb)
                    elements["edges"].append({
                        "group": "edges",
                        "data": {"id": ek_mb, "source": company_node_id, "target": vac_node_id, "label": "MEMBUKA"}
                    })

                # Chart: location
                loc = location.strip() if location else "Tidak diketahui"
                chart_data["locations"][loc] = chart_data["locations"].get(loc, 0) + 1
                # Chart: level
                lvl = level.strip() if level else "Tidak diketahui"
                chart_data["levels"][lvl] = chart_data["levels"].get(lvl, 0) + 1

                # Track vacancy skill IDs for MATCH detection
                vac_skill_ids = set()
                for sk in (vac_skills or []):
                    sk = sk.strip()
                    if not sk:
                        continue
                    sk_id = f"skill_{sk.lower().replace(' ', '_').replace('-', '_')}"
                    vac_skill_ids.add(sk_id)
                    if sk_id not in seen_ids:
                        seen_ids.add(sk_id)
                        elements["nodes"].append({
                            "group": "nodes",
                            "data": {"id": sk_id, "label": sk, "type": "skill", "desc": f"Skill: {sk}"}
                        })
                    ek_rs = f"{vac_node_id}||{sk_id}||REQUIRES_SKILL"
                    if ek_rs not in seen_edges:
                        seen_edges.add(ek_rs)
                        elements["edges"].append({
                            "group": "edges",
                            "data": {"id": ek_rs, "source": vac_node_id, "target": sk_id, "label": "REQUIRES_SKILL"}
                        })
                    # Chart: skill frequency
                    chart_data["skills"][sk.lower()] = chart_data["skills"].get(sk.lower(), 0) + 1

                c.execute("""
                    SELECT a.id, a.user_id, p.full_name, p.skills, a.status
                    FROM app.applications a
                    LEFT JOIN app.job_seeker_profiles p ON a.user_id = p.user_id
                    WHERE a.vacancy_id = %s
                """, (vid,))
                applicants = c.fetchall()

                for app_row in applicants:
                    app_id, app_user_id, full_name, app_skills, app_status = app_row
                    app_node_id = f"applicant_{app_user_id}"
                    app_status_label = app_status.capitalize() if app_status else "Baru"
                    app_match_count = 0
                    if app_node_id not in seen_ids:
                        seen_ids.add(app_node_id)
                        elements["nodes"].append({
                            "group": "nodes",
                            "data": {
                                "id": app_node_id,
                                "label": full_name or f"Pelamar #{app_user_id}",
                                "type": "applicant",
                                "status": app_status_label,
                                "desc": ""
                            }
                        })
                    ek_dl = f"{vac_node_id}||{app_node_id}||DILAMAR"
                    if ek_dl not in seen_edges:
                        seen_edges.add(ek_dl)
                        elements["edges"].append({
                            "group": "edges",
                            "data": {"id": ek_dl, "source": vac_node_id, "target": app_node_id, "label": "DILAMAR"}
                        })

                    for sk in (app_skills or []):
                        sk = sk.strip()
                        if not sk:
                            continue
                        sk_id = f"skill_{sk.lower().replace(' ', '_').replace('-', '_')}"
                        if sk_id not in seen_ids:
                            seen_ids.add(sk_id)
                            elements["nodes"].append({
                                "group": "nodes",
                                "data": {"id": sk_id, "label": sk, "type": "skill", "desc": sk}
                            })
                        ek_ps = f"{app_node_id}||{sk_id}||PUNYA_SKILL"
                        if ek_ps not in seen_edges:
                            seen_edges.add(ek_ps)
                            elements["edges"].append({
                                "group": "edges",
                                "data": {"id": ek_ps, "source": app_node_id, "target": sk_id, "label": "PUNYA_SKILL"}
                            })

                        # MATCH edge: if applicant skill matches vacancy required skill
                        if sk_id in vac_skill_ids:
                            app_match_count += 1
                            ek_mt = f"{sk_id}||{app_node_id}||MATCH"
                            if ek_mt not in seen_edges:
                                seen_edges.add(ek_mt)
                                elements["edges"].append({
                                    "group": "edges",
                                    "data": {"id": ek_mt, "source": sk_id, "target": app_node_id, "label": "MATCH"}
                                })

                        chart_data["skills"][sk.lower()] = chart_data["skills"].get(sk.lower(), 0) + 1

                    # Update applicant desc with match count
                    for n in elements["nodes"]:
                        if n["data"].get("id") == app_node_id:
                            base = n["data"]["label"]
                            match_str = f"{app_match_count} cocok" if app_match_count > 0 else "belum ada kecocokan"
                            n["data"]["desc"] = f"{base} · {app_status_label} · {match_str}"
                            break

                # Update vacancy desc with applicant count
                app_count_for_vac = len(applicants)
                for n in elements["nodes"]:
                    if n["data"].get("id") == vac_node_id:
                        cur = n["data"].get("desc", "")
                        n["data"]["desc"] = f"{cur} · {app_count_for_vac} pelamar"
                        break

            c.close()
            conn.close()
    except Exception as e:
        print(f"[!] Dashboard graph API error: {e}")

    # Sort chart data
    sorted_skills = sorted(chart_data["skills"].items(), key=lambda x: x[1], reverse=True)[:10]
    sorted_locations = sorted(chart_data["locations"].items(), key=lambda x: x[1], reverse=True)[:10]
    sorted_levels = sorted(chart_data["levels"].items(), key=lambda x: x[1], reverse=True)

    # Count stats
    unique_applicants = set()
    own_vacancy_count = 0
    for n in elements["nodes"]:
        if n["data"]["type"] == "applicant":
            unique_applicants.add(n["data"]["id"])
        elif n["data"]["type"] == "vacancy":
            own_vacancy_count += 1

    return jsonify({
        "elements": elements,
        "node_count": len(elements["nodes"]),
        "edge_count": len(elements["edges"]),
        "own_vacancies": own_vacancy_count,
        "total_applicants": len(unique_applicants),
        "chart_data": {
            "skills": [{"skill": s, "frequency": c} for s, c in sorted_skills],
            "locations": [{"location": l, "job_count": c} for l, c in sorted_locations],
            "levels": [{"level": l, "count": c} for l, c in sorted_levels],
        },
    })


# === Analytics APIs ===

@employer_bp.route("/api/analytics/skills", methods=["GET"])
@login_required
@employer_required
def api_analytics_skills():
    top_n = request.args.get("top_n", 20, type=int)
    G = load_enriched_graph()
    data = get_analytics_skills(G, top_n)
    return jsonify(data)


@employer_bp.route("/api/analytics/companies", methods=["GET"])
@login_required
@employer_required
def api_analytics_companies():
    top_n = request.args.get("top_n", 20, type=int)
    G = load_enriched_graph()
    data = get_analytics_companies(G, top_n)
    return jsonify(data)


@employer_bp.route("/api/analytics/locations", methods=["GET"])
@login_required
@employer_required
def api_analytics_locations():
    top_n = request.args.get("top_n", 20, type=int)
    G = load_enriched_graph()
    data = get_analytics_locations(G, top_n)
    return jsonify(data)


@employer_bp.route("/api/analytics/levels", methods=["GET"])
@login_required
@employer_required
def api_analytics_levels():
    G = load_enriched_graph()
    data = get_analytics_levels(G)
    return jsonify(data)


# === Applicant Management ===

@employer_bp.route("/vacancies/<vacancy_id>/applicants")
@login_required
@employer_required
def view_applicants(vacancy_id):
    from src.application_service import get_applications_for_vacancy
    from src.employer_service import get_vacancy
    from src.db_service import get_profile_by_user_id
    vacancy = get_vacancy(vacancy_id)
    if not vacancy:
        return "Lowongan tidak ditemukan", 404
    if vacancy.get("historical") or not vacancy.get("id"):
        flash("Lowongan tidak memiliki akses pelamar.", "danger")
        return redirect(url_for("employer.vacancies_page"))
    applicants = get_applications_for_vacancy(vacancy_id)
    for a in applicants:
        a["profile"] = get_profile_by_user_id(int(a["user_id"])) if a["user_id"].isdigit() else None
    return render_template("employer/applicants.html", vacancy=vacancy, applicants=applicants)


@employer_bp.route("/api/applications/<app_id>/status", methods=["POST"])
@login_required
@employer_required
def api_update_application_status(app_id):
    from src.application_service import update_application_status
    from src.notification_service import notify_application_status
    data = request.get_json(force=True)
    status = data.get("status", "")
    if status not in ("reviewed", "accepted", "rejected"):
        return jsonify({"error": "Status tidak valid"}), 400
    app_obj = update_application_status(app_id, status)
    if not app_obj:
        return jsonify({"error": "Lamaran tidak ditemukan"}), 404
    # Notify job seeker
    user_id = int(app_obj.get("user_id", 0))
    vacancy_id = app_obj.get("vacancy_id", "")
    if user_id and vacancy_id:
        from src.employer_service import get_vacancy
        v = get_vacancy(vacancy_id)
        v_title = v.get("job_title", "Lowongan") if v else "Lowongan"
        notify_application_status(user_id, status, v_title, vacancy_id)
    return jsonify({"success": True, "application": app_obj})


@employer_bp.route("/api/messages/send", methods=["POST"])
@login_required
@employer_required
def api_send_message():
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
            c.execute("SELECT job_title FROM app.vacancies WHERE id = %s", (vacancy_id,))
            vrow = c.fetchone()
            vacancy_title = vrow[0] if vrow else vacancy_id
            c.execute("SELECT name FROM app.companies WHERE user_id = %s", (current_user.id,))
            crow = c.fetchone()
            sender_name = crow[0] if crow else "Perusahaan"
            c.close()
            conn.close()
            notify_new_message(receiver_id, sender_name, vacancy_title, vacancy_id)
    except Exception as e:
        print(f"[!] Gagal mengirim notifikasi pesan: {e}")

    return jsonify({"success": True, "message": result})


@employer_bp.route("/api/messages/<int:applicant_id>/<vacancy_id>", methods=["GET"])
@login_required
@employer_required
def api_get_conversation(applicant_id, vacancy_id):
    from src.message_service import get_conversation
    messages = get_conversation(vacancy_id, current_user.id, applicant_id)
    return jsonify({"messages": messages})


@employer_bp.route("/api/notifications", methods=["GET"])
@login_required
@employer_required
def employer_api_get_notifications():
    from src.notification_service import get_notifications, get_unread_count
    limit = request.args.get("limit", 20, type=int)
    notifs = get_notifications(current_user.id, limit)
    unread = get_unread_count(current_user.id)
    return jsonify({"notifications": notifs, "unread": unread})


@employer_bp.route("/api/notifications/read/<int:notif_id>", methods=["POST"])
@login_required
@employer_required
def employer_api_read_notification(notif_id):
    from src.notification_service import read_notification
    read_notification(notif_id, current_user.id)
    return jsonify({"success": True})


@employer_bp.route("/api/notifications/read-all", methods=["POST"])
@login_required
@employer_required
def employer_api_read_all_notifications():
    from src.notification_service import read_all_notifications
    read_all_notifications(current_user.id)
    return jsonify({"success": True})
