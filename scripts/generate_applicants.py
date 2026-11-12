"""
Generate a synthetic, anonymous applicant dataset for the job recommendation system.

Design goals
------------
1. Skills are sampled from the project's curated job-skill dictionary
   (``src.clean_skills.SKILL_CATEGORIES``) plus a small, documented set of
   high-frequency skills taken directly from job postings.
2. Applicants are conditioned on real job clusters (category, location, salary),
   so the data is relevant to the jobs the recommender actually serves.
3. IDs are anonymous (P-0001, ...). No names, emails, or phone numbers.
4. Output is reproducible via a seed and is written as CSV + JSON.

Usage
-----
    python scripts/generate_applicants.py --n 100 --seed 42

The first run builds a cache in ``data/applicants/.cache``. Later runs reuse it
unless the source data changes or ``--refresh-cache`` is passed.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import random
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Make ``src`` importable when the script is run from the repository root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.clean_skills import (  # noqa: E402
    SKILL_CATEGORIES,
    SKILL_CATEGORY_LABELS,
    normalize_skill,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
JOBS_DB = ROOT / "data" / "all_jobs_clean.db"
POSTINGS_CSV = ROOT / "data" / "postings_final.csv"
GRAPH_FILE = ROOT / "data" / "graph_jobs_clean.graphml"
OUTPUT_DIR = ROOT / "data" / "applicants"
CACHE_DIR = OUTPUT_DIR / ".cache"
CACHE_FILE = CACHE_DIR / "job_stats.json"
CACHE_VERSION = 1

# ---------------------------------------------------------------------------
# Unified category taxonomy
# ---------------------------------------------------------------------------
# Indonesian job data uses one taxonomy, LinkedIn postings use another.  We map
# both into a single, comparable set of 16 categories.
UNIFIED_CATEGORIES = [
    "Teknologi Informasi",
    "Teknik",
    "Penjualan & Pemasaran",
    "Keuangan & Akuntansi",
    "Sumber Daya Manusia",
    "Layanan Kesehatan",
    "Pendidikan & Pelatihan",
    "Perhotelan & Restoran",
    "Manufaktur & Produksi",
    "Konstruksi & Bangunan",
    "Seni, Media & Komunikasi",
    "Sains & Penelitian",
    "Pelayanan & Administrasi",
    "Hukum",
    "Manajemen & Bisnis",
    "Lainnya",
]

ID_TO_UNIFIED = {
    "Komputer/Teknologi Informasi": "Teknologi Informasi",
    "Teknik": "Teknik",
    "Penjualan / Pemasaran": "Penjualan & Pemasaran",
    "Akuntansi / Keuangan": "Keuangan & Akuntansi",
    "Sumber Daya Manusia/Personalia": "Sumber Daya Manusia",
    "Layanan Kesehatan": "Layanan Kesehatan",
    "Pendidikan/Pelatihan": "Pendidikan & Pelatihan",
    "Hotel/Restoran": "Perhotelan & Restoran",
    "Manufaktur": "Manufaktur & Produksi",
    "Bangunan/Konstruksi": "Konstruksi & Bangunan",
    "Seni/Media/Komunikasi": "Seni, Media & Komunikasi",
    "Sains": "Sains & Penelitian",
    "Pelayanan": "Pelayanan & Administrasi",
    "Lainnya": "Lainnya",
}

EN_TO_UNIFIED = {
    "Information Technology": "Teknologi Informasi",
    "Engineering": "Teknik",
    "Sales": "Penjualan & Pemasaran",
    "Marketing": "Penjualan & Pemasaran",
    "Business Development": "Penjualan & Pemasaran",
    "Advertising": "Penjualan & Pemasaran",
    "Public Relations": "Seni, Media & Komunikasi",
    "Accounting/Auditing": "Keuangan & Akuntansi",
    "Finance": "Keuangan & Akuntansi",
    "Human Resources": "Sumber Daya Manusia",
    "Health Care Provider": "Layanan Kesehatan",
    "Education": "Pendidikan & Pelatihan",
    "Training": "Pendidikan & Pelatihan",
    "Manufacturing": "Manufaktur & Produksi",
    "Production": "Manufaktur & Produksi",
    "Purchasing": "Manufaktur & Produksi",
    "Supply Chain": "Manufaktur & Produksi",
    "Distribution": "Manufaktur & Produksi",
    "Design": "Seni, Media & Komunikasi",
    "Art/Creative": "Seni, Media & Komunikasi",
    "Writing/Editing": "Seni, Media & Komunikasi",
    "Research": "Sains & Penelitian",
    "Science": "Sains & Penelitian",
    "Customer Service": "Pelayanan & Administrasi",
    "Administrative": "Pelayanan & Administrasi",
    "Legal": "Hukum",
    "Management": "Manajemen & Bisnis",
    "Project Management": "Manajemen & Bisnis",
    "Product Management": "Manajemen & Bisnis",
    "Consulting": "Manajemen & Bisnis",
    "Strategy/Planning": "Manajemen & Bisnis",
    "Analyst": "Manajemen & Bisnis",
    "General Business": "Manajemen & Bisnis",
    "Other": "Lainnya",
    # Software QA postings are closer to the IT cluster than to manufacturing.
    "Quality Assurance": "Teknologi Informasi",
}

# ---------------------------------------------------------------------------
# Skill vocabulary
# ---------------------------------------------------------------------------
# A small supplement of skills that are frequent in real job postings but are
# not present in SKILL_CATEGORIES.  Each entry is (skill, display group).
SUPPLEMENT_SKILLS = {
    # Marketing / sales
    "branding": "Domain & Industri",
    "advertising": "Domain & Industri",
    "social media": "Domain & Industri",
    "digital marketing": "Domain & Industri",
    "seo": "Domain & Industri",
    "content marketing": "Domain & Industri",
    "email marketing": "Domain & Industri",
    "market research": "Domain & Industri",
    "lead generation": "Domain & Industri",
    "account management": "Domain & Industri",
    # Finance
    "budgeting": "Domain & Industri",
    "financial statements": "Domain & Industri",
    # Management
    "change management": "Manajemen Proyek & Produk",
    "strategic planning": "Manajemen Proyek & Produk",
    "operations management": "Manajemen Proyek & Produk",
    "program management": "Manajemen Proyek & Produk",
    # Engineering / construction
    "autocad": "Domain & Industri",
    "osha": "Domain & Industri",
    "blueprint reading": "Domain & Industri",
    # Design / media
    "graphic design": "Desain & UI/UX",
    "copywriting": "Desain & UI/UX",
    "canva": "Desain & UI/UX",
}

# Skills that should not dominate an applicant profile.  Applicants get at most
# 1-2 of these; the rest of their skills come from the technical/domain pool.
SOFT_SKILLS = {normalize_skill(s) for s in SKILL_CATEGORIES["Soft Skills"]}

# Synonym groups used to avoid redundant skills in one applicant profile
# (e.g. "excel" + "microsoft excel", "node" + "node.js").
SYNONYM_GROUPS = [
    ["excel", "microsoft excel"],
    ["word", "word processing"],
    ["quality assurance", "qa"],
    ["node.js", "node", "nodejs"],
    ["vue", "vue.js", "vuejs"],
    ["next.js", "nextjs"],
    ["nuxt.js", "nuxtjs"],
    ["go", "golang"],
    ["c#", "csharp"],
    ["postgresql", "postgres"],
    ["elasticsearch", "elastic search"],
    ["cloud computing", "cloud"],
    ["artificial intelligence", "ai"],
    ["natural language processing", "nlp"],
    ["large language model", "llm"],
    ["hugging face", "huggingface"],
    ["penetration testing", "pen testing"],
    ["cybersecurity", "cyber security"],
    ["social media", "social media marketing"],
]

CANONICAL_SKILL: dict[str, str] = {}
for _group in SYNONYM_GROUPS:
    _canonical = normalize_skill(_group[0])
    for _synonym in _group:
        CANONICAL_SKILL[normalize_skill(_synonym)] = _canonical


def canonical_skill(skill: str) -> str:
    """Return a canonical key used to deduplicate synonymous skills."""
    return CANONICAL_SKILL.get(normalize_skill(skill), normalize_skill(skill))

# Per-category skill pools.  Every entry is checked against the vocabulary at
# runtime; unknown entries are dropped with a warning.
CATEGORY_POOLS: dict[str, list[str]] = {
    "Teknologi Informasi": [
        # Programming
        "python", "java", "javascript", "typescript", "c++", "c#", "csharp",
        "go", "golang", "rust", "swift", "kotlin", "php", "ruby", "scala",
        "r", "matlab", "perl", "bash", "shell scripting", "powershell",
        # Frontend
        "react", "angular", "vue", "vue.js", "vuejs", "svelte", "next.js",
        "nextjs", "nuxt.js", "nuxtjs", "html", "html5", "css", "css3",
        "sass", "scss", "less", "bootstrap", "tailwind", "tailwind css",
        "material ui", "mui", "chakra ui", "styled components", "webpack",
        "vite", "babel", "eslint", "prettier", "responsive design",
        "mobilefirst development", "frontend", "ui development", "ux design",
        "web development", "redux", "mobx", "jquery",
        # Backend
        "node", "node.js", "nodejs", "express", "express.js", "django",
        "flask", "spring", "spring boot", "rails", "ruby on rails",
        "laravel", "asp.net", ".net", ".net core", "fastapi", "gin", "echo",
        "microservices", "rest", "rest api", "graphql", "grpc", "api",
        "api development", "api management", "backend",
        # Databases
        "sql", "mysql", "postgresql", "postgres", "mongodb", "nosql",
        "redis", "elasticsearch", "elastic search", "cassandra", "mariadb",
        "oracle", "oracle database", "sql server", "microsoft sql server",
        "sqlite", "dynamodb", "firebase", "firestore", "bigquery",
        "snowflake", "redshift", "cosmos db", "couchdb", "couchbase",
        "hbase", "neo4j", "database", "database management",
        # Cloud / DevOps
        "aws", "amazon web services", "azure", "microsoft azure", "gcp",
        "google cloud", "google cloud platform", "cloud computing", "cloud",
        "docker", "kubernetes", "k8s", "helm", "helm charts", "devops",
        "ci/cd", "jenkins", "circleci", "github actions", "gitlab ci",
        "travis ci", "terraform", "ansible", "puppet", "chef", "pulumi",
        "cloudformation", "linux", "unix", "ubuntu", "centos", "red hat",
        "nginx", "apache", "tomcat", "load balancing", "scaling", "pods",
        "hpa", "containerization", "container orchestration",
        # Data
        "data science", "data analysis", "data engineering", "data analytics",
        "tableau", "power bi", "looker", "qlik", "qlikview", "excel",
        "microsoft excel", "vba", "google sheets", "pandas", "numpy",
        "scipy", "jupyter", "jupyter notebook", "data mining",
        "data warehouse", "data pipeline", "etl", "apache spark", "spark",
        "hadoop", "hive", "pig", "databricks", "airflow", "dbt",
        "statistics", "statistical analysis", "forecasting",
        # AI / ML
        "machine learning", "deep learning", "nlp",
        "natural language processing", "computer vision", "tensorflow",
        "pytorch", "keras", "scikit-learn", "ai", "artificial intelligence",
        "generative ai", "llm", "large language model", "openai",
        "hugging face", "huggingface", "transformers", "spacy", "nltk",
        "gensim", "fasttext", "word2vec", "xgboost", "lightgbm", "catboost",
        "random forest", "neural network", "cnn", "rnn", "lstm",
        "transformer", "mlops", "model deployment", "model serving",
        "reinforcement learning", "recommendation system", "tensorhub",
        "pytorch lightning", "onnx", "triton",
        # Streaming / search
        "kafka", "apache kafka", "flink", "apache flink", "spark streaming",
        "storm", "apache storm", "flume", "apache flume", "esper", "wso2",
        "rabbitmq", "jms", "activemq", "pulsar", "apache pulsar", "kinesis",
        "pub/sub", "message queue", "event streaming", "stream processing",
        "complex event processing", "cep", "solr", "apache solr",
        "opensearch", "open search", "cognisearch", "search engine",
        "information retrieval", "full text search",
        # Security
        "cybersecurity", "cyber security", "security", "information security",
        "penetration testing", "pen testing", "ethical hacking",
        "network security", "application security", "cloud security",
        "devsecops", "siem", "soc", "vulnerability assessment", "encryption",
        "authentication", "authorization", "oauth", "jwt", "saml",
        "identity management", "compliance", "regulatory compliance", "gdpr",
        "hipaa",
        # Mobile
        "android", "ios", "react native", "flutter", "dart", "xamarin",
        "mobile development", "mobile app", "android studio", "xcode",
        # QA
        "quality assurance", "qa", "testing", "automation testing",
        "selenium", "cypress", "playwright", "jest", "mocha", "unit testing",
        "integration testing", "e2e testing", "test driven development",
        "tdd", "behavior driven development", "bdd", "manual testing",
        "performance testing",
        # Project / enterprise / office
        "agile", "scrum", "kanban", "jira", "confluence", "project management",
        "product management", "product owner", "scrum master",
        "sprint planning", "retrospective", "stakeholder management",
        "risk management", "technical lead", "tech lead", "team lead",
        "sap", "salesforce", "hubspot", "dynamics 365", "servicenow",
        "workday", "peoplesoft", "microsoft dynamics", "crm", "erp",
        "customer relationship management", "word", "powerpoint", "outlook",
        "microsoft office", "google workspace", "google drive", "google docs",
        "microsoft 365", "office 365", "sharepoint", "teams",
    ],
    "Teknik": [
        "civil engineering", "construction management", "site supervision",
        "project controls", "cost estimating", "construction safety",
        "inspection", "manufacturing", "lean", "six sigma",
        "continuous improvement", "quality assurance", "qa", "testing",
        "project management", "risk management", "risk assessment",
        "stakeholder management", "agile", "scrum", "sap", "erp", "excel",
        "microsoft excel", "data analysis", "statistics", "python", "matlab",
        "r", "supply chain", "logistics", "inventory management",
        "procurement", "vendor management", "demand planning",
        "material planning", "autocad", "osha", "blueprint reading",
        "operations management", "program management", "change management",
        "strategic planning",
    ],
    "Penjualan & Pemasaran": [
        "sales", "business development", "marketing", "customer service",
        "crm", "salesforce", "retail", "negotiation", "market research",
        "digital marketing", "social media", "social media marketing",
        "seo", "content marketing", "email marketing", "advertising",
        "event planning", "presentation", "forecasting", "account management",
        "lead generation", "customer relationship management", "branding",
        "communication", "problem solving", "persuasion",
        "customer support", "ecommerce", "commerce",
    ],
    "Keuangan & Akuntansi": [
        "accounting", "finance", "auditing", "taxation", "audit",
        "financial analysis", "financial reporting", "financial planning",
        "risk assessment", "internal audit", "external audit", "banking",
        "investment", "insurance", "underwriting", "claims", "kyc",
        "anti money laundering", "payroll", "budgeting", "forecasting",
        "erp", "sap", "microsoft excel", "financial statements",
        "risk management", "compliance", "regulatory", "regulatory reporting",
        "wealth management", "portfolio management", "financial statements",
        "communication", "attention to detail",
    ],
    "Sumber Daya Manusia": [
        "human resources", "hris", "recruitment", "talent acquisition",
        "onboarding", "employee relations", "payroll",
        "benefits administration", "performance management",
        "workforce planning", "organizational development", "compensation",
        "labor relations", "employee engagement", "training", "coaching",
        "sourcing", "employment law", "workday", "communication",
        "problem solving", "conflict resolution", "active listening",
    ],
    "Layanan Kesehatan": [
        "nursing", "patient care", "clinical", "medical", "healthcare",
        "pharmaceutical", "biotech", "cpr", "acls", "pals", "bls", "surgery",
        "surgical", "radiology", "cardiology", "dentistry", "veterinary",
        "case management", "patient safety", "patient monitoring",
        "wound care", "critical care", "telemetry", "med surg",
        "medication administration", "health assessment", "clinical care",
        "primary care", "care coordination", "emergency", "trauma",
        "nurse practitioner", "infection control", "wellness", "immunization",
        "phlebotomy", "ultrasound", "rehabilitation", "physical therapy",
        "occupational therapy", "behavioral health", "mental health",
        "hospice", "home health", "long term care", "hipaa", "communication",
        "empathy", "attention to detail",
    ],
    "Pendidikan & Pelatihan": [
        "education", "teaching", "training", "curriculum development",
        "assessment", "lesson planning", "classroom management",
        "instructional design", "elearning", "online learning", "coaching",
        "mentoring", "presentation", "public speaking", "microsoft office",
        "communication", "patience", "facilitation",
    ],
    "Perhotelan & Restoran": [
        "hospitality", "food service", "kitchen management", "menu planning",
        "food preparation", "culinary", "chef", "cooking", "baking",
        "restaurant management", "guest service", "event planning",
        "catering", "banquet", "bartending", "food safety",
        "customer service", "inventory management", "scheduling",
        "communication", "teamwork",
    ],
    "Manufaktur & Produksi": [
        "manufacturing", "supply chain", "logistics", "warehouse operations",
        "inventory management", "warehouse", "procurement", "purchasing",
        "sourcing", "vendor management", "shipping", "receiving",
        "distribution", "transportation", "demand planning",
        "material planning", "lean", "six sigma", "continuous improvement",
        "quality assurance", "food safety", "erp", "sap", "osha",
        "communication", "problem solving",
    ],
    "Konstruksi & Bangunan": [
        "construction management", "civil engineering", "site supervision",
        "project controls", "cost estimating", "construction safety",
        "inspection", "project management", "risk assessment",
        "quality assurance", "autocad", "osha", "blueprint reading",
        "structural analysis", "surveying", "communication",
    ],
    "Seni, Media & Komunikasi": [
        "design", "ui/ux", "ui design", "ux design", "figma", "sketch",
        "adobe xd", "photoshop", "illustrator", "invision", "user research",
        "prototyping", "wireframing", "design thinking", "design system",
        "graphic design", "canva", "copywriting", "marketing", "social media",
        "branding", "advertising", "event planning", "presentation",
        "writing", "editing", "storytelling", "public relations",
        "communication", "creativity",
    ],
    "Sains & Penelitian": [
        "research", "data analysis", "statistics", "statistical analysis",
        "python", "r", "matlab", "data science", "machine learning",
        "clinical", "quality assurance", "regulatory", "data entry",
        "communication", "critical thinking", "attention to detail",
    ],
    "Pelayanan & Administrasi": [
        "customer service", "customer support", "administrative support",
        "data entry", "filing", "typing", "word processing",
        "microsoft office", "excel", "outlook", "scheduling",
        "calendar management", "office management", "correspondence",
        "document management", "google workspace", "google drive",
        "google docs", "google sheets", "microsoft 365", "office 365",
        "sharepoint", "crm", "time management", "communication",
        "problem solving", "attention to detail",
    ],
    "Hukum": [
        "legal", "legal research", "compliance", "regulatory", "law",
        "litigation", "corporate law", "intellectual property",
        "employment law", "paralegal", "regulatory compliance",
        "risk management", "case management", "communication",
        "critical thinking", "attention to detail",
    ],
    "Manajemen & Bisnis": [
        "project management", "product management", "agile", "scrum",
        "kanban", "jira", "confluence", "product owner", "scrum master",
        "sprint planning", "retrospective", "stakeholder management",
        "risk management", "technical lead", "tech lead", "team lead",
        "business development", "change management", "strategic planning",
        "operations management", "program management", "budgeting",
        "forecasting", "vendor management", "negotiation", "decision making",
        "problem solving", "communication", "presentation", "leadership",
        "customer relationship management", "crm", "erp", "sap",
        "microsoft excel", "excel",
    ],
    "Lainnya": [
        "python", "sql", "excel", "microsoft excel", "microsoft office",
        "communication", "project management", "customer service", "sales",
        "marketing", "data analysis", "problem solving", "leadership",
        "time management", "teamwork", "attention to detail", "negotiation",
        "research", "presentation", "accounting", "finance",
        "human resources", "logistics", "design", "quality assurance",
        "operations management", "strategic planning",
    ],
}


def _dedupe_skill_list(skills: list[str]) -> list[str]:
    """Remove exact duplicates and synonyms while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for skill in skills:
        key = canonical_skill(skill)
        if key in seen:
            continue
        seen.add(key)
        out.append(skill)
    return out


# Remove duplicate and synonymous entries from every category pool.
CATEGORY_POOLS = {
    category: _dedupe_skill_list(skills)
    for category, skills in CATEGORY_POOLS.items()
}

# ---------------------------------------------------------------------------
# Experience / education / salary configuration
# ---------------------------------------------------------------------------
LEVELS = ["fresh", "junior", "mid", "senior"]
LEVEL_WEIGHTS = {"fresh": 0.20, "junior": 0.30, "mid": 0.30, "senior": 0.20}
LEVEL_YEARS = {
    "fresh": (0, 1),
    "junior": (2, 3),
    "mid": (4, 6),
    "senior": (7, 15),
}
LEVEL_SKILLS = {
    "fresh": (3, 5),
    "junior": (5, 7),
    "mid": (7, 10),
    "senior": (9, 13),
}
LEVEL_MAX_SOFT = {"fresh": 1, "junior": 1, "mid": 2, "senior": 2}

EDUCATION_ENUM = ["SMA/SMK", "D3", "S1/D4", "S2", "S3", "Lainnya"]

EDU_GENERAL = {
    "fresh": [("SMA/SMK", 0.10), ("D3", 0.25), ("S1/D4", 0.60), ("S2", 0.05)],
    "junior": [("SMA/SMK", 0.05), ("D3", 0.25), ("S1/D4", 0.65), ("S2", 0.05)],
    "mid": [("D3", 0.15), ("S1/D4", 0.70), ("S2", 0.15)],
    "senior": [("D3", 0.10), ("S1/D4", 0.65), ("S2", 0.22), ("S3", 0.03)],
}

EDU_OVERRIDES = {
    "Layanan Kesehatan": {
        "fresh": [("S1/D4", 0.70), ("S2", 0.25), ("S3", 0.05)],
        "junior": [("S1/D4", 0.70), ("S2", 0.25), ("S3", 0.05)],
        "mid": [("S1/D4", 0.65), ("S2", 0.30), ("S3", 0.05)],
        "senior": [("S1/D4", 0.55), ("S2", 0.40), ("S3", 0.05)],
    },
    "Pendidikan & Pelatihan": {
        "fresh": [("S1/D4", 0.80), ("S2", 0.20)],
        "junior": [("S1/D4", 0.80), ("S2", 0.20)],
        "mid": [("S1/D4", 0.75), ("S2", 0.25)],
        "senior": [("S1/D4", 0.65), ("S2", 0.30), ("S3", 0.05)],
    },
    "Hukum": {
        "fresh": [("S1/D4", 0.85), ("S2", 0.15)],
        "junior": [("S1/D4", 0.85), ("S2", 0.15)],
        "mid": [("S1/D4", 0.80), ("S2", 0.20)],
        "senior": [("S1/D4", 0.70), ("S2", 0.28), ("S3", 0.02)],
    },
    "Teknologi Informasi": {
        "fresh": [("SMA/SMK", 0.05), ("D3", 0.25), ("S1/D4", 0.65), ("S2", 0.05)],
        "junior": [("D3", 0.25), ("S1/D4", 0.70), ("S2", 0.05)],
        "mid": [("D3", 0.15), ("S1/D4", 0.70), ("S2", 0.15)],
        "senior": [("D3", 0.10), ("S1/D4", 0.65), ("S2", 0.22), ("S3", 0.03)],
    },
}

MARKET_MIX = {"Indonesia": 0.70, "International": 0.30}
ID_SALARY_NULL_RATE = 0.40
INTL_SALARY_NULL_RATE = 0.50
ID_SALARY_LEVEL_FACTOR = {"fresh": 0.75, "junior": 0.90, "mid": 1.00, "senior": 1.25}

COUNTRY_CURRENCY = {
    "United States": "USD",
    "United Kingdom": "GBP",
    "Canada": "CAD",
    "Australia": "AUD",
}

# Rough monthly gross base ranges, only used for the optional international
# salary field.  These are heuristic estimates, not observed data.
INTL_SALARY_BASE = {
    "United States": {"fresh": 3500, "junior": 5000, "mid": 7500, "senior": 11000},
    "United Kingdom": {"fresh": 2200, "junior": 3000, "mid": 4200, "senior": 6000},
    "Canada": {"fresh": 3000, "junior": 4200, "mid": 6000, "senior": 8500},
    "Australia": {"fresh": 4000, "junior": 5500, "mid": 7500, "senior": 10000},
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def source_signature() -> dict:
    """Return a lightweight signature of the source files for cache checks."""
    sig = {}
    for path in (JOBS_DB, POSTINGS_CSV, GRAPH_FILE):
        if path.exists():
            st = path.stat()
            sig[str(path)] = [st.st_mtime, st.st_size]
    return sig


def build_vocab() -> dict[str, str]:
    """Build the normalized skill vocabulary and its display group."""
    vocab: dict[str, str] = {}
    for cat, skills in SKILL_CATEGORIES.items():
        label = SKILL_CATEGORY_LABELS.get(cat, cat)
        for skill in skills:
            vocab.setdefault(normalize_skill(skill), label)
    for skill, label in SUPPLEMENT_SKILLS.items():
        vocab.setdefault(normalize_skill(skill), label)
    return vocab


def match_vocab(raw_skill: str, vocab: dict[str, str]) -> str | None:
    """Match a raw job skill to a vocabulary entry using n-grams."""
    skill = normalize_skill(str(raw_skill))
    if not skill:
        return None
    if skill in vocab:
        return skill
    tokens = re.findall(r"[a-z0-9+#./]+", skill)
    for n in range(min(4, len(tokens)), 0, -1):
        for i in range(len(tokens) - n + 1):
            candidate = " ".join(tokens[i : i + n])
            if candidate in vocab:
                return candidate
    return None


def percentile(sorted_values: list[float], q: float) -> float:
    """Simple linear-interpolation percentile (q in [0, 1])."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    return float(
        sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)
    )


def summarize_salary(pairs: list[tuple[float, float]]) -> dict | None:
    """Summarize observed (min, max) salary pairs."""
    if len(pairs) < 10:
        return None
    mins = sorted(p[0] for p in pairs)
    maxs = sorted(p[1] for p in pairs)
    return {
        "count": len(pairs),
        "median_min": statistics.median(mins),
        "median_max": statistics.median(maxs),
        "p25_min": percentile(mins, 0.25),
        "p75_min": percentile(mins, 0.75),
        "p25_max": percentile(maxs, 0.25),
        "p75_max": percentile(maxs, 0.75),
    }


def safe_json_loads(value):
    try:
        return json.loads(value)
    except Exception:
        return None


def safe_literal_eval(value):
    try:
        return ast.literal_eval(value)
    except Exception:
        return None


def is_valid_location(loc: str) -> bool:
    if not loc:
        return False
    loc = loc.strip()
    if not loc or len(loc) > 60:
        return False
    if loc.isdigit():
        return False
    if "jobstreet" in loc.lower():
        return False
    if loc.lower() == "indonesia":
        # Keep city/province level locations; "Indonesia" alone is too generic.
        return False
    return True


# ---------------------------------------------------------------------------
# Statistics builder
# ---------------------------------------------------------------------------


def build_stats(vocab: dict[str, str], refresh: bool = False) -> dict:
    """Build (or load) job-derived statistics used for applicant generation."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sig = source_signature()

    if CACHE_FILE.exists() and not refresh:
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if (
                cached.get("version") == CACHE_VERSION
                and cached.get("source_signature") == sig
            ):
                print(f"[*] Using cached job statistics: {CACHE_FILE}")
                return cached
        except Exception:
            pass

    print("[*] Building job statistics from source data (first run)...")

    id_category_weights: Counter = Counter()
    id_locations_by_cat: dict[str, Counter] = defaultdict(Counter)
    id_locations_global: Counter = Counter()
    id_salary_by_cat: dict[str, list[tuple[float, float]]] = defaultdict(list)
    id_salary_global: list[tuple[float, float]] = []

    # ---- Indonesian job data (clean_jobs) ----
    if JOBS_DB.exists():
        conn = sqlite3.connect(JOBS_DB)
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT categories, skills, location, salary_min, salary_max,
                   salary_currency
            FROM clean_jobs
            """
        )
        for categories_raw, skills_raw, location, smin, smax, currency in rows:
            categories = safe_json_loads(categories_raw) if categories_raw else None
            if not isinstance(categories, list) or not categories:
                continue
            first = str(categories[0]).strip()
            unified = ID_TO_UNIFIED.get(first)
            if not unified:
                continue

            id_category_weights[unified] += 1

            loc = str(location or "").strip()
            if is_valid_location(loc):
                id_locations_by_cat[unified][loc] += 1
                id_locations_global[loc] += 1

            if (
                str(currency or "").strip().upper() == "IDR"
                and smin is not None
                and smax is not None
                and float(smin) > 0
                and float(smax) >= float(smin)
            ):
                pair = (float(smin), float(smax))
                id_salary_by_cat[unified].append(pair)
                id_salary_global.append(pair)
        conn.close()

    # ---- LinkedIn postings (skill frequency + international categories) ----
    intl_category_weights: Counter = Counter()
    skill_freq_by_cat: dict[str, Counter] = defaultdict(Counter)

    if POSTINGS_CSV.exists():
        import pandas as pd

        df = pd.read_csv(POSTINGS_CSV, usecols=["skills_extracted", "category"])
        for skills_raw, category in zip(df["skills_extracted"], df["category"]):
            unified = EN_TO_UNIFIED.get(str(category).strip())
            if not unified:
                continue
            intl_category_weights[unified] += 1

            skills = safe_literal_eval(skills_raw)
            if not isinstance(skills, list):
                continue
            for raw in skills:
                matched = match_vocab(str(raw), vocab)
                if matched:
                    skill_freq_by_cat[unified][matched] += 1

    # ---- International locations (graph) ----
    intl_locations: Counter = Counter()
    if GRAPH_FILE.exists():
        import networkx as nx

        graph = nx.read_graphml(GRAPH_FILE)
        for _, data in graph.nodes(data=True):
            if data.get("type") != "job":
                continue
            country = str(data.get("search_country", "") or "").strip()
            city = str(data.get("search_city", "") or "").strip()
            if country and city:
                intl_locations[(country, city)] += 1

    # ---- Summaries ----
    id_salary_summary_by_cat = {
        cat: summarize_salary(pairs) for cat, pairs in id_salary_by_cat.items()
    }
    id_salary_summary_global = summarize_salary(id_salary_global)

    stats = {
        "version": CACHE_VERSION,
        "source_signature": sig,
        "id_category_weights": dict(id_category_weights),
        "intl_category_weights": dict(intl_category_weights),
        "id_locations_by_cat": {
            cat: counter.most_common(200)
            for cat, counter in id_locations_by_cat.items()
        },
        "id_locations_global": id_locations_global.most_common(200),
        "id_salary_by_cat": id_salary_summary_by_cat,
        "id_salary_global": id_salary_summary_global,
        "intl_locations": [
            [country, city, count]
            for (country, city), count in intl_locations.most_common(300)
        ],
        "skill_freq_by_cat": {
            cat: dict(counter) for cat, counter in skill_freq_by_cat.items()
        },
    }

    CACHE_FILE.write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[*] Cached job statistics: {CACHE_FILE}")
    return stats


# ---------------------------------------------------------------------------
# Sampling helpers
# ---------------------------------------------------------------------------


def weighted_sample_without_replacement(
    rng: random.Random, items: list[str], weights: list[float], k: int
) -> list[str]:
    """Sample ``k`` unique items using the given weights."""
    if k <= 0:
        return []
    pool = [(item, max(float(w), 1e-9)) for item, w in zip(items, weights)]
    if k >= len(pool):
        return [item for item, _ in pool]

    selected: list[str] = []
    for _ in range(k):
        total = sum(w for _, w in pool)
        r = rng.random() * total
        acc = 0.0
        for idx, (item, w) in enumerate(pool):
            acc += w
            if r <= acc:
                selected.append(item)
                pool.pop(idx)
                break
    return selected


def weighted_choice(rng: random.Random, pairs: list[tuple[str, float]]) -> str:
    items = [p[0] for p in pairs]
    weights = [p[1] for p in pairs]
    return rng.choices(items, weights=weights, k=1)[0]


def pick_category(rng: random.Random, market: str, stats: dict) -> str:
    if market == "Indonesia":
        weights = stats.get("id_category_weights") or {}
    else:
        weights = stats.get("intl_category_weights") or {}
    pairs = [(cat, float(weights.get(cat, 0))) for cat in UNIFIED_CATEGORIES]
    pairs = [(cat, w) for cat, w in pairs if w > 0]
    if not pairs:
        pairs = [(cat, 1.0) for cat in UNIFIED_CATEGORIES]
    return weighted_choice(rng, pairs)


def sample_skills(
    rng: random.Random,
    category: str,
    level: str,
    stats: dict,
    vocab: dict[str, str],
) -> list[str]:
    """Sample a realistic, category-relevant skill set."""
    pool = [s for s in CATEGORY_POOLS.get(category, []) if s in vocab]
    if not pool:
        pool = [s for s in CATEGORY_POOLS["Lainnya"] if s in vocab]

    core = [s for s in pool if s not in SOFT_SKILLS]
    soft = [s for s in pool if s in SOFT_SKILLS]

    # Fall back to the global vocabulary if a category pool is too small.
    if len(core) < 3:
        fallback = [s for s in vocab if s not in SOFT_SKILLS]
        core = list(dict.fromkeys(core + fallback))
    if not soft:
        soft = [s for s in vocab if s in SOFT_SKILLS]

    total = rng.randint(*LEVEL_SKILLS[level])
    max_soft = min(LEVEL_MAX_SOFT[level], len(soft), max(0, total - 2))
    soft_n = rng.randint(0, max_soft)
    core_n = total - soft_n
    if core_n > len(core):
        core_n = len(core)
        soft_n = min(total - core_n, len(soft))

    freq = stats.get("skill_freq_by_cat", {}).get(category, {})
    core_weights = [max(1.0, float(freq.get(s, 0))) ** 0.55 for s in core]
    soft_weights = [max(1.0, float(freq.get(s, 0))) ** 0.40 for s in soft]

    selected_core = weighted_sample_without_replacement(
        rng, core, core_weights, core_n
    )
    selected_soft = weighted_sample_without_replacement(
        rng, soft, soft_weights, soft_n
    )

    skills = _dedupe_skill_list(selected_core + selected_soft)

    # Synonymous skills may collapse during deduplication; top up to at least
    # three skills when the pool allows it.
    target_min = min(3, total, len(core) + len(soft))
    if len(skills) < target_min:
        seen = {canonical_skill(skill) for skill in skills}
        for candidate in core + soft:
            key = canonical_skill(candidate)
            if key in seen:
                continue
            skills.append(candidate)
            seen.add(key)
            if len(skills) >= target_min:
                break

    rng.shuffle(skills)
    return skills


def sample_education(rng: random.Random, category: str, level: str) -> str:
    dist = EDU_OVERRIDES.get(category, {}).get(level) or EDU_GENERAL[level]
    return weighted_choice(rng, dist)


def sample_location(rng: random.Random, market: str, category: str, stats: dict):
    """Return (country, location)."""
    if market == "Indonesia":
        pairs = stats.get("id_locations_by_cat", {}).get(category) or []
        if not pairs:
            pairs = stats.get("id_locations_global") or []
        if not pairs:
            return "Indonesia", "Jakarta Raya"
        location = weighted_choice(rng, [(str(p[0]), float(p[1])) for p in pairs])
        return "Indonesia", location

    pairs = stats.get("intl_locations") or []
    if not pairs:
        return "United States", "New York"
    country, city = weighted_choice(
        rng, [((str(p[0]), str(p[1])), float(p[2])) for p in pairs]
    )
    return country, city


def sample_salary(
    rng: random.Random, market: str, category: str, level: str, country: str
) -> dict | None:
    """Return an optional salary expectation or ``None``."""
    noise = lambda: math.exp(rng.gauss(0.0, 0.18))  # noqa: E731

    if market == "Indonesia":
        if rng.random() < ID_SALARY_NULL_RATE:
            return None
        summary = (
            (CURRENT_STATS.get("id_salary_by_cat") or {}).get(category)
            or CURRENT_STATS.get("id_salary_global")
        )
        if not summary:
            return None
        factor = ID_SALARY_LEVEL_FACTOR[level]
        smin = summary["median_min"] * factor * noise()
        smax = summary["median_max"] * factor * noise()
        if smax < smin * 1.10:
            smax = smin * 1.10
        return {
            "min": int(round(smin / 500_000) * 500_000),
            "max": int(round(smax / 500_000) * 500_000),
            "currency": "IDR",
            "period": "month",
        }

    if rng.random() < INTL_SALARY_NULL_RATE:
        return None
    base = INTL_SALARY_BASE.get(country, {}).get(level)
    if not base:
        return None
    smin = base * 0.85 * noise()
    smax = base * 1.20 * noise()
    if smax < smin * 1.10:
        smax = smin * 1.10
    return {
        "min": int(round(smin / 100) * 100),
        "max": int(round(smax / 100) * 100),
        "currency": COUNTRY_CURRENCY.get(country, "USD"),
        "period": "month",
    }


# ``sample_salary`` needs the loaded statistics; set by ``generate_applicants``.
CURRENT_STATS: dict = {}


def group_skills(skills: list[str], vocab: dict[str, str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for skill in skills:
        label = vocab.get(skill, "Lainnya")
        groups.setdefault(label, []).append(skill)
    return groups


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def build_category_quota(
    rng: random.Random, n: int, min_per_category: int, stats: dict
) -> list[str]:
    """Build a category list with a minimum per category and a weighted fill.

    A pure market-weighted draw can leave small categories (e.g. Hukum) with
    zero applicants.  For an evaluation dataset we want at least a few records
    in every category, so we seed each category with ``min_per_category``
    records and fill the rest using the combined Indonesian/international job
    distribution.
    """
    categories = UNIFIED_CATEGORIES
    min_per = max(0, min(int(min_per_category), n // max(1, len(categories))))
    quota = [category for category in categories for _ in range(min_per)]
    remaining = n - len(quota)

    if remaining > 0:
        id_weights = stats.get("id_category_weights") or {}
        intl_weights = stats.get("intl_category_weights") or {}
        id_sum = sum(float(v) for v in id_weights.values()) or 1.0
        intl_sum = sum(float(v) for v in intl_weights.values()) or 1.0
        pairs = [
            (
                category,
                MARKET_MIX["Indonesia"] * (float(id_weights.get(category, 0)) / id_sum)
                + MARKET_MIX["International"]
                * (float(intl_weights.get(category, 0)) / intl_sum),
            )
            for category in categories
        ]
        pairs = [(cat, w) for cat, w in pairs if w > 0] or [
            (cat, 1.0) for cat in categories
        ]
        for _ in range(remaining):
            quota.append(weighted_choice(rng, pairs))

    rng.shuffle(quota)
    return quota


def generate_applicants(
    n: int,
    seed: int,
    stats: dict,
    vocab: dict[str, str],
    min_per_category: int = 2,
) -> list[dict]:
    global CURRENT_STATS
    CURRENT_STATS = stats

    rng = random.Random(seed)
    n_id = int(round(n * MARKET_MIX["Indonesia"]))
    n_intl = n - n_id
    markets = ["Indonesia"] * n_id + ["International"] * n_intl
    rng.shuffle(markets)
    categories = build_category_quota(rng, n, min_per_category, stats)

    records: list[dict] = []
    for market, category in zip(markets, categories):
        level = weighted_choice(rng, [(lvl, LEVEL_WEIGHTS[lvl]) for lvl in LEVELS])
        years = rng.randint(*LEVEL_YEARS[level])
        skills = sample_skills(rng, category, level, stats, vocab)
        education = sample_education(rng, category, level)
        country, location = sample_location(rng, market, category, stats)
        salary = sample_salary(rng, market, category, level, country)

        record = {
            "applicant_id": None,  # assigned after shuffling
            "market": market,
            "country": country,
            "location": location,
            "interest_category": category,
            "experience_level": level,
            "experience_years": years,
            "education": education,
            "skills": skills,
            "skill_count": len(skills),
            "skill_groups": group_skills(skills, vocab),
            "expected_salary": salary,
            "is_synthetic": True,
        }
        records.append(record)

    rng.shuffle(records)
    for idx, record in enumerate(records, start=1):
        record["applicant_id"] = f"P-{idx:04d}"
    return records


# ---------------------------------------------------------------------------
# Validation & output
# ---------------------------------------------------------------------------


def validate(applicants: list[dict], vocab: dict[str, str]) -> dict:
    errors: list[str] = []
    seen_ids: set[str] = set()

    for applicant in applicants:
        aid = applicant.get("applicant_id")
        if not aid or aid in seen_ids:
            errors.append(f"Duplicate or missing applicant_id: {aid!r}")
        seen_ids.add(aid)

        for field in (
            "market",
            "country",
            "location",
            "interest_category",
            "experience_level",
            "experience_years",
            "education",
            "skills",
        ):
            if applicant.get(field) in (None, "", []):
                errors.append(f"{aid}: empty field {field!r}")

        if applicant.get("interest_category") not in UNIFIED_CATEGORIES:
            errors.append(f"{aid}: invalid interest_category")
        if applicant.get("experience_level") not in LEVELS:
            errors.append(f"{aid}: invalid experience_level")
        if applicant.get("education") not in EDUCATION_ENUM:
            errors.append(f"{aid}: invalid education")

        skills = applicant.get("skills") or []
        if not skills:
            errors.append(f"{aid}: no skills")
        for skill in skills:
            if skill not in vocab:
                errors.append(f"{aid}: skill not in dictionary: {skill!r}")

        salary = applicant.get("expected_salary")
        if salary is not None:
            if salary.get("currency") not in {"IDR", "USD", "GBP", "CAD", "AUD"}:
                errors.append(f"{aid}: invalid salary currency")
            if salary.get("period") != "month":
                errors.append(f"{aid}: invalid salary period")
            if not (isinstance(salary.get("min"), int) and isinstance(salary.get("max"), int)):
                errors.append(f"{aid}: salary min/max must be integers")
            elif salary["min"] <= 0 or salary["max"] < salary["min"]:
                errors.append(f"{aid}: invalid salary range")

        # No personally identifiable information.
        for pii in ("name", "full_name", "email", "phone", "address"):
            if pii in applicant:
                errors.append(f"{aid}: PII field present: {pii}")

    return {
        "ok": not errors,
        "errors": errors,
        "n": len(applicants),
        "unique_ids": len(seen_ids),
        "skills_all_in_dictionary": all(
            s in vocab for a in applicants for s in (a.get("skills") or [])
        ),
    }


def make_report(
    applicants: list[dict],
    stats: dict,
    vocab: dict[str, str],
    seed: int,
    min_per_category: int = 2,
) -> dict:
    def count_by(field: str) -> dict:
        return dict(Counter(a[field] for a in applicants).most_common())

    salaries = [a["expected_salary"] for a in applicants if a.get("expected_salary")]
    skill_counts = [a["skill_count"] for a in applicants]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "n_applicants": len(applicants),
        "category_minimum": min_per_category,
        "market": count_by("market"),
        "category": count_by("interest_category"),
        "experience_level": count_by("experience_level"),
        "education": count_by("education"),
        "salary_filled": len(salaries),
        "salary_null": len(applicants) - len(salaries),
        "salary_currency": dict(Counter(s["currency"] for s in salaries).most_common()),
        "skills_avg": round(sum(skill_counts) / len(skill_counts), 2) if skill_counts else 0,
        "skills_min": min(skill_counts) if skill_counts else 0,
        "skills_max": max(skill_counts) if skill_counts else 0,
        "vocabulary_size": len(vocab),
        "skill_dictionary_sources": {
            "curated_categories": len(SKILL_CATEGORIES),
            "curated_skills": len(
                {normalize_skill(s) for v in SKILL_CATEGORIES.values() for s in v}
            ),
            "supplement_skills": len(SUPPLEMENT_SKILLS),
        },
        "job_data": {
            "indonesian_jobs": sum((stats.get("id_category_weights") or {}).values()),
            "international_postings": sum(
                (stats.get("intl_category_weights") or {}).values()
            ),
            "international_locations": len(stats.get("intl_locations") or []),
        },
    }


def write_outputs(applicants: list[dict], report: dict, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    n = len(applicants)

    json_path = outdir / f"applicants_{n}.json"
    csv_path = outdir / f"applicants_{n}.csv"
    xlsx_path = outdir / f"applicants_{n}.xlsx"
    report_path = outdir / "generation_report.json"
    readme_path = outdir / "README.md"

    payload = {
        "metadata": {
            "title": "Synthetic Anonymous Applicant Dataset",
            "version": "1.0",
            "generated_at": report["generated_at"],
            "seed": report["seed"],
            "n_applicants": n,
            "source": "synthetic",
            "notes": [
                "Applicant IDs are anonymous; no names, emails, or phone numbers.",
                "Skills are sampled from the project's curated job-skill dictionary.",
                "Applicants are conditioned on real job clusters (category, location, salary).",
                "Expected salary is optional and may be null.",
                "International salary ranges are heuristic estimates, not observed data.",
            ],
        },
        "applicants": applicants,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    columns = [
        "applicant_id",
        "market",
        "country",
        "location",
        "interest_category",
        "experience_level",
        "experience_years",
        "education",
        "skill_count",
        "skills",
        "skill_groups",
        "expected_salary_min",
        "expected_salary_max",
        "expected_salary_currency",
        "expected_salary_period",
    ]
    rows: list[dict] = []
    for applicant in applicants:
        salary = applicant.get("expected_salary") or {}
        rows.append(
            {
                "applicant_id": applicant["applicant_id"],
                "market": applicant["market"],
                "country": applicant["country"],
                "location": applicant["location"],
                "interest_category": applicant["interest_category"],
                "experience_level": applicant["experience_level"],
                "experience_years": applicant["experience_years"],
                "education": applicant["education"],
                "skill_count": applicant["skill_count"],
                # Use " | " instead of "; " so spreadsheet apps that treat
                # semicolon as a delimiter do not shift the columns.
                "skills": " | ".join(applicant["skills"]),
                "skill_groups": json.dumps(
                    applicant["skill_groups"], ensure_ascii=False
                ),
                "expected_salary_min": salary.get("min", ""),
                "expected_salary_max": salary.get("max", ""),
                "expected_salary_currency": salary.get("currency", ""),
                "expected_salary_period": salary.get("period", ""),
            }
        )

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    # Excel export is the friendliest option for users on Indonesian locales,
    # where Excel may default to semicolon as the list separator.
    try:
        import pandas as pd

        pd.DataFrame(rows, columns=columns).to_excel(xlsx_path, index=False)
        print(f"[OK] XLSX : {xlsx_path}")
    except Exception as exc:  # pragma: no cover - optional dependency
        print(f"[!] XLSX skipped: {exc}")

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    readme_path.write_text(build_readme(report, n), encoding="utf-8")

    print(f"[OK] JSON : {json_path}")
    print(f"[OK] CSV  : {csv_path}")
    print(f"[OK] Report: {report_path}")
    print(f"[OK] README: {readme_path}")


def build_readme(report: dict, n: int) -> str:
    return f"""# Synthetic Applicant Dataset ({n} records)

Dataset pelamar **sintetis dan anonim** untuk pengujian sistem rekomendasi
lowongan kerja.

## File

- `applicants_{n}.json` — dataset lengkap (metadata + daftar pelamar)
- `applicants_{n}.csv` — versi tabular (delimiter koma, cocok untuk pandas)
- `applicants_{n}.xlsx` — versi Excel (paling mudah dibuka langsung)
- `generation_report.json` — ringkasan distribusi & validasi
- `README.md` — dokumen ini

## Skema per pelamar

| Field | Tipe | Keterangan |
|---|---|---|
| `applicant_id` | string | ID anonim, format `P-0001` |
| `market` | string | `Indonesia` atau `International` |
| `country` | string | Negara asal pelamar |
| `location` | string | Kota/provinsi |
| `interest_category` | string | Bidang/kategori minat (16 kategori terpadu) |
| `experience_level` | string | `fresh`, `junior`, `mid`, `senior` |
| `experience_years` | integer | Tahun pengalaman |
| `education` | string | `SMA/SMK`, `D3`, `S1/D4`, `S2`, `S3`, `Lainnya` |
| `skills` | array[string] | Skill dari kamus lowongan |
| `skill_count` | integer | Jumlah skill |
| `skill_groups` | object | Pengelompokan skill per jenis |
| `expected_salary` | object/null | `min`, `max`, `currency`, `period`; boleh null |
| `is_synthetic` | boolean | Selalu `true` |

> Catatan: untuk pelamar internasional, `education` dipetakan ke padanan
> Indonesia (S1/D4 = Bachelor, S2 = Master, S3 = PhD).

## Cara pakai singkat

```python
import pandas as pd

df = pd.read_csv("data/applicants/applicants_{n}.csv")
row = df.iloc[0]
user_text = row["skills"].replace(" | ", " ") + " " + row["interest_category"]
# user_text bisa dipakai sebagai input recommend_jobs_sentence(...)
```

> Di CSV, skill dipisah ` | ` agar tidak bentrok dengan delimiter. Jika Excel
> meminta delimiter saat membuka CSV, pilih **Comma** (bukan semicolon).
> File `applicants_{n}.xlsx` bisa dibuka langsung tanpa pengaturan delimiter.

## Cara data dibangkitkan

1. **Kamus skill** = `SKILL_CATEGORIES` di `src/clean_skills.py` (575 skill,
   18 kategori) + {report['skill_dictionary_sources']['supplement_skills']} skill
   tambahan yang sering muncul di lowongan nyata (mis. `autocad`, `osha`,
   `digital marketing`).
2. **Klaster lowongan** = kategori lowongan Indonesia (`data/all_jobs_clean.db`)
   dan posting internasional (`data/postings_final.csv`), dipetakan ke 16
   kategori terpadu. Setiap kategori dijamin minimal
   {report['category_minimum']} pelamar, sisanya dialokasikan mengikuti
   distribusi lowongan.
3. **Skill pelamar** disampling dari pool skill kategori yang sesuai, dengan
   bobot frekuensi skill di lowongan nyata. Soft skill dibatasi maksimal 1–2
   per pelamar.
4. **Lokasi** disampling dari distribusi lokasi lowongan pada kategori tersebut
   (Indonesia) atau dari graph lowongan internasional.
5. **Gaji** opsional: sekitar 40% pelamar Indonesia dan 50% pelamar
   internasional tidak mengisi harapan gaji.
6. **Pendidikan & pengalaman** mengikuti distribusi yang wajar per level dan
   kategori.
7. **ID anonim** diberikan setelah data diacak; tidak ada nama/email/telepon.

## Reproducibility

```bash
python scripts/generate_applicants.py --n {n} --seed {report['seed']} \
  --min-per-category {report['category_minimum']}
```

Gunakan `--refresh-cache` jika data sumber berubah.

## Ringkasan

- Jumlah pelamar: **{n}**
- Market: {report['market']}
- Level pengalaman: {report['experience_level']}
- Pendidikan: {report['education']}
- Gaji terisi: {report['salary_filled']} / {n} (null: {report['salary_null']})
- Rata-rata skill per pelamar: {report['skills_avg']}
- Ukuran kamus skill: {report['vocabulary_size']}

## Catatan penting

- Dataset ini **bukan data pelamar nyata**.
- Rentang gaji internasional adalah **estimasi heuristik**, bukan data observasi.
- Untuk evaluasi rekomendasi, `interest_category` dapat dipakai sebagai
  *ground truth* kategori yang diharapkan.
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic anonymous applicant dataset."
    )
    parser.add_argument("--n", type=int, default=100, help="Number of applicants")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory (default: data/applicants)",
    )
    parser.add_argument(
        "--min-per-category",
        type=int,
        default=2,
        help="Minimum number of applicants per category (default: 2)",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Rebuild job statistics even if the cache is valid",
    )
    args = parser.parse_args()

    if args.n <= 0:
        parser.error("--n must be positive")

    vocab = build_vocab()
    stats = build_stats(vocab, refresh=args.refresh_cache)
    applicants = generate_applicants(
        args.n, args.seed, stats, vocab, args.min_per_category
    )
    validation = validate(applicants, vocab)

    if not validation["ok"]:
        print("[!] Validation failed:")
        for error in validation["errors"][:20]:
            print(f"    - {error}")
        return 1

    report = make_report(
        applicants, stats, vocab, args.seed, args.min_per_category
    )
    report["validation"] = validation
    write_outputs(applicants, report, args.outdir)

    print("\n=== SUMMARY ===")
    print(f"Applicants : {report['n_applicants']}")
    print(f"Market     : {report['market']}")
    print(f"Categories : {len(report['category'])}")
    print(f"Salary     : {report['salary_filled']} filled / {report['salary_null']} null")
    print(f"Skills avg : {report['skills_avg']}")
    print(f"Vocabulary : {report['vocabulary_size']} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
