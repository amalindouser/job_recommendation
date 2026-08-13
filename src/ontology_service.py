import os
import json
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple, Any


ONTOLOGY_DIR = Path(__file__).parent.parent / "data" / "ontology"
ONTOLOGY_JSON = ONTOLOGY_DIR / "job_ontology.json"
ONET_ONTOLOGY_JSON = ONTOLOGY_DIR / "onet_ontology.json"
ESCO_ONTOLOGY_JSON = ONTOLOGY_DIR / "esco_ontology.json"


BUILTIN_ONTOLOGY = {
    "skill_relations": {
        "related_to": [
            ["python", "object_oriented_programming"],
            ["python", "scripting"],
            ["java", "object_oriented_programming"],
            ["java", "jvm"],
            ["javascript", "typescript"],
            ["react", "frontend_development"],
            ["react", "ui_development"],
            ["node.js", "backend_development"],
            ["node.js", "server_side_javascript"],
            ["docker", "containerization"],
            ["kubernetes", "container_orchestration"],
            ["sql", "relational_database"],
            ["nosql", "non_relational_database"],
            ["mongodb", "document_database"],
            ["aws", "cloud_computing"],
            ["azure", "cloud_computing"],
            ["gcp", "cloud_computing"],
            ["machine_learning", "deep_learning"],
            ["machine_learning", "artificial_intelligence"],
            ["tensorflow", "deep_learning_framework"],
            ["pytorch", "deep_learning_framework"],
            ["git", "version_control"],
            ["agile", "scrum"],
            ["rest_api", "api_development"],
            ["graphql", "api_development"],
            ["microservices", "distributed_systems"],
            ["data_analysis", "data_science"],
            ["statistics", "data_science"],
            ["communication", "interpersonal_skills"],
            ["leadership", "management"],
            ["project_management", "agile_project_management"],
            ["customer_service", "client_relations"],
            ["sales", "business_development"],
            ["marketing", "digital_marketing"],
            ["accounting", "financial_reporting"],
            ["nursing", "patient_care"],
            ["surgery", "surgical_procedures"],
            ["pharmacy", "medication_management"],
            ["supply_chain", "logistics"],
            ["quality_control", "quality_assurance"],
            ["data_engineering", "etl"],
            ["devops", "ci_cd"],
            ["cybersecurity", "information_security"],
            ["networking", "network_infrastructure"],
        ],
        "substitutes": [
            ["tensorflow", "pytorch"],
            ["aws", "azure"],
            ["aws", "gcp"],
            ["azure", "gcp"],
            ["mongodb", "cassandra"],
            ["mysql", "postgresql"],
            ["react", "vue"],
            ["react", "angular"],
            ["jenkins", "github_actions"],
            ["jenkins", "gitlab_ci"],
            ["docker", "podman"],
            [" Kubernetes", "docker_swarm"],
            ["python", "r"],
            ["javascript", "typescript"],
            ["java", "csharp"],
            ["java", "kotlin"],
            ["slack", "microsoft_teams"],
            ["jira", "asana"],
            ["jira", "trello"],
            ["tableau", "power_bi"],
            ["tableau", "looker"],
        ],
        "prerequisite_of": [
            ["python", "machine_learning"],
            ["python", "deep_learning"],
            ["python", "data_science"],
            ["java", "spring"],
            ["java", "android_development"],
            ["javascript", "react"],
            ["javascript", "node.js"],
            ["javascript", "vue"],
            ["sql", "data_analysis"],
            ["sql", "data_science"],
            ["docker", "kubernetes"],
            ["docker", "container_orchestration"],
            ["networking", "cybersecurity"],
            ["statistics", "machine_learning"],
            ["linear_algebra", "machine_learning"],
            ["calculus", "machine_learning"],
            ["git", "devops"],
            ["linux", "devops"],
            ["linux", "cybersecurity"],
            ["html", "frontend_development"],
            ["css", "frontend_development"],
            ["accounting_basics", "financial_analysis"],
            ["medical_terminology", "nursing"],
            ["customer_service", "sales"],
            ["communications", "public_relations"],
            ["data_analysis", "data_science"],
            ["machine_learning", "deep_learning"],
            ["deep_learning", "natural_language_processing"],
            ["deep_learning", "computer_vision"],
        ],
    },
    "industry_classifications": {
        "technology": {
            "aliases": ["tech", "information_technology", "software", "it"],
            "typical_skills": ["python", "java", "javascript", "sql", "git", "agile",
                               "cloud_computing", "docker", "rest_api", "algorithms"],
            "typical_jobs": ["software_engineer", "data_scientist", "devops_engineer",
                              "product_manager", "qa_engineer", "backend_developer",
                              "frontend_developer", "full_stack_developer", "it_support"]
        },
        "healthcare": {
            "aliases": ["medical", "health", "clinical", "hospital"],
            "typical_skills": ["patient_care", "nursing", "medical_terminology",
                               "surgery", "pharmacy", "diagnostics", "emr",
                               "clinical_research", "anatomy", "physiology"],
            "typical_jobs": ["registered_nurse", "doctor", "pharmacist",
                              "medical_assistant", "radiologist", "surgeon",
                              "physical_therapist", "medical_researcher"]
        },
        "finance": {
            "aliases": ["financial", "banking", "insurance", "accounting"],
            "typical_skills": ["accounting", "financial_analysis", "risk_management",
                               "auditing", "tax", "budgeting", "forecasting",
                               "compliance", "financial_reporting", "excel"],
            "typical_jobs": ["accountant", "financial_analyst", "auditor",
                              "risk_manager", "tax_specialist", "investment_banker",
                              "financial_advisor", "compliance_officer"]
        },
        "sales_retail": {
            "aliases": ["retail", "sales", "ecommerce"],
            "typical_skills": ["customer_service", "sales", "negotiation",
                               "merchandising", "inventory_management", "communication",
                               "leadership", "time_management", "problem_solving"],
            "typical_jobs": ["sales_associate", "store_manager", "account_executive",
                              "sales_representative", "retail_manager", "cashier"]
        },
        "manufacturing": {
            "aliases": ["manufacturing", "production", "industrial", "factory"],
            "typical_skills": ["quality_control", "lean_manufacturing", "six_sigma",
                               "supply_chain", "logistics", "safety", "autocad",
                               "plc", "process_improvement", "inventory_management"],
            "typical_jobs": ["production_manager", "quality_engineer", "supply_chain_analyst",
                              "manufacturing_engineer", "plant_manager", "safety_officer"]
        },
        "construction": {
            "aliases": ["construction", "civil_engineering", "architecture"],
            "typical_skills": ["project_management", "autocad", "blueprint_reading",
                               "site_supervision", "safety", "estimating",
                               "scheduling", "contracts", "building_codes"],
            "typical_jobs": ["project_manager", "construction_superintendent",
                              "civil_engineer", "architect", "estimator",
                              "site_supervisor", "construction_manager"]
        },
        "education": {
            "aliases": ["education", "teaching", "academic", "training"],
            "typical_skills": ["teaching", "curriculum_development", "assessment",
                               "classroom_management", "educational_technology",
                               "communication", "mentoring", "research"],
            "typical_jobs": ["teacher", "professor", "instructional_designer",
                              "school_administrator", "trainer", "education_consultant"]
        },
        "hospitality": {
            "aliases": ["hospitality", "hotel", "restaurant", "tourism", "food_service"],
            "typical_skills": ["customer_service", "food_safety", "scheduling",
                               "inventory_management", "event_planning", "communication",
                               "teamwork", "multitasking", "hospitality_management"],
            "typical_jobs": ["hotel_manager", "restaurant_manager", "chef",
                              "event_coordinator", "front_desk_agent", "food_service_manager"]
        },
        "logistics": {
            "aliases": ["logistics", "transportation", "supply_chain", "warehouse"],
            "typical_skills": ["supply_chain_management", "logistics", "inventory_management",
                               "warehouse_management", "transportation", "sap",
                               "data_analysis", "negotiation", "scheduling"],
            "typical_jobs": ["logistics_manager", "supply_chain_analyst", "warehouse_manager",
                              "transportation_manager", "procurement_specialist"]
        },
        "human_resources": {
            "aliases": ["hr", "human_resources", "recruitment", "talent"],
            "typical_skills": ["recruitment", "employee_relations", "payroll",
                               "benefits_administration", "compliance", "communication",
                               "conflict_resolution", "training", "leadership"],
            "typical_jobs": ["hr_manager", "recruiter", "hr_generalist",
                              "talent_acquisition_specialist", "benefits_administrator"]
        },
    },
    "job_qualifications": {
        "software_engineer": ["computer_science", "software_engineering", "information_technology"],
        "data_scientist": ["computer_science", "statistics", "mathematics", "data_science"],
        "registered_nurse": ["nursing", "bachelor_of_science_in_nursing"],
        "accountant": ["accounting", "finance", "business_administration"],
        "teacher": ["education", "teaching", "specific_subject_major"],
        "project_manager": ["business_administration", "engineering", "project_management"],
        "mechanical_engineer": ["mechanical_engineering", "engineering"],
        "electrical_engineer": ["electrical_engineering", "engineering"],
        "pharmacist": ["pharmacy", "pharmaceutical_sciences"],
        "lawyer": ["law", "legal_studies"],
        "doctor": ["medicine", "medical_degree"],
        "dentist": ["dentistry", "dental_surgery"],
        "architect": ["architecture", "architectural_engineering"],
        "financial_analyst": ["finance", "accounting", "economics", "business"],
        "marketing_manager": ["marketing", "business_administration", "communications"],
    },
    "job_certifications": {
        "software_engineer": ["aws_certified_developer", "google_professional_cloud_developer",
                              "microsoft_certified_azure_developer", "oracle_java_certified"],
        "data_scientist": ["aws_certified_data_analytics", "google_professional_data_engineer",
                           "azure_data_scientist", "certified_analytics_professional"],
        "project_manager": ["pmp", "prince2", "certified_scrum_master", "safe_agilist"],
        "accountant": ["cpa", "cma", "acca", "certified_internal_auditor"],
        "cybersecurity_analyst": ["cissp", "ceh", "comptia_security_plus", "cism"],
        "network_engineer": ["ccna", "ccnp", "comptia_network_plus", "juniper_jncia"],
        "devops_engineer": ["aws_certified_devops", "google_professional_cloud_devops",
                            "docker_certified", "ckad", "cka"],
        "registered_nurse": ["rn_license", "ccrn", "cne", "cmsrn"],
        "human_resources": ["phr", "shrm_cp", "shrm_scp", "ccp"],
        "six_sigma_belt": ["six_sigma_green_belt", "six_sigma_black_belt", "lean_six_sigma"],
    },
    "job_to_skills": {
        "software_engineer": ["python", "java", "git", "agile", "rest_api", "sql",
                              "docker", "algorithms", "data_structures", "testing",
                              "problem_solving", "teamwork", "communication"],
        "data_scientist": ["python", "machine_learning", "statistics", "sql",
                           "data_visualization", "deep_learning", "r", "linear_algebra",
                           "big_data", "nlp", "communication", "critical_thinking"],
        "registered_nurse": ["patient_care", "nursing", "medical_terminology",
                             "emr", "critical_thinking", "communication", "teamwork",
                             "attention_to_detail", "time_management", "compassion"],
        "project_manager": ["project_management", "agile", "scrum", "leadership",
                            "communication", "risk_management", "budgeting",
                            "scheduling", "teamwork", "problem_solving"],
        "accountant": ["accounting", "financial_reporting", "auditing", "tax",
                       "excel", "attention_to_detail", "analytical_skills",
                       "time_management", "communication", "ethics"],
        "sales_representative": ["sales", "negotiation", "customer_service",
                                  "communication", "leadership", "time_management",
                                  "problem_solving", "teamwork", "crm", "presentation"],
        "marketing_manager": ["marketing", "digital_marketing", "social_media",
                               "content_creation", "analytics", "seo", "communication",
                               "project_management", "creativity", "leadership"],
        "devops_engineer": ["devops", "docker", "kubernetes", "ci_cd", "linux",
                            "aws", "git", "python", "jenkins", "terraform",
                            "monitoring", "networking", "agile"],
        "teacher": ["teaching", "curriculum_development", "assessment",
                     "classroom_management", "communication", "patience",
                     "organization", "leadership", "creativity", "mentoring"],
        "store_manager": ["customer_service", "sales", "leadership",
                          "inventory_management", "scheduling", "communication",
                          "problem_solving", "teamwork", "merchandising",
                          "budgeting", "training"],
    },
}


class OntologyService:
    def __init__(self, data_path: Optional[Path] = None, auto_load_external: bool = True):
        self.data_path = data_path or ONTOLOGY_JSON
        self.external_sources: Dict[str, dict] = {}
        self.ontology = self._load()
        if auto_load_external:
            self.load_external_ontologies()

    def _load(self) -> dict:
        if self.data_path and self.data_path.exists():
            try:
                data = json.loads(self.data_path.read_text(encoding="utf-8"))
                print(f"[OK] Loaded ontology from {self.data_path}")
                return self._merge_with_builtin(data)
            except Exception as e:
                print(f"[!] Failed to load ontology file: {e}")
        print("[OK] Using built-in ontology")
        return dict(BUILTIN_ONTOLOGY)

    def load_external_ontologies(self) -> List[str]:
        loaded = []
        for name, path in [("O*NET", ONET_ONTOLOGY_JSON), ("ESCO", ESCO_ONTOLOGY_JSON)]:
            if path and path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self.external_sources[name] = data
                    loaded.append(name)
                except Exception as e:
                    print(f"[!] Failed to load {name} ontology: {e}")
        if loaded:
            print(f"[OK] Loaded external ontologies: {', '.join(loaded)}")
            self.ontology = self._merge_all()
        else:
            print("[OK] No external ontologies found, using built-in")
        return loaded

    def _merge_with_builtin(self, external: dict) -> dict:
        merged = {}
        for key in BUILTIN_ONTOLOGY:
            if key == "job_to_skills":
                merged[key] = dict(BUILTIN_ONTOLOGY[key])
            else:
                merged[key] = dict(BUILTIN_ONTOLOGY[key])
        for key in ("job_to_skills",):
            ext_val = external.get(key, {})
            if isinstance(ext_val, dict):
                for job_key, skills in ext_val.items():
                    if isinstance(skills, list) and skills:
                        existing = merged.get(key, {}).get(job_key, [])
                        if existing:
                            seen = set(s.lower() for s in existing)
                            merged_list = list(existing)
                            for s in skills:
                                sl = s.lower()
                                if sl not in seen:
                                    seen.add(sl)
                                    merged_list.append(s)
                            merged[key][job_key] = merged_list
                        else:
                            merged[key][job_key] = skills
        for key in ("skill_relations",):
            ext_val = external.get(key, {})
            if isinstance(ext_val, dict):
                for rel_type, pairs in ext_val.items():
                    if isinstance(pairs, list):
                        existing = merged.setdefault(key, {}).setdefault(rel_type, [])
                        existing_set = set(tuple(p) for p in existing)
                        for pair in pairs:
                            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                                keyed = tuple(pair)
                                if keyed not in existing_set:
                                    existing_set.add(keyed)
                                    existing.append(list(keyed))
        all_skill_names = external.get("all_skill_names", [])
        if all_skill_names:
            merged["all_skill_names"] = list(dict.fromkeys(all_skill_names))
        return merged

    def _merge_all(self) -> dict:
        merged = dict(BUILTIN_ONTOLOGY)
        for name, ext in self.external_sources.items():
            merged = self._merge_with_builtin_impl(merged, ext)
        return merged

    @staticmethod
    def _merge_with_builtin_impl(base: dict, overlay: dict) -> dict:
        result = {}
        for key in base:
            result[key] = base[key]
        for key in ("job_to_skills",):
            ext_val = overlay.get(key, {})
            if isinstance(ext_val, dict):
                for job_key, skills in ext_val.items():
                    if isinstance(skills, list) and skills:
                        existing = result.setdefault(key, {}).get(job_key, [])
                        if existing:
                            seen = set(s.lower() for s in existing)
                            merged = list(existing)
                            for s in skills:
                                sl = s.lower()
                                if sl not in seen:
                                    seen.add(sl)
                                    merged.append(s)
                            result[key][job_key] = merged
                        else:
                            result[key][job_key] = skills
        for key in ("skill_relations",):
            ext_val = overlay.get(key, {})
            if isinstance(ext_val, dict):
                for rel_type, pairs in ext_val.items():
                    if isinstance(pairs, list):
                        existing = result.setdefault(key, {}).setdefault(rel_type, [])
                        existing_set = set(tuple(p) for p in existing)
                        for pair in pairs:
                            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                                keyed = tuple(pair)
                                if keyed not in existing_set:
                                    existing_set.add(keyed)
                                    existing.append(list(keyed))
        all_names = overlay.get("all_skill_names", [])
        if all_names:
            result["all_skill_names"] = list(dict.fromkeys(all_names))
        return result

    def has_external_ontology(self, name: str = "") -> bool:
        if name:
            return name in self.external_sources
        return len(self.external_sources) > 0

    @staticmethod
    def _skill_variants(skill: str) -> List[str]:
        variants = [skill]
        s = skill.lower().strip()
        for sep in (".", "_", " "):
            if sep in s:
                variants.append(s.replace(sep, "."))
                variants.append(s.replace(sep, "_"))
                variants.append(s.replace(sep, " "))
        return list(set(variants))

    def get_related_skills(self, skill: str) -> List[str]:
        skill_lower = skill.lower().strip()
        related = set()
        variants = self._skill_variants(skill_lower)
        for s1, s2 in self.ontology.get("skill_relations", {}).get("related_to", []):
            for v in variants:
                if s1 == v:
                    related.add(s2)
                elif s2 == v:
                    related.add(s1)
        return list(related)

    def get_substitute_skills(self, skill: str) -> List[str]:
        skill_lower = skill.lower().strip()
        subs = set()
        variants = self._skill_variants(skill_lower)
        for s1, s2 in self.ontology.get("skill_relations", {}).get("substitutes", []):
            for v in variants:
                if s1 == v:
                    subs.add(s2)
                elif s2 == v:
                    subs.add(s1)
        return list(subs)

    def get_prerequisite_skills(self, skill: str) -> List[str]:
        skill_lower = skill.lower().strip()
        prereqs = set()
        variants = self._skill_variants(skill_lower)
        for s1, s2 in self.ontology.get("skill_relations", {}).get("prerequisite_of", []):
            for v in variants:
                if s2 == v:
                    prereqs.add(s1)
        return list(prereqs)

    def get_advanced_skills(self, skill: str) -> List[str]:
        skill_lower = skill.lower().strip()
        advanced = set()
        variants = self._skill_variants(skill_lower)
        for s1, s2 in self.ontology.get("skill_relations", {}).get("prerequisite_of", []):
            for v in variants:
                if s1 == v:
                    advanced.add(s2)
        return list(advanced)

    def get_skills_for_job(self, job_title: str) -> List[str]:
        key = self._normalize_job_title(job_title)
        direct = self.ontology.get("job_to_skills", {}).get(key, [])
        if direct:
            return direct
        for ext_name, ext_data in self.external_sources.items():
            ext_skills = ext_data.get("job_to_skills", {}).get(key, [])
            if ext_skills:
                return ext_skills
        best_key = self._fuzzy_match_job_title(key, list(self.ontology.get("job_to_skills", {}).keys()))
        if best_key:
            return self.ontology.get("job_to_skills", {}).get(best_key, [])
        for ext_name, ext_data in self.external_sources.items():
            ext_keys = list(ext_data.get("job_to_skills", {}).keys())
            best_ext = self._fuzzy_match_job_title(key, ext_keys)
            if best_ext:
                return ext_data.get("job_to_skills", {}).get(best_ext, [])
        return []

    @staticmethod
    def _fuzzy_match_job_title(normalized: str, candidates: List[str]) -> Optional[str]:
        if not candidates:
            return None
        n_words = set(normalized.split("_"))
        if not n_words:
            return None
        best_score = 0
        best = None
        for c in candidates:
            c_words = set(c.split("_"))
            if not c_words:
                continue
            overlap = len(n_words & c_words)
            score = overlap / max(len(n_words), len(c_words))
            if score > best_score:
                best_score = score
                best = c
        return best if best_score >= 0.3 else None

    def get_qualifications_for_job(self, job_title: str) -> List[str]:
        key = self._normalize_job_title(job_title)
        return self.ontology.get("job_qualifications", {}).get(key, [])

    def get_certifications_for_job(self, job_title: str) -> List[str]:
        key = self._normalize_job_title(job_title)
        return self.ontology.get("job_certifications", {}).get(key, [])

    def get_industry_for_job(self, job_title: str) -> Optional[str]:
        key = self._normalize_job_title(job_title)
        for industry, info in self.ontology.get("industry_classifications", {}).items():
            if key in info.get("typical_jobs", []):
                return industry
        return None

    def get_all_relations_for_skill(self, skill: str) -> Dict[str, List[str]]:
        return {
            "related_to": self.get_related_skills(skill),
            "substitutes": self.get_substitute_skills(skill),
            "prerequisite_of": self.get_prerequisite_skills(skill),
            "advanced_skills": self.get_advanced_skills(skill),
        }

    def get_industry_info(self, industry: str) -> Optional[dict]:
        for key, info in self.ontology.get("industry_classifications", {}).items():
            if key == industry or industry in info.get("aliases", []):
                return {**info, "id": key}
        return None

    def detect_industry_from_skills(self, skills: List[str]) -> List[Tuple[str, float]]:
        if not skills:
            return []
        skills_lower = {s.lower().strip() for s in skills}
        scores = []
        for industry, info in self.ontology.get("industry_classifications", {}).items():
            typical = {s.lower() for s in info.get("typical_skills", [])}
            if typical:
                overlap = len(skills_lower & typical)
                score = overlap / len(typical)
                if score > 0:
                    scores.append((industry, score))
        scores.sort(key=lambda x: -x[1])
        return scores

    def detect_industry_from_job_title(self, job_title: str) -> Optional[str]:
        key = self._normalize_job_title(job_title)
        for industry, info in self.ontology.get("industry_classifications", {}).items():
            for typical_job in info.get("typical_jobs", []):
                if typical_job in key or key in typical_job:
                    return industry
        return None

    def job_belongs_to_industries(self, job_title: str) -> List[str]:
        key = self._normalize_job_title(job_title)
        results = []
        for industry, info in self.ontology.get("industry_classifications", {}).items():
            if key in info.get("typical_jobs", []):
                results.append(industry)
                continue
            for typical_job in info.get("typical_jobs", []):
                if typical_job in key or key in typical_job:
                    results.append(industry)
                    break
        return results

    def search_skills(self, query: str, max_results: int = 20) -> List[str]:
        query_lower = query.lower().strip()
        all_skills = set()
        for name in self.ontology.get("all_skill_names", []):
            all_skills.add(name.replace("_", " "))
        for rel_list in self.ontology.get("skill_relations", {}).values():
            for s1, s2 in rel_list:
                all_skills.add(s1.replace("_", " "))
                all_skills.add(s2.replace("_", " "))
        for job_skills in self.ontology.get("job_to_skills", {}).values():
            for s in job_skills:
                all_skills.add(s.replace("_", " "))
        matches = [s for s in all_skills if query_lower in s.lower()]
        matches.sort()
        return matches[:max_results]

    @staticmethod
    def _normalize_job_title(title: str) -> str:
        t = title.lower().strip()
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = re.sub(r"\s+", "_", t.strip())
        t = re.sub(r"_(senior|junior|lead|staff|principal|associate|intern|manager|director|head)$", "", t)
        t = re.sub(r"^(senior|junior|lead|staff|principal|associate|intern|manager|director|head)_", "", t)
        for stop_word in ["senior", "junior", "lead", "staff", "principal", "associate",
                           "intern", "manager", "director", "head", "i", "ii", "iii", "iv", "v",
                           "1", "2", "3", "4", "5", "sr", "jr", "mid", "entry"]:
            t = t.replace(f"_{stop_word}_", "_")
            t = t.replace(f"_{stop_word}", "")
            t = t.replace(f"{stop_word}_", "")
        t = re.sub(r"_+", "_", t).strip("_")
        return t


_instance = None


def get_ontology(refresh: bool = False) -> OntologyService:
    global _instance
    if _instance is None or refresh:
        _instance = OntologyService()
    return _instance


def enrich_graph_with_ontology(G, ontology: Optional[OntologyService] = None) -> None:
    if ontology is None:
        ontology = get_ontology()
    new_nodes = 0
    new_edges = 0

    job_nodes = [(n, d) for n, d in G.nodes(data=True) if d.get("type") == "job"]

    for node_id, data in job_nodes:
        job_title = data.get("job_title", "").strip()
        if not job_title:
            continue

        normalized_title = OntologyService._normalize_job_title(job_title)

        # --- Industry ---
        industries = ontology.job_belongs_to_industries(job_title)
        if not industries:
            detected = ontology.detect_industry_from_job_title(job_title)
            if detected:
                industries = [detected]

        for ind in industries:
            ind_id = f"industry_{ind}"
            if not G.has_node(ind_id):
                G.add_node(ind_id, type="industry", label=ind.replace("_", " ").title())
                new_nodes += 1
            rel_key = f"belongs_to_{node_id}_{ind_id}"
            if not G.has_edge(node_id, ind_id):
                G.add_edge(node_id, ind_id, relation="BELONGS_TO", id=rel_key)
                new_edges += 1

        # --- Qualification ---
        quals = ontology.get_qualifications_for_job(job_title)
        for qual in quals:
            qual_id = f"qualification_{qual}"
            if not G.has_node(qual_id):
                qual_label = qual.replace("_", " ").title()
                G.add_node(qual_id, type="qualification", label=qual_label)
                new_nodes += 1
            rel_key = f"eligible_for_{qual_id}_{node_id}"
            if not G.has_edge(qual_id, node_id):
                G.add_edge(qual_id, node_id, relation="ELIGIBLE_FOR", id=rel_key)
                new_edges += 1

        # --- Certification ---
        certs = ontology.get_certifications_for_job(job_title)
        for cert in certs:
            cert_id = f"certification_{cert}"
            if not G.has_node(cert_id):
                cert_label = cert.replace("_", " ").title()
                G.add_node(cert_id, type="certification", label=cert_label)
                new_nodes += 1
            rel_key = f"requires_cert_{node_id}_{cert_id}"
            if not G.has_edge(node_id, cert_id):
                G.add_edge(node_id, cert_id, relation="REQUIRES_CERTIFICATION", id=rel_key)
                new_edges += 1

    # --- Skill-to-Skill relations ---
    skill_nodes = {}
    for n, d in G.nodes(data=True):
        if d.get("type") == "skill":
            label = d.get("label", n)
            skill_nodes[label.lower().strip()] = n

    for rel_type in ["related_to", "substitutes", "prerequisite_of"]:
        for s1, s2 in ontology.ontology.get("skill_relations", {}).get(rel_type, []):
            n1 = skill_nodes.get(s1)
            n2 = skill_nodes.get(s2)
            if n1 and n2:
                rel_key = f"{rel_type}_{n1}_{n2}"
                if not G.has_edge(n1, n2):
                    G.add_edge(n1, n2, relation=rel_type.upper(), id=rel_key)
                    new_edges += 1

    print(f"[OK] Ontology enrichment: added {new_nodes} nodes and {new_edges} edges")


if __name__ == "__main__":
    svc = get_ontology()
    print("Testing ontology service...")

    ext_status = " + ".join(svc.external_sources.keys()) if svc.external_sources else "built-in only"
    print(f"\nOntology sources: {ext_status}")
    print(f"  job_to_skills entries: {len(svc.ontology.get('job_to_skills', {}))}")
    print(f"  all_skill_names: {len(svc.ontology.get('all_skill_names', []))}")
    print(f"  skill_relations related_to: {len(svc.ontology.get('skill_relations', {}).get('related_to', []))}")

    tests = [
        "software engineer",
        "data scientist",
        "registered nurse",
        "Software Engineer Senior",
        "Data Scientist",
        "Python Developer",
        "Frontend Developer",
    ]
    for t in tests:
        skills = svc.get_skills_for_job(t)
        print(f"\nSkills for '{t}':")
        if skills:
            print(f"  {skills[:10]}{'...' if len(skills) > 10 else ''}")
        else:
            print(f"  (no direct mapping)")

    print("\nSearch skills for 'python':")
    print(f"  {svc.search_skills('python', max_results=8)}")

    print("\nRelated to 'python':")
    print(f"  {svc.get_related_skills('python')}")

    print("\nSubstitutes for 'tensorflow':")
    print(f"  {svc.get_substitute_skills('tensorflow')}")

    print("\nPrerequisites for 'machine_learning':")
    print(f"  {svc.get_prerequisite_skills('machine_learning')}")

    print("\nDetect industry from skills:")
    print(f"  {svc.detect_industry_from_skills(['python', 'docker', 'kubernetes', 'sql'])}")
