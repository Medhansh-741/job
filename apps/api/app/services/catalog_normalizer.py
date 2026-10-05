"""Deterministic Catalog Normalizer & Preprocessor.

Handles canonical company and title normalization, seniority regex filtering,
experience requirement parsing, skill tagging, and plaintext description truncation.
"""
import html
import re
from datetime import datetime, timezone
from typing import Optional, List, Set, Any

# Management and leadership roles excluded at ingestion to focus on pure IC roles
SENIOR_PATTERN = re.compile(
    r"\b(staff|principal|director|vp|vice president|head of|lead|architect|fellow)\b",
    re.IGNORECASE,
)

# Required years regex: e.g., "3+ years", "2-4 yrs", "5 years of experience"
YEARS_PATTERN = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs)",
    re.IGNORECASE,
)

# HTML tag removal
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

# Common entity suffixes stripped for company normalization
COMPANY_SUFFIX_PATTERN = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|pvt|private|corp|corporation|technologies|technology|tech|software|solutions|services|group|co|holdings|labs)\b",
    re.IGNORECASE,
)

# Bracketed content and delimiters stripped for title normalization
TITLE_CLEAN_PATTERN = re.compile(
    r"(\([^\)]*\)|\[[^\]]*\]|\|.*|\-.*|—.*)",
    re.IGNORECASE,
)

# Canonical tech skill dictionary: canonical -> aliases
SKILLS_TAXONOMY = {
    "python": ["python"], "javascript": ["javascript", "js", "ecmascript"],
    "typescript": ["typescript", "ts"], "java": ["java"], "c++": ["c++", "cpp"], "c": ["c language"],
    "c#": ["c#", "csharp"], "go": ["golang", "go lang"], "rust": ["rust"], "kotlin": ["kotlin"],
    "swift": ["swift", "swiftui"], "ruby": ["ruby", "rails", "ruby on rails"], "php": ["php", "laravel"],
    "scala": ["scala"], "sql": ["sql", "mysql", "postgresql", "postgres", "t-sql"], "bash": ["bash", "shell scripting"],
    "react": ["react", "reactjs", "react.js"], "nextjs": ["next.js", "nextjs", "next js"],
    "vue": ["vue", "vuejs", "vue.js"], "angular": ["angular", "angularjs"],
    "nodejs": ["node.js", "nodejs", "node js", "node"], "express": ["express", "expressjs"],
    "html": ["html", "html5"], "css": ["css", "css3", "sass", "scss"], "tailwind": ["tailwind", "tailwindcss"],
    "redux": ["redux", "zustand"], "graphql": ["graphql"], "rest": ["rest", "restful", "rest api", "rest apis"],
    "websockets": ["websocket", "websockets"], "grpc": ["grpc"],
    "fastapi": ["fastapi"], "django": ["django"], "flask": ["flask"], "spring": ["spring", "spring boot"],
    "dotnet": [".net", "dotnet", "asp.net"],
    "postgresql": ["postgresql", "postgres", "postgis"], "mongodb": ["mongodb", "mongo"],
    "redis": ["redis"], "elasticsearch": ["elasticsearch", "opensearch"], "kafka": ["kafka"],
    "rabbitmq": ["rabbitmq"], "celery": ["celery"], "sqlite": ["sqlite"], "dynamodb": ["dynamodb"],
    "cassandra": ["cassandra"], "neo4j": ["neo4j"], "snowflake": ["snowflake"], "spark": ["spark", "pyspark"],
    "airflow": ["airflow"], "dbt": ["dbt"], "etl": ["etl", "elt", "data pipelines", "data pipeline"],
    "supabase": ["supabase"], "firebase": ["firebase"], "prisma": ["prisma"],
    "docker": ["docker", "containers", "containerization"], "kubernetes": ["kubernetes", "k8s"],
    "aws": ["aws", "amazon web services", "ec2", "s3", "lambda"], "gcp": ["gcp", "google cloud"],
    "azure": ["azure"], "terraform": ["terraform"], "linux": ["linux", "unix"],
    "git": ["git", "github", "gitlab"], "cicd": ["ci/cd", "cicd", "github actions", "jenkins"],
    "nginx": ["nginx"], "microservices": ["microservices", "microservice"],
    "pytorch": ["pytorch"], "tensorflow": ["tensorflow", "keras"], "jax": ["jax"],
    "scikit-learn": ["scikit-learn", "sklearn"], "pandas": ["pandas"], "numpy": ["numpy"],
    "machine learning": ["machine learning", "ml"], "deep learning": ["deep learning"],
    "nlp": ["nlp", "natural language processing"], "computer vision": ["computer vision", "opencv", "yolo", "yolov8"],
    "llm": ["llm", "llms", "large language models", "generative ai", "genai"],
    "rag": ["rag", "retrieval augmented generation", "retrieval-augmented generation"],
    "langchain": ["langchain", "langgraph", "llamaindex"], "agents": ["ai agents", "agentic", "multi-agent"],
    "embeddings": ["embeddings", "vector database", "vector databases", "semantic search", "sentence transformers"],
    "prompt engineering": ["prompt engineering", "prompting"], "onnx": ["onnx"],
    "mlops": ["mlops", "model deployment"], "data science": ["data science", "statistics", "statistical"],
    "android": ["android"], "ios": ["ios"], "react native": ["react native"], "flutter": ["flutter"],
    "figma": ["figma"], "ui/ux": ["ui/ux", "ux", "ui design", "user experience", "design systems"],
    "three.js": ["three.js", "threejs", "webgl"], "framer": ["framer", "gsap"],
    "testing": ["unit testing", "pytest", "jest", "cypress", "selenium", "test automation", "qa", "sdet", "automated testing"],
    "devops": ["devops", "sre", "site reliability engineering", "site reliability"],
    "oracle": ["oracle", "pl/sql", "plsql"],
    "servicenow": ["servicenow"],
    "salesforce": ["salesforce", "apex"],
    "agile": ["agile", "scrum"], "system design": ["system design", "distributed systems", "scalable"],
    "algorithms": ["data structures", "algorithms", "dsa"], "oop": ["oop", "object-oriented"],
    "security": ["security", "cybersecurity", "authentication", "oauth", "jwt"],
    # Widened coverage (common JD vocabulary that previously left jobs with no skills at all)
    "hugging face": ["hugging face", "huggingface", "transformers"],
    "fine-tuning": ["fine-tuning", "finetuning", "fine tuning", "lora", "rlhf"],
    "cuda": ["cuda", "gpu programming"],
    "mlflow": ["mlflow", "kubeflow", "sagemaker", "vertex ai"],
    "bigquery": ["bigquery", "redshift", "databricks"],
    "hadoop": ["hadoop", "hive", "mapreduce"],
    "data analysis": ["data analysis", "data analytics", "tableau", "power bi", "looker"],
    "ansible": ["ansible", "puppet", "chef"],
    "observability": ["observability", "prometheus", "grafana", "datadog"],
    "networking": ["networking", "tcp/ip"],
    "embedded": ["embedded systems", "firmware", "rtos", "microcontroller"],
    "blockchain": ["blockchain", "solidity", "web3", "smart contracts"],
    "game development": ["unity", "unreal engine", "game development"],
    "webpack": ["webpack", "vite", "rollup", "esbuild"],
    "api design": ["api design", "openapi", "swagger"],
    "playwright": ["playwright", "puppeteer"],
}

_SKILL_PATTERNS = {}
for canon, aliases in SKILLS_TAXONOMY.items():
    alts = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    _SKILL_PATTERNS[canon] = re.compile(r"(?<![a-z0-9+#.])(?:" + alts + r")(?![a-z0-9+#])", re.IGNORECASE)


def normalize_company(name: str) -> str:
    """Canonical company identifier for deduplication (lowercase, stripped suffixes, alphanumeric)."""
    if not name:
        return ""
    cleaned = COMPANY_SUFFIX_PATTERN.sub(" ", name.lower())
    return re.sub(r"[^a-z0-9]", "", cleaned)


def normalize_title(title: str) -> str:
    """Canonical title for deduplication (lowercase, stripped brackets and trailing metadata)."""
    if not title:
        return ""
    # Remove bracketed and hyphenated tags like "(Remote)", "[India]", "- Backend"
    cleaned = TITLE_CLEAN_PATTERN.sub(" ", title.lower())
    # Remove non-alphanumeric except space and collapse whitespace
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_senior_role(title: str) -> bool:
    """Returns True if the role is a senior/staff/director/executive management role."""
    if not title:
        return False
    return bool(SENIOR_PATTERN.search(title))


def extract_required_years(description: str) -> Optional[int]:
    """Finds the lowest explicit required years of experience up to 15 years."""
    if not description:
        return None
    matches = [int(m.group(1)) for m in YEARS_PATTERN.finditer(description) if int(m.group(1)) <= 15]
    return min(matches) if matches else None


def extract_skills(text: str) -> List[str]:
    """Extracts a sorted list of unique canonical technical skills mentioned in the text."""
    if not text:
        return []
    found: Set[str] = {c for c, p in _SKILL_PATTERNS.items() if p.search(text)}
    # Fallback for concatenated words in malformed texts
    if text.count(" ") < len(text) / 12:
        flat = re.sub(r"\s+", "", text.lower())
        for canon, aliases in SKILLS_TAXONOMY.items():
            if any(len(a) >= 6 and a.replace(" ", "") in flat for a in aliases):
                found.add(canon)
    return sorted(found)


def clean_html_text(text: str) -> str:
    """Strips HTML tags, unescapes entities, collapses whitespace and leading preview dots (no length limit).

    Run skill/years extraction on THIS (the full text); only the stored description is truncated.
    """
    if not text:
        return ""
    unescaped = html.unescape(html.unescape(text))
    stripped = HTML_TAG_PATTERN.sub(" ", unescaped)
    collapsed = re.sub(r"\s+", " ", stripped).strip()
    # Strip leading ellipses/periods/dashes from aggregator preview teasers
    return re.sub(r"^[\s\.\…\-]+", "", collapsed).strip()


def strip_html_and_truncate(text: str, limit: int = 1500) -> str:
    """Cleans HTML and limits character length for storage."""
    return clean_html_text(text)[:limit]


# alias (lowercase) -> canonical skill, built once for canonicalize_skill()
_ALIAS_TO_CANON = {}
for _canon, _aliases in SKILLS_TAXONOMY.items():
    _ALIAS_TO_CANON[_canon.lower()] = _canon
    for _a in _aliases:
        _ALIAS_TO_CANON.setdefault(_a.lower(), _canon)


def canonicalize_skill(name: str) -> Optional[str]:
    """Maps a free-form skill string (e.g. from an LLM) to the shared taxonomy, or None if unknown.

    Keeps job skills and candidate skills in one vocabulary so coverage math stays consistent.
    """
    if not name:
        return None
    key = re.sub(r"\s+", " ", name.lower().strip())
    return _ALIAS_TO_CANON.get(key)


def parse_date_posted(val: Any) -> datetime:
    """Normalizes various ATS date formats to a UTC datetime."""
    if not val:
        return datetime.now(timezone.utc)
    if isinstance(val, (int, float)):
        # Lever epoch timestamp (milliseconds or seconds)
        ts = val / 1000.0 if val > 1e11 else val
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(val, str):
        val = val.strip()
        try:
            # ISO format: 2026-10-04T12:00:00Z or similar
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)
