"""
Clean & deduplicate job skills, validate against descriptions from jobs.csv.
"""
import csv
import os
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

DB_URL = os.getenv("DB_URL")
DATA_DIR = Path(__file__).parent.parent / "data"
CSV_PATH = DATA_DIR / "jobs.csv"

SKILL_BLACKLIST = {
    # Bukan skill — degree / education
    "bachelor's degree", "bachelor degree", "bachelors degree", "ba/bs", "bs/ba",
    "master's degree", "master degree", "masters degree", "ma/ms", "ms/ma",
    "associate degree", "high school diploma", "high school", "ged",
    "college degree", "degree", "education", "formal education",
    # Bukan skill — benefits / perusahaan
    "equal opportunity employer", "equal employment opportunity", "eeo",
    "diversity", "equity", "inclusion", "diversity equity inclusion",
    "competitive salary", "competitive pay", "competitive compensation",
    "paid time off", "pto", "paid vacation", "paid holidays",
    "health insurance", "dental insurance", "vision insurance",
    "retirement plan", "401k", "pension", "pension scheme",
    "annual bonus", "annual bonuses", "performance bonus",
    "life assurance", "life insurance", "disability insurance",
    "stock options", "equity compensation",
    "tuition reimbursement", "relocation assistance",
    "career progression", "career growth", "career development",
    "professional development", "ongoing training",
    "employee discount", "discount", "discount in stores",
    "flexible schedule", "flexible hours", "flexible working",
    "work from home", "remote work", "hybrid work",
    "paid training", "on the job training", "on-the-job training",
    "training provided",
    # Bukan skill — generic / requirements
    "bachelor", "master",
    "driver's license", "valid driver's license", "drivers license",
    "authorization to work", "work authorization",
    "must be", "ability to", "willingness to",
    "pass background check", "background check",
    "drug screen", "drug test",
    "license", "certification required",
    "minimum", "qualifications",
    # Bukan skill — duplicates / too generic
    "requirements", "responsibilities", "qualifications",
    "experience", "years of experience", "years experience",
    "plus", "preferred", "nice to have",
    # Bukan skill — tempat / lokasi
    "united states", "us", "usa",
    # Bukan skill — benefits / compensation
    "fertility and familybuilding assistance", "fertility assistance",
    "family building assistance", "familybuilding assistance",
    "licensing and certification reimbursement", "licensure and credential reimbursements",
    "certification & licensure reimbursement",
    "employee assistance program", "employee assistance program (eap)",
    "employee stock ownership program", "employee stock purchase plan",
    "professional liability insurance",
    "california applicant privacy act", "california consumer privacy",
    "applicant privacy notice",
    "two professional supervisor references",
    # Bukan skill — generic responsibilities
    "planogram implementation and maintenance",
    "daily maintenance and cleanliness",
    "stocking and recovering merchandise",
    "stocking and rotating merchandise",
    "receiving and unpacking merchandise",
    "merchandise handling and movement",
    "planogram and merchandise presentation",
    # Bukan skill — AI extraction failure artifacts
    "no technical skills frameworks languages softwares concepts or requirements found in the given job posting",
    "no technical skills frameworks languages softwares concepts or requirements found in the given job posting.",
    "i am unable to extract the requested data as there is no provided job posting.",
    "i am unable to extract the requested data as there is no provided job posting",
    "the context does not mention anything about technical skills frameworks languages softwares concepts and requirements so i am unable to extract the requested data from the provided context",
    "the context does not mention anything about technical skills frameworks languages softwares concepts and requirements so i am unable to extract the requested data from the provided context.",
    "the context does not mention anything about technical skills frameworks languages softwares concepts and requirements so i cannot extract the requested data from the provided context.",
    "the context does not mention anything about technical skills frameworks languages softwares concepts and requirements so i cannot extract the requested data from the provided context",
    "ability to develop staff control expenses and shrinkage and manage merchandising and inventory control",
    "ability to comprehend access and utilize electronic medium and computer programs",
    "ability to stand walk climb ladders and lift up to 50 pounds for 8 hours",
    "associates degree or bachelors of science or arts in related field",
    # Bukan skill — vague / description fragments
    "management career advancement opportunities",
    "safety and sanitation maintenance",
    "guest complaint handling",
    # Bukan skill — single abstract words
    "solution sales process",
    "solution sales pro",
    # Sudah ada versi normalized-nya
    "communication skills", "written communication", "verbal communication",
    "problem solving skills", "problem-solving",
    "interpersonal skills", "interpersonal",
    "organizational skills", "organization skills",
    "analytical skills", "analytic skills",
    "leadership skills", "people management skills",
    "time management skills",
    "critical thinking skills",
    "teamwork skills",
    "detail oriented", "attention to details",
}

SKILL_NORMALIZE = {
    "communication skills": "communication",
    "written communication": "communication",
    "verbal communication": "communication",
    "interpersonal skills": "interpersonal",
    "organizational skills": "organization",
    "organization skills": "organization",
    "analytical skills": "analytical",
    "analytic skills": "analytical",
    "leadership skills": "leadership",
    "people management": "leadership",
    "problem solving skills": "problem solving",
    "problem-solving": "problem solving",
    "critical thinking skills": "critical thinking",
    "teamwork skills": "teamwork",
    "time management skills": "time management",
    "detail oriented": "attention to detail",
    "attention to details": "attention to detail",
    "microsoft office suite": "microsoft office",
    "ms office": "microsoft office",
    "ms excel": "excel",
    "microsoft excel": "excel",
    "ms word": "word",
    "microsoft word": "word",
    "ms powerpoint": "powerpoint",
    "microsoft powerpoint": "powerpoint",
    "crm software": "crm",
    "erp systems": "erp",
    "customer relations": "customer relationship management",
    "crm systems": "crm",
    "kpi management": "kpi",
    "key performance indicators": "kpi",
    "solution sales": "solution selling",
    "solution sales pro": "solution selling",
    "bd offerings": "business development",
    "opportunity planning": "sales planning",
    "territory management": "territory management",
    "territory planning": "territory management",
    "account management": "account management",
    "account planning": "account management",
    "standard operating procedures": "sop",
    "sops": "sop",
    "sop adherence": "sop",
    "safety regulations": "safety",
    "safety procedures": "safety",
    "safety standards": "safety",
    "occupational safety": "safety",
    "osha": "safety",
    "quality control": "quality assurance",
    "qa": "quality assurance",
    "quality standards": "quality assurance",
    "quality management": "quality assurance",
    "data entry": "data entry",
    "data processing": "data entry",
    "data management": "data management",
    "database management": "database",
    "sql queries": "sql",
    "structured query language": "sql",
    "python programming": "python",
    "javascript programming": "javascript",
    "java programming": "java",
    "c++ programming": "c++",
    "machine learning algorithms": "machine learning",
    "deep learning": "machine learning",
    "artificial intelligence": "ai",
    "natural language processing": "nlp",
    "statistical analysis": "statistics",
    "financial analysis": "financial analysis",
    "financial reporting": "financial reporting",
    "financial statements": "financial reporting",
    "budget management": "budgeting",
    "budgeting": "budgeting",
    "forecasting": "forecasting",
    "project planning": "project management",
    "project coordination": "project management",
    "project delivery": "project management",
    "agile": "agile",
    "scrum": "agile",
    "agile methodology": "agile",
    "kanban": "agile",
    "customer satisfaction": "customer service",
    "client relations": "customer service",
    "client management": "customer service",
    "customer experience": "customer service",
    "customer support": "customer service",
    "patient care": "patient care",
    "nursing": "nursing",
    "registered nurse": "nursing",
    "rn": "nursing",
    "bachelor of science in nursing": "nursing",
    "masters degree in nursing": "nursing",
    "sales": "sales",
    "selling": "sales",
    "business development": "business development",
    "negotiation": "negotiation",
    "contract negotiation": "negotiation",
    "vendor management": "vendor management",
    "supply chain": "supply chain",
    "logistics": "logistics",
    "inventory control": "inventory management",
    "warehouse management": "warehouse operations",
    "warehouse operations": "warehouse operations",
    "forklift": "forklift operation",
    "forklift operation": "forklift operation",
    "merchandising": "merchandising",
    "product knowledge": "product knowledge",
    "technical support": "technical support",
    "it support": "technical support",
    "help desk": "technical support",
    "troubleshooting": "troubleshooting",
    "repair": "repair",
    "maintenance": "maintenance",
    "preventive maintenance": "maintenance",
    "welding": "welding",
    "mig welding": "welding",
    "tig welding": "welding",
    "arc welding": "welding",
    "machining": "machining",
    "cnc": "cnc machining",
    "cnc machining": "cnc machining",
    "blueprint reading": "blueprint reading",
    "hydraulics": "hydraulics",
    "pneumatics": "pneumatics",
    "electrical": "electrical",
    "plumbing": "plumbing",
    "hvac": "hvac",
    "construction": "construction",
    "building codes": "building codes",
    "communication (verbal and written)": "communication",
    "verbal and written communication": "communication",
    "multidisciplinary team collaboration": "collaboration",
    "interdisciplinary team collaboration": "collaboration",
    "cross-functional collaboration": "collaboration",
    "team collaboration": "collaboration",
    "electronic medical record systems": "electronic medical records",
    "electronic medical record system": "electronic medical records",
    "electronic health records": "electronic health records",
    "medical record systems": "electronic medical records",
    "basic life support certification": "basic life support",
    "advanced cardiovascular life support": "advanced cardiac life support",
    "advanced cardiac life support": "advanced cardiac life support",
    "certified public accountant (cpa)": "cpa",
    "certified public accountant": "cpa",
    "good manufacturing practices (gmp)": "gmp",
    "good manufacturing practices": "gmp",
    "radiology information system (ris)": "radiology information system",
    "radiology information system": "radiology information system",
    "personal protective equipment": "ppe",
    "ppe (personal protective equipment)": "ppe",
    "standard operating procedures (sops)": "sop",
    "standard operating procedures": "sop",
    "key performance indicators (kpis)": "kpi",
    "key performance indicators": "kpi",
    "american nurses association (ana)": "american nurses association",
    "problemsolving and decisionmaking": "problem solving",
    "problemsolving skills": "problem solving",
    "problemsolving": "problem solving",
    "problem solving skills": "problem solving",
    "nursing support": "patient care",
    "virtual rn": "telehealth nursing",
    "solution sales process": "solution selling",
    "solution sales pro": "solution selling",
    "guest service skills": "guest service",
    "listening skills": "listening",
    "patient selfmanagement": "patient education",
    "selfmanagement": "patient education",
    "safety and sanitation maintenance": "food safety",
    "guest complaint handling": "complaint handling",
    "government regulation": "regulatory compliance",
    "sales opportunities": "sales",
    "microsoft word": "word",
    "microsoft excel": "excel",
    "microsoft powerpoint": "powerpoint",
    "microsoft outlook": "outlook",
    "basic life support": "bls",
    "bls certification": "bls",
    "cpr certification": "cpr",
    "advanced cardiac life support": "acls",
    "pediatric advanced life support": "pals",
    "food and beverage": "food service",
    "food & beverage": "food service",
    "decisionmaking": "decision making",
    "decision making skills": "decision making",
    "team management": "team leadership",
    "financial management": "financial analysis",
    "report writing": "reporting",
    "customer relationship": "customer service",
    "client relationship": "customer service",
    "time managment": "time management",
    "organisational": "organization",
    "organizational": "organization",
    "problem resolution": "problem solving",
    "issue resolution": "problem solving",
}

# Skill yang pasti berguna & ingin dipertahankan (domain-specific)
SKILL_WHITELIST_PREFIXES = [
    "python", "java", "javascript", "typescript", "react", "angular", "vue",
    "node", "express", "django", "flask", "spring", "rails", "laravel",
    "sql", "nosql", "mongodb", "postgresql", "mysql", "redis",
    "aws", "azure", "gcp", "cloud", "docker", "kubernetes", "devops",
    "machine learning", "deep learning", "nlp", "computer vision",
    "tensorflow", "pytorch", "keras", "scikit-learn",
    "data science", "data analysis", "data engineering",
    "tableau", "power bi", "looker", "qlik",
    "excel", "vba", "powerpoint", "word", "outlook",
    "sap", "oracle", "salesforce", "hubspot",
    "c++", "c#", ".net", "go", "rust", "swift", "kotlin",
    "html", "css", "sass", "less", "bootstrap", "tailwind",
    "rest", "graphql", "api", "microservices",
    "git", "github", "gitlab", "bitbucket",
    "jenkins", "circleci", "github actions", "ci/cd",
    "terraform", "ansible", "puppet", "chef",
    "linux", "unix", "bash", "powershell", "shell scripting",
    "networking", "tcp/ip", "dns", "firewall", "vpn",
    "cybersecurity", "security", "penetration testing",
    "agile", "scrum", "kanban", "jira", "confluence",
]

# ===============================
# Skill Categories
# ===============================
SKILL_CATEGORIES = {
    "Programming Languages": [
        "python", "java", "javascript", "typescript", "c++", "c#", "csharp", "go", "golang",
        "rust", "swift", "kotlin", "php", "ruby", "scala", "r", "matlab", "perl", "haskell",
        "elixir", "clojure", "dart", "lua", "objective c", "objective-c", "c programming",
        "c language", "assembly", "bash", "shell scripting", "powershell"
    ],
    "Frontend Development": [
        "react", "angular", "vue", "vue.js", "vuejs", "svelte", "next.js", "nextjs",
        "nuxt.js", "nuxtjs", "html", "html5", "css", "css3", "sass", "scss", "less",
        "bootstrap", "tailwind", "tailwind css", "material ui", "mui", "chakra ui",
        "styled components", "webpack", "vite", "babel", "eslint", "prettier",
        "responsive design", "mobilefirst development", "frontend", "ui development",
        "ux design", "web development", "redux", "mobx", "jquery"
    ],
    "Backend Development": [
        "node", "node.js", "nodejs", "express", "express.js", "django", "flask",
        "spring", "spring boot", "rails", "ruby on rails", "laravel", "php",
        "asp.net", ".net", ".net core", "fastapi", "gin", "echo",
        "microservices", "rest", "rest api", "graphql", "grpc",
        "api", "api development", "api management", "backend"
    ],
    "Databases & Storage": [
        "sql", "mysql", "postgresql", "postgres", "mongodb", "nosql",
        "redis", "elasticsearch", "elastic search", "cassandra", "mariadb",
        "oracle", "oracle database", "sql server", "microsoft sql server",
        "sqlite", "dynamodb", "firebase", "firestore", "bigquery",
        "snowflake", "redshift", "cosmos db", "couchdb", "couchbase",
        "hbase", "neo4j", "graphql", "database", "database management"
    ],
    "Cloud & DevOps": [
        "aws", "amazon web services", "azure", "microsoft azure", "gcp",
        "google cloud", "google cloud platform", "cloud computing", "cloud",
        "docker", "kubernetes", "k8s", "helm", "helm charts",
        "devops", "ci/cd", "jenkins", "circleci", "github actions",
        "gitlab ci", "travis ci", "terraform", "ansible", "puppet",
        "chef", "pulumi", "cloudformation",
        "linux", "unix", "ubuntu", "centos", "red hat",
        "nginx", "apache", "tomcat", "load balancing", "scaling",
        "pods", "hpa", "containerization", "container orchestration"
    ],
    "Data & Analytics": [
        "data science", "data analysis", "data engineering", "data analytics",
        "tableau", "power bi", "looker", "qlik", "qlikview",
        "excel", "microsoft excel", "vba", "google sheets",
        "pandas", "numpy", "scipy", "jupyter", "jupyter notebook",
        "data mining", "data warehouse", "data pipeline", "etl",
        "apache spark", "spark", "hadoop", "hive", "pig",
        "databricks", "airflow", "dbt",
        "statistics", "statistical analysis", "forecasting"
    ],
    "AI & Machine Learning": [
        "machine learning", "deep learning", "nlp", "natural language processing",
        "computer vision", "tensorflow", "pytorch", "keras", "scikit-learn",
        "ai", "artificial intelligence", "generative ai", "llm", "large language model",
        "openai", "hugging face", "huggingface", "transformers",
        "spacy", "nltk", "gensim", "fasttext", "word2vec",
        "xgboost", "lightgbm", "catboost", "random forest",
        "neural network", "cnn", "rnn", "lstm", "transformer",
        "mlops", "model deployment", "model serving",
        "reinforcement learning", "recommendation system",
        "tensorhub", "pytorch lightning", "onnx", "triton"
    ],
    "Streaming & Messaging": [
        "kafka", "apache kafka", "flink", "apache flink", "spark streaming",
        "storm", "apache storm", "flume", "apache flume", "esper",
        "wso2", "rabbitmq", "jms", "activemq", "pulsar", "apache pulsar",
        "kinesis", "pub/sub", "message queue", "event streaming",
        "stream processing", "complex event processing", "cep"
    ],
    "Search Platforms": [
        "elasticsearch", "elastic search", "solr", "apache solr",
        "opensearch", "open search", "cognisearch",
        "search engine", "information retrieval", "full text search"
    ],
    "Soft Skills": [
        "communication", "teamwork", "collaboration", "leadership",
        "problem solving", "critical thinking", "analytical",
        "time management", "organization", "adaptability",
        "interpersonal", "negotiation", "presentation",
        "creativity", "innovation", "decision making",
        "mentoring", "coaching", "conflict resolution",
        "emotional intelligence", "active listening",
        "attention to detail", "detail oriented",
        "empathy", "advocacy", "counseling",
        "public speaking", "facilitation",
        "patience", "cultural awareness",
        "self motivation", "initiative", "reliability",
        "dependability", "professionalism", "work ethic",
        "accountability", "ownership", "integrity",
        "persuasion", "problem solving",
    ],
    "Project & Product Management": [
        "agile", "scrum", "kanban", "jira", "confluence",
        "project management", "product management", "product owner",
        "scrum master", "sprint planning", "retrospective",
        "stakeholder management", "risk management",
        "technical lead", "tech lead", "team lead"
    ],
    "Security": [
        "cybersecurity", "cyber security", "security", "information security",
        "penetration testing", "pen testing", "ethical hacking",
        "network security", "application security", "cloud security",
        "devsecops", "siem", "soc", "vulnerability assessment",
        "encryption", "authentication", "authorization",
        "oauth", "jwt", "saml", "identity management",
        "compliance", "regulatory compliance", "gdpr", "hipaa"
    ],
    "Mobile Development": [
        "android", "ios", "swift", "kotlin", "react native",
        "flutter", "dart", "xamarin", "mobile development",
        "mobile app", "android studio", "xcode"
    ],
    "Design & UI/UX": [
        "ui/ux", "ui design", "ux design", "figma", "sketch",
        "adobe xd", "photoshop", "illustrator", "invision",
        "user research", "prototyping", "wireframing",
        "design thinking", "design system"
    ],
    "Office & Admin Tools": [
        "word", "excel", "powerpoint", "outlook", "microsoft office",
        "word processing", "spreadsheet", "data entry",
        "filing", "scheduling", "calendar management",
        "administrative support", "office management",
        "typing", "correspondence", "document management",
        "google workspace", "google drive", "google docs", "google sheets",
        "microsoft 365", "office 365", "sharepoint", "teams",
        "quickbooks", "publisher", "visio", "project",
    ],
    "Enterprise Software": [
        "sap", "oracle", "salesforce", "hubspot", "dynamics 365",
        "servicenow", "workday", "peoplesoft", "microsoft dynamics",
        "crm", "erp", "customer relationship management"
    ],
    "Quality Assurance": [
        "quality assurance", "qa", "testing", "automation testing",
        "selenium", "cypress", "playwright", "jest", "mocha",
        "unit testing", "integration testing", "e2e testing",
        "test driven development", "tdd", "behavior driven development",
        "bdd", "manual testing", "performance testing"
    ],
    "Domain & Industry": [
        "nursing", "patient care", "clinical", "medical",
        "healthcare", "pharmaceutical", "biotech",
        "finance", "accounting", "auditing", "taxation", "audit",
        "legal", "compliance", "regulatory", "law",
        "manufacturing", "supply chain", "logistics",
        "warehouse operations", "inventory management", "warehouse",
        "hospitality", "food service", "retail",
        "education", "teaching", "training",
        "sales", "business development", "marketing",
        "customer service", "customer support",
        # Healthcare extended
        "cpr", "acls", "pals", "bls", "surgery", "surgical",
        "radiology", "cardiology", "dentistry", "veterinary",
        "case management", "patient safety", "patient monitoring",
        "wound care", "critical care", "telemetry", "med surg",
        "medication administration", "health assessment",
        "clinical care", "primary care", "care coordination",
        "emergency", "trauma", "nurse practitioner",
        "infection control", "wellness", "immunization",
        "phlebotomy", "ultrasound", "rehabilitation",
        "physical therapy", "occupational therapy",
        "behavioral health", "mental health",
        "hospice", "home health", "long term care",
        # Finance extended
        "financial analysis", "financial reporting", "financial planning",
        "wealth management", "portfolio management",
        "risk assessment", "internal audit", "external audit",
        "regulatory reporting", "banking", "investment",
        "insurance", "underwriting", "claims",
        "kyc", "anti money laundering",
        # Construction & engineering
        "construction management", "civil engineering",
        "site supervision", "project controls", "cost estimating",
        "construction safety", "inspection",
        # HR extended
        "human resources", "hris", "recruitment", "talent acquisition",
        "onboarding", "employee relations", "payroll",
        "benefits administration", "performance management",
        "workforce planning", "organizational development",
        "compensation", "labor relations", "employee engagement",
        # Supply chain extended
        "procurement", "purchasing", "sourcing", "vendor management",
        "shipping", "receiving", "distribution", "transportation",
        "demand planning", "material planning",
        "lean", "six sigma", "continuous improvement",
        # Food & hospitality
        "food safety", "kitchen management", "menu planning",
        "food preparation", "culinary", "chef", "cooking", "baking",
        "restaurant management", "guest service",
        "event planning", "catering", "banquet", "bartending",
        # Legal extended
        "litigation", "corporate law", "intellectual property",
        "employment law", "legal research", "paralegal",
        # Education
        "curriculum development", "assessment", "lesson planning",
        "classroom management", "instructional design",
        "elearning", "online learning",
    ]
}

# Subcategory labels for display in Indonesian
SKILL_CATEGORY_LABELS = {
    "Programming Languages": "Bahasa Pemrograman",
    "Frontend Development": "Frontend",
    "Backend Development": "Backend",
    "Databases & Storage": "Database & Penyimpanan",
    "Cloud & DevOps": "Cloud & DevOps",
    "Data & Analytics": "Data & Analitik",
    "AI & Machine Learning": "AI & Machine Learning",
    "Streaming & Messaging": "Streaming & Messaging",
    "Search Platforms": "Search Platform",
    "Soft Skills": "Soft Skills",
    "Project & Product Management": "Manajemen Proyek & Produk",
    "Security": "Keamanan",
    "Mobile Development": "Mobile",
    "Design & UI/UX": "Desain & UI/UX",
    "Office & Admin Tools": "Office & Admin Tools",
    "Enterprise Software": "Enterprise Software",
    "Quality Assurance": "Quality Assurance",
    "Domain & Industry": "Domain & Industri"
}

# Uncategorized skills go here
MISC_CATEGORY = "Lainnya"
MISC_CATEGORY_EN = "Other Skills"

# Common non-skills that slip through is_stop_skill (extra filter)
EXTRA_STOP_SKILLS = {
    # Single abstract/generic words
    "development", "planning", "implementation", "support", "vision", "mission",
    "learning", "guidance", "standardization", "responsibility", "agility",
    "professionalism", "initiative", "integrity", "flexibility", "multitasking",
    "algebra", "geometry", "grammar", "vocabulary", "arithmetic",
    # Description fragments from graph
    "own it", "company truck", "climate change", "weekly direct deposit",
    "24/7 support", "smart cell phone", "own vehicle", "acceptable driving record",
    "criminal record check", "ceu", "feeding",
    # Generic job-related
    "policies", "procedures", "regulations",
    "scheduling", "prioritization", "reporting", "documentation",
    "oversight", "supervision", "compliance with regulations",
    # Tools/software that are too generic
    "pc skills", "computer skills", "google suite",
    # Generic business terms
    "cost control", "inventory",
    "administration", "operations management", "strategic planning",
    # Too generic in Indonesian job context
    "okr",
    # Non-skills
    "401(k)", "pipedrive", "outreach software", "network growth",
    "speaker outreach", "presenter outreach", "sponsorship outreach",
    "temperature control theory", "project accounting",
    # Physical requirements (NOT skills)
    "lifting", "walking", "standing", "stooping", "bending",
    "kneeling", "crouching", "crawling", "climbing", "balancing",
    "pushing", "pulling", "reaching", "grasping", "handling",
    "sitting", "twisting", "squatting", "carrying",
    "lifting 50 pounds", "lift 50 pounds", "lift 25 pounds",
    "stand for long periods", "stand for extended periods",
    "walking for long periods", "walking on uneven terrain",
    # Language requirements (not skills per se)
    "bilingual", "spanish language", "english language",
    "portuguese language", "french language", "german language",
    "mandarin language", "japanese language", "korean language",
    "foreign language", "language skills",
    # Interview/HR boilerplate
    "reliable transportation", "flexible schedule",
    "flexible work schedule", "weekend availability",
    "work weekends", "work holidays", "work evenings",
    "night shift", "day shift", "swing shift",
    "shift work", "rotating shifts", "on call",
    "must be available", "must be able to",
    "subject to", "background check", "drug test",
    "drug screening", "criminal background",
    "equal opportunity", "eeo", "affirmative action",
    # Noise dari keyword matching deskripsi JobStreet
    "job description", "job descriptions",
    "responsible", "responsibilities",
    "diploma", "degree", "education",
    "develop", "developing", "leading", "maintain",
    "activities", "purpose", "level",
    "people", "office", "life",
    "english", "global", "building",
    "computer", "digital", "media", "content",
    # Noise keyword generik hasil scrape JobStreet (ruang raya dkk)
    "access", "tech", "quality", "skill", "skills",
    "work", "works", "team", "job", "jobs", "role",
    # Kata peran/bidang terlalu generik untuk dijadikan skill
    "engineer", "engineers", "engineering", "developer", "developers",
    "data", "science", "computer science", "database administrator",
    "database", "manager", "management", "business", "marketing", "it support",
    "backend", "frontend", "fullstack", "full stack", "software engineer",
    # Kata kerja/noun generik hasil scrape yang bukan skill
    "develop", "issues", "resolutions",
}

# Patterns for filtering non-skills after extraction
EXTRA_STOP_PATTERNS = [
    r"^\d{3,4}\s*[kK]$",           # 401k, etc
    r"^\d+[-/]\d+",                 # 24/7, etc
    r".*motor.?skills?",
    r".*verbal.?instructions?",
    r"read/comprehend",
    r"^follow\s+verbal",
    r"^visual\s+acuity",
    r"food\s+(?:and|&)\s+catering",
    r"equipment\s+operation",
    r"^\d+\s+(?:hours|years?|months?)",
    r"health\s+safety",
    r"warmth\s+for",
    r"lift(?:ing)?\s+\d+\s*(?:pounds?|lbs?|kg)",
    r"stand\s+for\s+(?:long|extended)\s+periods?",
    r"walk(?:ing)?\s+for\s+(?:long|extended)\s+periods?",
    r"periodic\s+(?:lifting|bending|standing|walking)",
    r"ability\s+to\s+(?:lift|stand|walk|bend)",
    r"background\s+check",
    r"drug\s+(?:test|screen|testing|screening)",
    r"equal\s+opportunity",
    r"affirmative\s+action",
    r"subject\s+to",
]

# Lazy compilation for extra stop patterns (defined below, used by is_stop_skill)
_EXTRA_STOP_PATTERNS_CACHE = None
def _compile_extra_stop_patterns():
    global _EXTRA_STOP_PATTERNS_CACHE
    if _EXTRA_STOP_PATTERNS_CACHE is not None:
        return _EXTRA_STOP_PATTERNS_CACHE
    _EXTRA_STOP_PATTERNS_CACHE = [re.compile(p, re.IGNORECASE) for p in EXTRA_STOP_PATTERNS]
    return _EXTRA_STOP_PATTERNS_CACHE

# Build a prefix-based lookup for categorization
_ALL_CATEGORY_SKILLS = {}
for cat, skills in SKILL_CATEGORIES.items():
    for s in skills:
        _ALL_CATEGORY_SKILLS[s] = cat


def categorize_skills(skills_list):
    """Group a list of skills into categories.
    Returns dict of {category_label: [skills]} with Indonesian labels.
    """
    if not skills_list:
        return {}
    
    categories = {}
    for skill in skills_list:
        s = skill.lower().strip()
        found = False

        # Exact match first
        if s in _ALL_CATEGORY_SKILLS:
            cat = _ALL_CATEGORY_SKILLS[s]
            categories.setdefault(cat, []).append(skill)
            continue

        # For multi-word skills, try prefix matching
        # Require minimum 3 chars to avoid false matches (e.g. "r" matching everything)
        s_tokens = s.split()
        if len(s_tokens) >= 2:
            for cat_key, cat_skills in SKILL_CATEGORIES.items():
                for cat_skill in cat_skills:
                    if len(cat_skill) >= 3 and s.startswith(cat_skill):
                        categories.setdefault(cat_key, []).append(skill)
                        found = True
                        break
                    if len(cat_skill.split()) >= 2 and len(s) >= 3 and cat_skill.startswith(s):
                        categories.setdefault(cat_key, []).append(skill)
                        found = True
                        break
                if found:
                    break
        else:
            # Single-word skill: exact match only (avoids "word" -> "word2vec")
            for cat_key, cat_skills in SKILL_CATEGORIES.items():
                for cat_skill in cat_skills:
                    if s == cat_skill or (len(cat_skill) >= 3 and s.startswith(cat_skill)):
                        categories.setdefault(cat_key, []).append(skill)
                        found = True
                        break
                if found:
                    break
        
        if not found:
            categories.setdefault(MISC_CATEGORY, []).append(skill)
    
    result = {}
    for cat_en, skills in categories.items():
        label = SKILL_CATEGORY_LABELS.get(cat_en, cat_en)
        result[label] = skills
    
    return result


def get_category_labels():
    """Return list of (english_key, indonesian_label) for all categories."""
    return [(cat, SKILL_CATEGORY_LABELS.get(cat, cat)) for cat in SKILL_CATEGORIES]


# Minimum frequency threshold — skill harus muncul minimal N kali di dataset
MIN_FREQ = 3


def load_csv_descriptions():
    """Load (job_title_normalized, company_normalized) -> description from CSV."""
    if not CSV_PATH.exists():
        print(f"[!] CSV not found at {CSV_PATH}")
        return {}

    desc_map = {}
    count = 0
    with open(CSV_PATH, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("jobTitle") or "").strip().lower()
            company = (row.get("companyName") or "").strip().lower()
            desc = row.get("description") or ""
            if title and desc:
                key = (title, company)
                desc_map[key] = desc
                count += 1
    print(f"[OK] Loaded {count} descriptions from CSV")
    return desc_map


def normalize_skill(skill):
    s = skill.strip().lower()
    s = re.sub(r"\s+", " ", s)
    # remove trailing punctuation
    s = s.rstrip(".,;:")
    return s


_PATTERN_STOP_CACHE = None


def _compile_patterns():
    global _PATTERN_STOP_CACHE
    if _PATTERN_STOP_CACHE:
        return _PATTERN_STOP_CACHE
    patterns = [
        # Tangible benefits & compensation
        r"(?:assistance|reimbursement|bonus|coverage|program)\s*(?:for|and|programs)?",
        r"(?:fertility|family.building|childcare|tuition|relocation|licens|certif).*(?:assistance|reimbursement|program|coverage)",
        r"(?:employee|stock|equity|profit.sharing).*(?:program|plan|purchase|option)",
        r"(?:paid|pto|vacation|holiday|sick|leave|time.off)",
        r"(?:health|dental|vision|medical|life|disability).*(?:insurance|coverage|plan)",
        r"(?:retirement|401k|pension|rrsp).*(?:plan|matching|contribution)?",
        r"(?:insurance|coverage|reimbursement).*(?:plan|program)?",
        r"(?:discount|perk|benefit|incentive).*",
        r"(?:competitive|generous|attractive).*(?:salary|pay|compensation|package)",
        # Avoidance — description fragments
        r".*\bavoidance\b",
        r".*\boversight\b.*",
        r".*\bregistr(y|ies)\b",
        r".*\bmaintenance\b.*(?:daily|routine|regular|cleaning|sanitation)",
        r"(?:daily|routine|regular|sanitation).*\bmaintenance\b",
        r"(?:daily|routine|regular).*(?:maintenance|cleaning|sanitation|record)",
        # Generic responsibilities posing as skills
        r"stocking\s+(?:and|&)\s+(?:recovering|rotating|merchandise)",
        r"receiving\s+(?:and|&)\s+unpacking",
        r"merchandise\s+(?:handling|movement|presentation)",
        r"planogram\b.*",
        r"directional\s+flow\b",
        r"discipline\s+(?:and|&)\s+rewards?\b",
        # Non-skill single words (not a real skill)
        r"^(?:travel|csuite|c.suite|bsn|selfmanagement|registries)$",
        # Degree / certification fragments
        r"^(?:bachelor|master|phd|doctorate|associate|high.school|ged)\b",
        # Abstract / vague
        r"^(?:trends?|challenges?|terminology|reimbursement|regulation)",
        r"^key\s+(?:competitors?|trends?|drivers?|areas?)",
        # Benefits / company policy
        r"applicant\s+(?:privacy|notice)",
        r"california\s+(?:applicant|privacy|consumer)",
        r"equal.opportunity",
        r"employee.assistance",
        # AI extraction failure
        r"unable to extract",
        r"cannot extract",
        r"no technical skills",
        r"no job posting",
        r"context does not mention",
        r"ability to (?:develop|comprehend|stand|walk|lift)",
        r"associates degree or bachelors",
        # Government / HR boilerplate
        r"spd\d{4,}",                       # position codes like SPD94102
        r"nte\s+\d+\s*yr",                   # NTE 1 YR
        r"mbe\b", r"mbp\b",                  # MBE, MBP acronyms
        r"(?:open\s+)?continuous\s+announcement",
        r"career transition assistance plan",
        r"irs reassignment preference program",
        r"reassignment preference program",
        r"proof of employment",
        r"performance\s+appraisal",
        r"online\s+application\s+questionnaire",
        r"registration/license",
        r"position\s+description",
        r"alternative work schedule",
        r"nonbargaining\s+unit",
        r"government.?issued\s+charge\s+card",
        r"supervisory\s+probationary",
        r"probationary\s+period",
        r"one\s+year\s+specialized\s+experience",
        r"selection\s+interview",
        r"quality\s+group\s+rating",
        r"foreign\s+education\s+credentialing",
        r"department of education accredited",
        r"obtain\s+transcripts",
        r"accredited\s+college",
        r"c\.?\s*t\.?\s*a\.?\s*p\.?",        # CTAP
        r"r\.?\s*p\.?\s*p\.?",                # RPP
        r"proof\s+of\s+(?:education|license|registration)",
        r"day\s+shift",
        r"\d+\s+vacancies",
    ]
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    _PATTERN_STOP_CACHE = compiled
    return compiled


def is_stop_skill(skill):
    """Check if skill is a non-skill stopword."""
    s = skill.lower().strip()
    # terlalu pendek
    if len(s) <= 2:
        return True
    # cek blacklist exact
    if s in SKILL_BLACKLIST:
        return True
    # cek blacklist dengan partial match
    for stop in SKILL_BLACKLIST:
        if stop in s:
            return True
    # angka saja
    if re.match(r"^\d+[\dyears]*$", s):
        return True
    # terlalu panjang (>4 kata) — kemungkinan fragment deskripsi
    if len(s.split()) > 4:
        return True
    # regex patterns
    for p in _compile_patterns():
        if p.search(s):
            return True
    # extra stop skills
    if s in EXTRA_STOP_SKILLS:
        return True
    for p in _compile_extra_stop_patterns():
        if p.search(s):
            return True
    # single abstract word (bukan skill genuine)
    abstract_words = {
        "trends", "trend", "challenges", "challenge",
        "terminology", "technology",
        "opportunities", "opportunity",
        "solutions", "solution",
        "results", "result",
        "standards", "standard",
        "processes", "process",
        "procedures", "procedure",
        "policies", "policy",
        "regulations", "regulation",
        "compliance", "requirements", "requirement",
        "initiatives", "initiative",
        "strategies", "strategy",
        "objectives", "objective",
        "goals", "goal",
        "metrics", "metric",
        "deliverables", "deliverable",
        "methodologies", "methodology",
        "frameworks", "framework",
        "platforms", "platform",
        "systems", "system",
        "tools", "tool",
        "software", "hardware",
        "equipment", "machinery",
        "materials", "material",
        "products", "product",
        "services", "service",
        "clients", "client",
        "customers", "customer",
        "vendors", "vendor",
        "suppliers", "supplier",
        "stakeholders", "stakeholder",
        "partners", "partner",
        "colleagues", "colleague",
        "team members", "team member",
        "peers", "peer",
        "supervisors", "supervisor",
        "managers", "manager",
        "directors", "director",
        "executives", "executive",
        "key competitors",
        "travel",
        "csuite", "c-suite",
        "bsn",
        "selfmanagement", "self-management",
        "registries",
        "reimbursement",
    }
    words = s.split()
    if len(words) == 1 and words[0] in abstract_words:
        return True
    if s in abstract_words:
        return True
    # mengandung kata "key" sebagai kata pertama (key competitors, key trends, etc)
    if words[0] == "key" and len(words) <= 3:
        return True
    # generic — single word yang bukan skill
    generic = {
        "ability", "abilities", "skills", "knowledge", "understanding",
        "experience", "proficiency", "familiarity", "expertise",
        "including", "preferred", "required", "minimum",
        "various", "related", "general", "basic", "advanced",
        "demonstrated", "proven", "strong", "excellent", "good",
        "exceptional", "outstanding", "solid", "extensive",
        "day", "days", "week", "weeks", "month", "months", "year", "years",
        "time", "multiple", "various", "different", "including",
        "etc", "etc.", "e.g.", "i.e.",
    }
    if s in generic:
        return True
    return False


def skill_relevance_score(skill, desc_lower):
    """Score how relevant a skill is to the job description."""
    if not desc_lower:
        return 0.5
    s = skill.lower().strip()
    # exact match in description
    if s in desc_lower:
        return 1.0
    # word-level match
    words = s.split()
    matches = sum(1 for w in words if len(w) > 3 and w in desc_lower)
    if len(words) > 0:
        return matches / len(words) * 0.8
    return 0.0


def clean_and_dedup_skills(skills_raw, desc_lower="", job_title=""):
    """Clean, normalize, deduplicate skill list, return top N."""
    if not skills_raw:
        return []
    skills = [normalize_skill(s) for s in skills_raw.split(",") if s.strip()]

    # Step 1: normalize
    normalized = []
    for s in skills:
        if s in SKILL_NORMALIZE:
            normalized.append(SKILL_NORMALIZE[s])
        else:
            normalized.append(s)

    # Step 2: remove stop-skills
    filtered = [s for s in normalized if not is_stop_skill(s)]

    # Step 3: deduplicate (case-insensitive)
    seen = set()
    unique = []
    for s in filtered:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            unique.append(s)

    # Step 4: score by relevance to description & job title
    title_lower = job_title.lower()
    scored = []
    for s in unique:
        desc_score = skill_relevance_score(s, desc_lower)
        # bonus if skill appears in job title
        title_bonus = 0.3 if s.lower() in title_lower else 0.0
        # prefer shorter/more specific skills
        length_penalty = min(len(s) / 50, 0.2)
        final_score = desc_score + title_bonus - length_penalty
        scored.append((final_score, s))

    # Step 5: sort, keep top 10
    scored.sort(key=lambda x: -x[0])
    top = [s for _, s in scored[:10]]

    # Step 6: also include whitelist-prefix skills even if low score
    whitelisted = [s for s in unique if any(s.lower().startswith(p) for p in SKILL_WHITELIST_PREFIXES)]
    for s in whitelisted:
        if s not in top:
            top.append(s)
    # re-limit to 12
    return top[:12]


def update_job_skills(conn, job_db_id, cleaned_skills):
    c = conn.cursor()
    c.execute("DELETE FROM app.job_skills WHERE job_id = %s", (job_db_id,))
    for skill in cleaned_skills:
        c.execute(
            "INSERT INTO app.job_skills (job_id, skill) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (job_db_id, skill.lower())
        )
    conn.commit()
    c.close()


def run():
    import psycopg2
    if not DB_URL:
        print("[!] No DB_URL")
        return

    desc_map = load_csv_descriptions()
    print(f"[OK] Loaded {len(desc_map)} descriptions")

    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()

    c.execute("SELECT id, job_title, company, skills_raw FROM app.jobs ORDER BY id")
    rows = c.fetchall()
    print(f"[OK] Loaded {len(rows)} jobs from DB")

    total_old_skills = 0
    total_new_skills = 0
    updated = 0

    # Pre-compute frequency of each skill across ALL jobs (for filtering)
    c.execute("SELECT skill, COUNT(*) FROM app.job_skills GROUP BY skill")
    freq_map = {r[0]: r[1] for r in c.fetchall()}
    c.close()

    for job_db_id, job_title, company, skills_raw in rows:
        company = company or ""
        desc_lower = desc_map.get((job_title.lower(), company.lower()), "")
        if not desc_lower:
            # fallback: try matching by job_title only
            for (t, c), d in desc_map.items():
                if t == job_title.lower():
                    desc_lower = d
                    break

        old_count = len([s for s in skills_raw.split(",") if s.strip()]) if skills_raw else 0
        total_old_skills += old_count

        cleaned = clean_and_dedup_skills(skills_raw, desc_lower, job_title)
        new_count = len(cleaned)
        total_new_skills += new_count

        update_job_skills(conn, job_db_id, cleaned)
        updated += 1

        if updated % 500 == 0:
            print(f"  ... processed {updated}/{len(rows)}")

    conn.close()
    print(f"\n[OK] Done!")
    print(f"  Jobs processed: {updated}")
    print(f"  Skills before: {total_old_skills}")
    print(f"  Skills after:  {total_new_skills}")
    print(f"  Reduction:     {total_old_skills - total_new_skills} ({(1 - total_new_skills/total_old_skills)*100:.0f}%)")


if __name__ == "__main__":
    run()
