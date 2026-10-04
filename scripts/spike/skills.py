"""Spike-only skill dictionary: canonical skill -> aliases.  Matching is word-boundary
on lowercase text, so 'java' never matches inside 'javascript'."""
import re

SKILLS = {
    "python": ["python"], "javascript": ["javascript", "js", "ecmascript"],
    "typescript": ["typescript", "ts"], "java": ["java"], "c++": ["c++", "cpp"], "c": ["c language"],
    "c#": ["c#", "csharp"], "go": ["golang", "go lang"], "rust": ["rust"], "kotlin": ["kotlin"],
    "swift": ["swift", "swiftui"], "ruby": ["ruby", "rails", "ruby on rails"], "php": ["php", "laravel"],
    "scala": ["scala"], "sql": ["sql", "mysql", "t-sql"], "bash": ["bash", "shell scripting"],
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
    "quant": ["quantitative", "quant", "stochastic", "time series", "time-series"],
    "pde": ["pde", "scientific computing", "numerical methods"],
    "android": ["android"], "ios": ["ios"], "react native": ["react native"], "flutter": ["flutter"],
    "figma": ["figma"], "ui/ux": ["ui/ux", "ux", "ui design", "user experience", "design systems", "design system"],
    "three.js": ["three.js", "threejs", "webgl"], "framer": ["framer", "gsap"],
    "testing": ["unit testing", "pytest", "jest", "cypress", "selenium", "test automation", "qa"],
    "agile": ["agile", "scrum"], "system design": ["system design", "distributed systems", "scalable"],
    "algorithms": ["data structures", "algorithms", "dsa"], "oop": ["oop", "object-oriented"],
    "security": ["security", "cybersecurity", "authentication", "oauth", "jwt"],
    "api": ["api", "apis"], "oauth": ["oauth"], "stripe": ["stripe"],
}

_PATTERNS = {}
for canon, aliases in SKILLS.items():
    alts = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    _PATTERNS[canon] = re.compile(r"(?<![a-z0-9+#.])(?:" + alts + r")(?![a-z0-9+#])", re.I)


def extract_skills(text: str) -> set[str]:
    """Skills mentioned in text.  If the text has lost its spaces (bad PDF extraction),
    fall back to substring matching on aliases of 6+ characters."""
    found = {c for c, p in _PATTERNS.items() if p.search(text)}
    if text.count(" ") < len(text) / 12:  # abnormally few spaces -> concatenated words
        flat = re.sub(r"\s+", "", text.lower())
        for canon, aliases in SKILLS.items():
            if any(len(a) >= 6 and a.replace(" ", "") in flat for a in aliases):
                found.add(canon)
    return found
