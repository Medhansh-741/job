# Technical Architecture: Production Job Matcher Engine

> **High-Performance, Zero-Hallucination Semantic Job Matching & Grounded Verification System**  
> **Target Audience:** Freshers, Early-Career Developers, and Technical Job Seekers  
> **Core Pipeline:** Document Ingestion $\to$ Deterministic Parsing $\to$ FastEmbed Vector Encoding $\to$ pgvector HNSW ANN Retrieval $\to$ Hybrid Bayesian Math $\to$ Listwise Groq LLM Cross-Attention Re-Ranking $\to$ Grounded Citation Verdicts $\to$ Streamlined Dashboard UX.

---

## Table of Contents
1. [End-to-End System Macro Architecture](#1-end-to-end-system-macro-architecture)
2. [Catalog Ingestion & Normalization Subsystem (Loop 1)](#2-catalog-ingestion--normalization-subsystem-loop-1)
3. [5-Layer Document Security & Ingestion Pipeline](#3-5-layer-document-security--ingestion-pipeline)
4. [Deterministic Resume Section & Entity Parsing Engine](#4-deterministic-resume-section--entity-parsing-engine)
5. [Deterministic Job Description Section Parser](#5-deterministic-job-description-section-parser)
6. [Stage 1: pgvector HNSW Retrieval & SQL Seniority Knockout](#6-stage-1-pgvector-hnsw-retrieval--sql-seniority-knockout)
7. [Stage 2: Deterministic Hybrid Mathematical Scoring Layer](#7-stage-2-deterministic-hybrid-mathematical-scoring-layer)
8. [Stage 3: Grounded Groq LLM Cross-Attention Re-Ranking](#8-stage-3-grounded-groq-llm-cross-attention-re-ranking)
9. [In-Process Asynchronous Background Worker & Concurrency Shield](#9-in-process-asynchronous-background-worker--concurrency-shield)
10. [On-Demand Live Search Fallback Engine](#10-on-demand-live-search-fallback-engine)
11. [Relational Database Schema & Vector Indexing Model (ERD)](#11-relational-database-schema--vector-indexing-model-erd)
12. [Frontend Feed & Modal UX Interaction Architecture](#12-frontend-feed--modal-ux-interaction-architecture)
13. [Security Model, Isolation & Threat Mitigation](#13-security-model-isolation--threat-mitigation)

---

## 1. End-to-End System Macro Architecture

The platform is designed around two asynchronous decoupled loops:
- **Loop 1 (Catalog Ingestion):** Continuous, scheduled harvesting, normalization, FastEmbed ONNX vectorization, and upserting of multi-source job postings into a shared Supabase PostgreSQL catalog with an HNSW index.
- **Loop 2 (Candidate Matching & Verification):** Interactive, user-facing session executing document upload, deterministic parsing, sub-millisecond database vector retrieval, mathematical calibration, listwise Groq cross-attention, and grounded verification.

### Macro Architecture ASCII Diagram

```
+========================================================================================================+
|                                              CLIENT TIER                                               |
|                                                                                                        |
|   +------------------------------------------------------------------------------------------------+   |
|   | Next.js 16 Web Dashboard (React 19 / TypeScript / Tailwind CSS)                                |   |
|   | - File Upload UI (Dropzone, Progress, File Validation)                                         |   |
|   | - Top 15 Matches Feed (Two-Tier Badges: Emerald Exact Match vs Zinc Broader Fit)               |   |
|   | - Streamlined Job Modal (Grounded 2-Sentence Verdict, Green Strengths, Greyed-Out Gaps)         |   |
|   | - Direct External Apply Redirection                                                            |   |
|   +------------------------------------------------------------------------------------------------+   |
+========================================================================================================+
                                   |                                    ^
                   HTTPS Requests  |                                    | Server-Sent Events /
                   + Supabase JWT  |                                    | Supabase Realtime Updates
                                   v                                    |
+========================================================================================================+
|                                           APPLICATION TIER                                             |
|                                                                                                        |
|   +------------------------------------------------------------------------------------------------+   |
|   | FastAPI Asynchronous Service (Python 3.11+ / Uvicorn)                                          |   |
|   |                                                                                                |   |
|   |   [Auth Guard]                 [Document Ingestion]              [Deterministic Section Parsers] |   |
|   |   - Supabase JWT Verification  - 5-Layer Security Sanitizer      - Resume Parser (Regex & State)|   |
|   |   - User Identity Extraction   - Magic Byte & Zip Bomb Check     - JD Parser (Deductions/Needs) |   |
|   |                                                                                                |   |
|   |   [Embedding Service]          [Two-Stage Matching Funnel]       [In-Process Queue Worker]      |   |
|   |   - FastEmbed (all-MiniLM-L6)  - Stage 1: pgvector HNSW ANN      - asyncio.Queue Throttling     |   |
|   |   - ONNX Runtime (384-dim)     - Stage 2: Deterministic Math     - asyncio.Semaphore(2) Shield  |   |
|   |   - Content-Hash Cache Lookup  - Stage 3: Groq LLM Re-Ranking    - In-Flight Deduplication Set  |   |
|   +------------------------------------------------------------------------------------------------+   |
+========================================================================================================+
          |                               |                                      |
          | Read/Write Isolated Data      | Query Dense Embeddings               | HTTP/2 Keep-Alive
          | Storage & State               | & Store Relational Catalog           | Listwise Batch Inference
          v                               v                                      v
+================================+ +===================================+ +================================+
|        PERSISTENCE TIER        | |           VECTOR TIER             | |      LLM INFERENCE TIER        |
|                                | |                                   | |                                |
|   Supabase PostgreSQL 15       | |   pgvector Extension              | |   Groq Cloud LPUs              |
|   - auth.users                 | |   - HNSW Cosine Index             | |   - Model: llama-3.3-70b       |
|   - public.resumes             | |     (m=16, ef_construction=64)    | |     (or gpt-oss-120b)          |
|   - public.profiles            | |   - match_jobs RPC Stored Proc    | |   - max_tokens: 8000           |
|   - public.jobs                | |   - ef_search = 150 Runtime Conf  | |   - response_format: json      |
|   - public.matches             | |   - Seniority Title Knockout      | |   - Grounded Citation Contract |
|   Supabase Private Storage     | |                                   | |   - First-Principles Rubric    |
|   - Isolated /resumes/<uid>    | |                                   | |                                |
+================================+ +===================================+ +================================+
                                                  ^
                                                  | Scheduled Batch Upserts
                                                  | (Loop 1 Catalog Crawler)
+========================================================================================================+
|                                       INGESTION & CRAWLER TIER                                         |
|                                                                                                        |
|   +------------------------------------------------------------------------------------------------+   |
|   | Automated Ingestion Engine (GitHub Actions Cron / Local Crawlers)                              |   |
|   | - ATS Connectors: Greenhouse API, Lever API, Ashby API, SmartRecruiters API                    |   |
|   | - Aggregator Fallbacks: Adzuna India API, Jooble API, JSearch API, Remotive API                |   |
|   | - Deterministic Normalizer: MD5 Idempotent UUID, Title Tokenization, Skill Extraction          |   |
|   | - ONNX FastEmbed Engine: Local CPU batch vectorization (384-dim)                               |   |
|   +------------------------------------------------------------------------------------------------+   |
+========================================================================================================+
```

---

## 2. Catalog Ingestion & Normalization Subsystem (Loop 1)

The job catalog is maintained independently of user traffic. Crawlers fetch jobs from keyless ATS boards and job aggregators, normalize metadata into a strict relational structure, tag required skills, vectorize descriptions via local CPU ONNX FastEmbed, and upsert records into Supabase.

### Ingestion Flow Diagram

```
+-----------------------------------------------------------------------------------------+
|                                   RAW DATA SOURCES                                      |
|  [Greenhouse API]      [Lever API]       [Ashby API]     [SmartRecruiters]    [Adzuna]  |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                              CATALOG NORMALIZER SERVICE                                 |
|                                                                                         |
|  1. Key Normalization:                                                                  |
|     - Clean company name: regex strip "Inc", "LLC", "Pvt Ltd", trim whitespace          |
|     - Canonical title: strip department prefixes, tags, emojis                          |
|                                                                                         |
|  2. Idempotent Deterministic Primary Key Generation:                                     |
|     id = md5(normalized_company + "::" + normalized_title + "::" + location)            |
|                                                                                         |
|  3. Regional Classification:                                                            |
|     - 'india': Matches "Bengaluru", "Bangalore", "Hyderabad", "Pune", "Delhi", "India"  |
|     - 'us': Matches "San Francisco", "New York", "Austin", "United States", "USA"       |
|     - 'remote': Explicit "Remote", "Work from anywhere", "Distributed"                  |
|                                                                                         |
|  4. Seniority & Experience Extraction:                                                  |
|     - Regex parse years: "([0-9]+)\+?\s*(?:to|-)\s*([0-9]+)?\s*years?"                 |
|     - Extract lower bound: required_years = int(match)                                  |
|                                                                                         |
|  5. Skill Extraction Engine:                                                            |
|     - Dictionary scan against curated technical taxonomy (~450 tech keywords)           |
|     - Deduplicate and lowercase: e.g. ["python", "fastapi", "docker", "postgres"]       |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                LOCAL ONNX FASTEMBED                                     |
|                                                                                         |
|  - Model: sentence-transformers/all-MiniLM-L6-v2                                        |
|  - Engine: ONNX Runtime (CPU optimized, zero external API costs)                        |
|  - Input String: "{title} at {company}. Location: {location}. Skills: {skills}. {desc}" |
|  - Output: 384-dimensional dense float32 vector                                         |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                                SUPABASE POSTGRESQL                                      |
|                                                                                         |
|  INSERT INTO public.jobs (id, title, company, location, region, description,            |
|                           skills, required_years, embedding, is_active, last_seen_at)   |
|  ON CONFLICT (id) DO UPDATE SET last_seen_at = now(), is_active = true                  |
+-----------------------------------------------------------------------------------------+
```

---

## 3. 5-Layer Document Security & Ingestion Pipeline

To protect the server from malformed, weaponized, or unreadable files, the upload route enforces a rigorous 5-layer sanitization barrier before any text parsing or LLM inference takes place.

### Document Validation Security Gate Diagram

```
[Raw Incoming File Stream]
            |
            v
+-------------------------------------------------------------------------+
| LAYER 1: Hard Size Limit Verification                                   |
| - Max file size: 5.0 MB (5 * 1024 * 1024 bytes)                        |
| - Rejection: 413 Payload Too Large                                      |
+-------------------------------------------------------------------------+
            | Passes
            v
+-------------------------------------------------------------------------+
| LAYER 2: Extension & Sanitization Barrier                               |
| - Allowed: .pdf, .docx, .doc, .txt                                      |
| - Safe filename: regex strip path traversal (`../`, `\`, null bytes)    |
| - Rejection: 400 Bad Request ("Disallowed file extension")              |
+-------------------------------------------------------------------------+
            | Passes
            v
+-------------------------------------------------------------------------+
| LAYER 3: Magic Byte (File Signature) Verification                       |
| - PDF: must begin with b"%PDF-" (0x25 0x50 0x44 0x46)                   |
| - DOCX: must begin with b"PK\x03\x04" (ZIP archive signature)           |
| - Rejection: 400 Bad Request ("Spoofed MIME type detected")             |
+-------------------------------------------------------------------------+
            | Passes
            v
+-------------------------------------------------------------------------+
| LAYER 4: Decompression Bomb & Malicious Entity Defense                  |
| - DOCX: checks uncompressed zip entry sizes; rejects if ratio > 100:1   |
| - Disables XML external entities (XXE) and recursive expansions         |
| - Rejection: 400 Bad Request ("Decompression bomb detected")            |
+-------------------------------------------------------------------------+
            | Passes
            v
+-------------------------------------------------------------------------+
| LAYER 5: Extractability & Content Density Validation                    |
| - PDF: parsed with pdfplumber; DOCX: parsed with python-docx            |
| - Min length requirement: >= 100 characters of readable text            |
| - Rejection: 400 Bad Request ("Scanned image or unreadable document")   |
+-------------------------------------------------------------------------+
            |
            v [Sanitized Document Object]
   (raw_bytes, safe_filename, extracted_text, content_type)
```

---

## 4. Deterministic Resume Section & Entity Parsing Engine

Rather than relying on non-deterministic LLM calls to parse resumes (which is slow, expensive, and prone to format errors), the platform uses a high-speed, deterministic regex state machine.

### Resume Parser Subsystem Diagram

```
+-----------------------------------------------------------------------------------------+
|                                    RAW EXTRACTED TEXT                                   |
|                   (e.g., from pdfplumber / python-docx stream)                           |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                              HEADING DETECTION ENGINE                                   |
|  Matches major resume landmarks using case-insensitive anchor patterns:                 |
|  - Education:     r'^(?:education|academic\s+background|qualifications)'               |
|  - Experience:    r'^(?:experience|work\s+history|employment|internships?)'             |
|  - Projects:      r'^(?:projects|technical\s+projects|academic\s+projects)'             |
|  - Skills:        r'^(?:technical\s+skills|skills\s+&?\s+tools?|competencies)'          |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                               SECTION PARTITIONER                                       |
|  Segments text into structured string buffers:                                          |
|  {                                                                                      |
|    "education":  "B.Tech in Computer Science, MIT (2020-2024)...",                      |
|    "experience": "Software Engineering Intern @ QMax (Jan 2024 - Jun 2024)...",         |
|    "projects":   "RailMind | Python, FastAPI, YOLOv8... JanSamadhan | React, Node...",  |
|    "skills":     "Python, FastAPI, TypeScript, React, Docker, PostgreSQL..."             |
|  }                                                                                      |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                            ENTITIES & TENURE CALCULATOR                                 |
|                                                                                         |
|  1. Skill Extraction:                                                                   |
|     - Case-insensitive token boundary match against 450+ canonical tech terms           |
|     - Deduplicates: ["python", "fastapi", "react", "docker", "postgresql"]             |
|                                                                                         |
|  2. Work History & Internship Analysis:                                                 |
|     - Parses date ranges: "Jan 2024 - Jun 2024", "08/2023 to 12/2023"                   |
|     - Distinguishes "Intern" / "Trainee" keywords from full-time titles                 |
|     - Calculates:                                                                       |
|         internship_months = sum(internship duration)                                   |
|         full_time_experience_years = sum(non-internship duration)                       |
|                                                                                         |
|  3. Fresher Classification Contract:                                                    |
|     is_fresher = (full_time_experience_years <= 1.0)                                    |
|                                                                                         |
|  4. Structured Entity Output:                                                           |
|     - Projects: List[{name: str, summary: str}]                                         |
|     - Experience: List[{role_and_company: str, summary: str}]                           |
+-----------------------------------------------------------------------------------------+
```

---

## 5. Deterministic Job Description Section Parser

Before a job description is processed for matching or LLM cross-attention, it is passed through `app.services.jd_parser.py`. This deterministic parser segments raw, unstructured text into a clean structured schema in $<1\text{ms}$.

### JD Parser Architecture Diagram

```
+-----------------------------------------------------------------------------------------+
|                               RAW UNSTRUCTURED JD TEXT                                  |
|     (Contains mixed headers, HR boilerplate, company marketing, duties, and tools)      |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                        DETERMINISTIC REGEX SECTION SPLITTER                             |
|                                                                                         |
|  Scans for section header markers:                                                      |
|  - Responsibilities: "What you will do", "Duties", "Key Responsibilities", "Day to Day"|
|  - Requirements:     "Requirements", "Basic Qualifications", "Must Haves", "Skills"     |
|  - Preferred/Bonus:  "Nice to have", "Preferred Qualifications", "Bonus points"         |
|  - Experience Level: "0-2 years", "Entry level", "Fresher", "Associate", "Senior"       |
|  - Education:        "B.S.", "B.Tech", "Computer Science", "Equivalent experience"      |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                           STRUCTURED JD OBJECT (SCHEMA)                                 |
|                                                                                         |
|  {                                                                                      |
|    "role_title":         "Full Stack Engineer",                                         |
|    "company":            "Acme Corp",                                                   |
|    "experience_level":   "Entry-Level / Fresher (0-1 years)",                           |
|    "responsibilities":   [                                                              |
|                            "Build scalable REST APIs using Node.js and TypeScript",     |
|                            "Develop responsive frontend interfaces with React"          |
|                          ],                                                             |
|    "required_skills":    ["react", "typescript", "node.js", "rest api", "sql"],        |
|    "preferred_skills":   ["docker", "aws", "tailwind css"],                             |
|    "education":          "Bachelor's degree in Computer Science or related field"       |
|  }                                                                                      |
+-----------------------------------------------------------------------------------------+
```

---

## 6. Stage 1: pgvector HNSW Retrieval & SQL Seniority Knockout

When a candidate profile is matched, Stage 1 performs dense approximate nearest neighbor (ANN) retrieval over the entire job catalog using PostgreSQL's `pgvector` extension and an HNSW index, with hard exclusion filters applied directly in SQL.

### Database Retrieval & Seniority Knockout Diagram

```
               Candidate Profile Embedding (384-dim Float Vector)
                                       |
                                       v
+-----------------------------------------------------------------------------------------+
|                     SUPABASE POSTGRESQL STORED PROCEDURE: match_jobs                     |
|                                                                                         |
|  1. Runtime HNSW Exploration Setting:                                                   |
|     PERFORM set_config('hnsw.ef_search', '150', true);                                  |
|     (Guarantees full exploration across 150 graph nodes, preventing early truncation)   |
|                                                                                         |
|  2. Cosine Distance Operator:                                                           |
|     distance = (j.embedding <=> query_embedding)                                        |
|     similarity = 1.0 - distance                                                         |
|                                                                                         |
|  3. SQL Hard Seniority Knockout Filter (Zero-Leakage Invariant):                        |
|     AND NOT (                                                                           |
|         j.normalized_title ~* '\y(director|vp|vice president|head of)\y'                |
|         OR j.title ~* '\y(director|vp|vice president|head of)\y'                        |
|     )                                                                                   |
|     AND (                                                                               |
|         NOT is_fresher_candidate OR                                                     |
|         NOT (                                                                           |
|             j.normalized_title ~* '\y(senior|sr\.?|lead|architect|manager|mgr|staff|principal)\y'
|             OR j.title ~* '\y(senior|sr\.?|lead|architect|manager|mgr|staff|principal)\y'
|         )                                                                               |
|     )                                                                                   |
|                                                                                         |
|  4. Regional Partition Expansion & Negative Geographic Knockout:                        |
|     - Target 'india'  => Matches j.region IN ('india', 'remote')                         |
|                          AND NOT restricted to non-India locations/timezones:            |
|                          (location ~* '\y(amer|us only|canada|uk|france|germany|emea)\y')|
|     - Target 'us'     => Matches j.region IN ('us', 'remote')                            |
|     - Target 'remote' => Matches j.region = 'remote'                                    |
|                                                                                         |
|  5. Experience Years Ceiling:                                                           |
|     - Freshers:    j.required_years IS NULL OR j.required_years <= 1                    |
|     - Experienced: j.required_years IS NULL OR j.required_years <= (candidate_years + 1)|
|                                                                                         |
|  ORDER BY j.embedding <=> query_embedding ASC LIMIT 100;                                |
+-----------------------------------------------------------------------------------------+
                                       |
                                       v
                Candidate Pool of Top 50-100 Semantically Relevant Jobs
                     (All Senior/Lead/Manager Roles Completely Eliminated)
```

---

## 7. Stage 2: Deterministic Hybrid Mathematical Scoring Layer

Stage 2 takes the vector search results and evaluates them with a deterministic mathematical scoring formula. This eliminates the "single-skill fluke" anomaly (where a terse job description containing only one skill scored 90%+) by introducing a Bayesian Denominator Floor, a Dual-Track Math Safeguard, and a Non-Linear Reality Dampener.

### Mathematical Scoring Architecture Diagram

```
+-----------------------------------------------------------------------------------------+
|                              INPUT SIGNALS PER CANDIDATE JOB                            |
|  - raw_sim: Cosine similarity [0.0, 1.0] from pgvector                                  |
|  - candidate_skills: Set of verified technical skills from resume                       |
|  - job_skills: Set of explicit technical skills extracted from JD                       |
|  - candidate_roles: Preferred target roles & extracted headline                         |
|  - job_title: Canonical job title                                                       |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
| 1. SEMANTIC NORMALIZATION (Min-Max Scaling)                                             |
|    Cosine similarities for sentence-transformers naturally cluster in [0.30, 0.75].     |
|                                                                                         |
|    clamped = max(0.30, min(0.75, raw_sim))                                              |
|    S_norm  = (clamped - 0.30) / (0.75 - 0.30)                                           |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
| 2. DUAL-TRACK MATH SAFEGUARD & BAYESIAN DENOMINATOR FLOOR                               |
|                                                                                         |
|    Track A: Standard Jobs (|job_skills| > 0)                                            |
|    - matched_skills = candidate_skills ∩ job_skills                                     |
|    - denominator    = max(|job_skills|, 3)                                              |
|    - C_skill        = |matched_skills| / denominator                                    |
|    - Base_Score     = 0.40 * S_norm + 0.60 * C_skill + B_title                          |
|                                                                                         |
|    Track B: Terse / Empty-Skill Postings (|job_skills| == 0)                             |
|    - Purely semantic track with strict score ceiling:                                   |
|    - Base_Score = 0.70 * S_norm + B_title                                               |
|    - Final Score is strictly capped at 65% max (68% blended ceiling)                     |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
| 3. ROLE & TITLE ALIGNMENT BOOST                                                         |
|    B_title = +0.05 (+5%) if any role token matches job title; else 0.0                   |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
| 4. BASE SCORE SYNTHESIS                                                                 |
|    Base_Score = 0.40 * S_norm + 0.60 * C_skill + B_title                                |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
| 5. NON-LINEAR REALITY DAMPENER (Knockout Penalty)                                       |
|    Prevents candidates with 0 matching skills from receiving high scores due to        |
|    broad semantic similarity.                                                           |
|                                                                                         |
|    D_skill = 1.00  if C_skill >= 0.50                                                   |
|    D_skill = 0.85  if 0.25 <= C_skill < 0.50                                            |
|    D_skill = 0.60  if 0.00 < C_skill < 0.25                                             |
|    D_skill = 0.35  if C_skill == 0.00 (Hard Knockout Penalty for 0% skill overlap)       |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
| 6. FINAL DETERMINISTIC MATH SCORE                                                       |
|    Score_math = round(clamp(Base_Score * D_skill * 100, 0, 100))                         |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
               Sorted & Truncated to Top 15 Finalists with Company Diversity Cap
                 (Strict maximum of 2 postings per employer to prevent feed spam)
```

---

## 8. Stage 3: Grounded Groq LLM Cross-Attention Re-Ranking

The Top 15 finalists from deterministic math scoring are passed to Groq (`openai/gpt-oss-20b` primary with `openai/gpt-oss-120b` fallback) in a single listwise batch prompt (RankGPT paradigm). The LLM evaluates candidate projects and verified skills against each job's structured schema, outputting grounded verdicts and transparent score deductions in $<2\text{s}$.

### LLM Cross-Attention Pipeline Diagram

```
+-------------------------------------+   +-------------------------------------+
|      STRUCTURED CANDIDATE SCHEMA    |   |     STRUCTURED CANDIDATE JOBS       |
|  - headline                         |   |  - Top 15 Compressed Job Cards      |
|  - experience_years / is_fresher    |   |  - role_title & company             |
|  - verified_skills (35 max)         |   |  - responsibilities (clean bullets) |
|  - projects: [{name, summary}]      |   |  - required_skills                  |
|  - experience: [{role, company}]    |   |  - preferred_skills                 |
+-------------------------------------+   +-------------------------------------+
                   \                                 /
                    \                               /
                     v                             v
+-----------------------------------------------------------------------------------------+
|                             LISTWISE BATCH PROMPT TO GROQ                               |
|                                                                                         |
|  - Persistent HTTP client with keep-alive & 35s timeout to api.groq.com                 |
|  - Model: openai/gpt-oss-20b (~1.2s latency) with openai/gpt-oss-120b fallback           |
|  - Parameters: max_tokens = 4096, temperature = 0.0, response_format = json_object      |
|                                                                                         |
|  STRICT SYSTEM CONTRACT:                                                                |
|  1. Grounded Citation Mandate: In every 'verdict', you MUST cite at least one specific |
|     candidate project name (e.g. *RailMind*, *JanSamadhan*) or employer (e.g. *QMax*)   |
|     proving ability to perform core duties.                                             |
|  2. Anti-Hallucination Barrier: Never claim candidate knows tools not in verified_skills|
|  3. Deductions: Explicit point penalties for missing tools (2-5 pts each)               |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                               GROQ JSON OUTPUT SCHEMA                                   |
|                                                                                         |
|  {                                                                                      |
|    "evaluations": [                                                                     |
|      {                                                                                  |
|        "job_id": "c7a8b9e0...",                                                         |
|        "verdict": "Your RailMind project proves strong proficiency with FastAPI and ... |
|                    However, you lack experience with AWS ECS and Docker deployments.",  |
|        "strengths": ["FastAPI", "Python", "PostgreSQL", "REST APIs"],                   |
|        "gaps": ["Docker", "AWS ECS"],                                                   |
|        "deductions": [                                                                  |
|          {"skill": "Docker", "points": 5, "reason": "No containerization in portfolio"},|
|          {"skill": "AWS", "points": 4, "reason": "Cloud deployment experience missing"} |
|        ],                                                                               |
|        "capability_fit": 88,                                                            |
|        "tooling_fit": 72,                                                               |
|        "seniority_fit": 80                                                              |
|      }                                                                                  |
|    ]                                                                                    |
|  }                                                                                      |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                       DETERMINISTIC PYTHON SCORE BLENDING                               |
|                                                                                         |
|  1. Raw LLM Rubric Score:                                                               |
|     Score_llm_raw = 0.50 * capability_fit + 0.30 * tooling_fit + 0.20 * seniority_fit   |
|                                                                                         |
|  2. Deduction Subtraction (Capped at 15 points max penalty):                             |
|     penalty   = min(15, sum(d["points"] for d in deductions))                           |
|     Score_llm = clamp(Score_llm_raw - penalty, 0, 100)                                  |
|                                                                                         |
|  3. Blended Final Calibration:                                                          |
|     Final_Score = round(0.30 * Score_math + 0.70 * Score_llm)                           |
+-----------------------------------------------------------------------------------------+
                                             |
                                             v
+-----------------------------------------------------------------------------------------+
|                               ATOMIC PERSISTENCE LAYER                                  |
|  INSERT INTO public.matches (user_id, job_id, match_score, matched_skills,              |
|                              missing_skills, explanation, score_breakdown)              |
|  ON CONFLICT (user_id, job_id) DO UPDATE SET match_score = EXCLUDED.match_score ...     |
+-----------------------------------------------------------------------------------------+
```

---

## 9. In-Process Asynchronous Background Worker & Concurrency Shield

To eliminate the operational complexity and cost of external task queues (such as Celery, Redis, or RabbitMQ), the platform embeds an in-process asynchronous matching worker managed within FastAPI's lifespan context.

### Queue Worker & Concurrency Shield Diagram

```
[Resume Upload Completed]
           |
           v
+-------------------------------------------------------------------------+
| Content-Hash Cache Inspection                                           |
| - Compare candidate_embedding_payload hash against existing_profile     |
| - If identical hash AND public.matches exists:                          |
|   -> Cache Hit: Bypass worker entirely (0ms CPU, 0 tokens)              |
+-------------------------------------------------------------------------+
           | Cache Miss / New Resume
           v
+-------------------------------------------------------------------------+
| IN-PROCESS ASYNC MATCHING WORKER (app.core.worker.py)                   |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  | In-Flight Deduplication Set (set[str])                            |  |
|  | - If user_id is already currently queued or executing, reject     |  |
|  |   duplicate requests immediately                                  |  |
|  +-------------------------------------------------------------------+  |
|                                  | Enqueued                             |
|                                  v                                      |
|  +-------------------------------------------------------------------+  |
|  | asyncio.Queue (FIFO Buffer)                                       |  |
|  | - Buffers background matching requests for authenticated users    |  |
|  +-------------------------------------------------------------------+  |
|                                  | Dequeued                             |
|                                  v                                      |
|  +-------------------------------------------------------------------+  |
|  | asyncio.Semaphore(2) Concurrency Shield                           |  |
|  | - Limits concurrent heavy matching funnels to at most 2 tasks     |  |
|  | - Protects CPU memory and Groq API token per-minute limits        |  |
|  +-------------------------------------------------------------------+  |
|                                  | Acquired Permit                      |
|                                  v                                      |
|  +-------------------------------------------------------------------+  |
|  | execute_matching_funnel(user_id, region, limit=15)                |  |
|  | - Updates thread-safe TaskTracker across 6 real-time milestones:  |  |
|  |   10% Doc Ingestion -> 25% Parsing -> 55% Vector -> 70% Math      |  |
|  |   -> 82% LLM Re-rank -> 95% Persistence -> 100% Complete          |  |
|  | - Atomically writes results to public.matches                     |  |
|  | - Releases semaphore & removes user_id from in-flight set        |  |
|  +-------------------------------------------------------------------+  |
+-------------------------------------------------------------------------+
                                   |
                                   v  (Polled every 800ms by Next.js client)
+-------------------------------------------------------------------------+
| LIVE TASK PROGRESS TRACKER (app.core.task_tracker.py)                   |
| - Authenticated endpoint: GET /matches/status                           |
| - Response: { status, progress, step_label, error, updated_at }         |
| - Powers locked modal progress bar and eliminates UI race conditions    |
+-------------------------------------------------------------------------+
```

---

## 10. On-Demand Live Search Fallback Engine

When a candidate uploads a resume for a specialized or niche tech stack and the shared Supabase catalog returns fewer than 5 high-confidence matches ($Score \ge 60\%$), the live fallback engine triggers dynamically.

### Live Search Fallback Flow Diagram

```
Candidate Matches Evaluated from Shared Catalog
                     |
                     v
       Are High-Confidence Matches (Score >= 60%) < 5?
                    / \
             NO    /   \   YES
                  /     \
                 v       v
+------------------+   +---------------------------------------------------+
| Proceed directly |   | TRIGGER LIVE FALLBACK SEARCH (live_fallback.py)   |
| to Groq Re-Rank  |   |                                                   |
+------------------+   | 1. Formulate Query:                               |
                       |    - Query = "{headline} {top_candidate_skills}"   |
                       |    - Location = candidate target region (India/US)|
                       |                                                   |
                       | 2. Fetch External Jobs:                           |
                       |    - Query Adzuna India API                       |
                       |    - Query Jooble India API                       |
                       |                                                   |
                       | 3. Normalize & Deduplicate:                       |
                       |    - Strip formatting & boilerplate               |
                       |    - Generate deterministic MD5 ID                |
                       |                                                   |
                       | 4. On-the-Fly Vectorization:                      |
                       |    - FastEmbed CPU ONNX vectorization (384-dim)   |
                       |                                                   |
                       | 5. Upsert to Supabase public.jobs:                |
                       |    - Instantly enriches the shared global catalog |
                       |                                                   |
                       | 6. Re-evaluate Funnel:                            |
                       |    - Re-runs Stage 1 & 2 including fresh jobs     |
                       +---------------------------------------------------+
                                                 |
                                                 v
                                   Proceed to Groq Re-Rank
```

---

## 11. Relational Database Schema & Vector Indexing Model (ERD)

The persistence layer runs on PostgreSQL 15 within Supabase, using foreign key cascade rules and strict Row-Level Security (RLS) to ensure user data isolation.

### Entity Relationship Diagram (ERD)

```
+-----------------------------------+
|            auth.users             |
|-----------------------------------|
| id                   UUID  <PK>   |
| email                TEXT         |
| encrypted_password   TEXT         |
| created_at           TIMESTAMPTZ  |
+-----------------------------------+
         |                  |
         | 1:1              | 1:1
         v                  v
+--------------------+   +-----------------------------------+
|  public.profiles   |   |          public.resumes           |
|--------------------|   |-----------------------------------|
| user_id UUID  <PK> |   | id            UUID  <PK>          |
| headline TEXT      |   | user_id       UUID  <FK>          |
| skills   TEXT[]    |   | filename      TEXT                |
| experience_years   |   | storage_path  TEXT                |
| preferred_roles    |   | file_size     INTEGER             |
| embedding  vec(384)|   | mime_type     TEXT                |
| content_hash TEXT  |   | raw_text      TEXT                |
| raw_json   JSONB   |   | is_active     BOOLEAN (DEFAULT tr)|
| updated_at TIMESTZ |   | created_at    TIMESTAMPTZ         |
+--------------------+   +-----------------------------------+
                                   |
                                   | 1:N
                                   v
                         +-----------------------------------+
                         |          public.matches           |
                         |-----------------------------------|
                         | id             UUID  <PK>         |
                         | user_id        UUID  <FK>         |
                         | job_id         TEXT  <FK> -----+  |
                         | match_score    INTEGER         |  |
                         | matched_skills TEXT[]          |  |
                         | missing_skills TEXT[]          |  |
                         | explanation    TEXT            |  |
                         | score_breakdown JSONB          |  |
                         | created_at     TIMESTAMPTZ     |  |
                         +-----------------------------------+
                                                          |
                                                          | N:1
                                                          v
                                         +-----------------------------------+
                                         |           public.jobs             |
                                         |-----------------------------------|
                                         | id                 TEXT <PK>      |
                                         | title              TEXT           |
                                         | company            TEXT           |
                                         | normalized_company TEXT           |
                                         | normalized_title   TEXT           |
                                         | location           TEXT           |
                                         | region             TEXT           |
                                         | description        TEXT           |
                                         | source_url         TEXT           |
                                         | required_years     INTEGER        |
                                         | skills             TEXT[]         |
                                         | embedding          vector(384)    |
                                         | is_active          BOOLEAN        |
                                         | last_seen_at       TIMESTAMPTZ    |
                                         +-----------------------------------+
```

### Table Specifications & Index Strategies

| Table | Index Type | Target Columns / Operator | Purpose |
|---|---|---|---|
| `public.jobs` | **HNSW** | `embedding vector_cosine_ops` (`m=16`, `ef_construction=64`) | Sub-millisecond ANN cosine similarity search across 10,000+ jobs |
| `public.jobs` | **B-Tree** | `(region)` | Fast regional filtering partition |
| `public.jobs` | **B-Tree** | `(is_active, last_seen_at)` | Fast staleness pruner and catalog maintenance |
| `public.jobs` | **B-Tree** | `(normalized_company, normalized_title, region)` | Idempotent deduplication lookups |
| `public.matches` | **B-Tree Unique** | `(user_id, job_id)` | Enforces single score record per job/user pair |
| `public.matches` | **B-Tree** | `(user_id, match_score DESC)` | Fast indexed read-aside query for dashboard feed (<0.2ms) |
| `public.resumes` | **Partial Unique**| `(user_id) WHERE is_active = true` | Guarantees at most one active resume per candidate |

---

## 12. Frontend Feed & Modal UX Interaction Architecture

The frontend is built on Next.js 16 (App Router) and Tailwind CSS. The interface prioritizes clarity, eliminating cognitive fatigue from redundant progress bars and presenting immediate, grounded evidence.

### User Interface Interaction Hierarchy

```
+-----------------------------------------------------------------------------------------+
|                                    DASHBOARD FEED                                       |
|                                                                                         |
|  Active Resume Banner:                                                                  |
|  [ File: medhansh.pdf (142 KB) | Uploaded 2h ago | [Replace Resume] | [Delete Resume] ] |
|                                                                                         |
|  Region Selector: [ India (Default) | United States | Remote | All ]                     |
|                                                                                         |
|  Top 15 Ranked Match Cards Grid:                                                        |
|  +-----------------------------------------------------------------------------------+  |
|  | Mitratech — Associate Software Engineer                       [ Exact Match: 94% ]|  |
|  | Hyderabad, India • Full-Time                                                      |  |
|  | "Your RailMind and JanSamadhan projects prove strong backend API design..."       |  |
|  | [Python] [FastAPI] [PostgreSQL] [REST]                                            |  |
|  +-----------------------------------------------------------------------------------+  |
|  | Coram AI — Junior Backend Developer                          [ Exact Match: 89% ]|  |
|  | Bengaluru, India • Full-Time                                                      |  |
|  | "Direct experience with asynchronous Python services and distributed queuing..."  |  |
|  | [Python] [AsyncIO] [Redis] [Docker]                                               |  |
|  +-----------------------------------------------------------------------------------+  |
|  | getwingapp — Full Stack Engineer                             [ Broader Fit: 74% ]|  |
|  | Remote • Full-Time                                                                |  |
|  | "Demonstrated full-stack capabilities, but role emphasizes Vue.js over React..."  |  |
|  | [TypeScript] [Node.js]                                                            |  |
|  +-----------------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------------+
                                             |
                               Click Job Card|
                                             v
+-----------------------------------------------------------------------------------------+
|                                STREAMLINED JOB DETAIL MODAL                             |
|                                                                                         |
|  Header:                                                                                |
|  - Role Title, Company, Location, Date Posted                                           |
|  - Calibrated Match Percentage Badge: [ 94% Match ]                                     |
|                                                                                         |
|  Section 1: Grounded Match Verdict Card (Zero Hallucination)                             |
|  +-----------------------------------------------------------------------------------+  |
|  | Verdict:                                                                          |  |
|  | "Your RailMind project demonstrates strong competence in architecting production  |  |
|  | FastAPI backends and managing PostgreSQL databases. However, you lack prior       |  |
|  | exposure to enterprise message queues like Apache Kafka."                         |  |
|  +-----------------------------------------------------------------------------------+  |
|                                                                                         |
|  Section 2: Verified Strengths (Matched Skills)                                         |
|  [ Python ]  [ FastAPI ]  [ PostgreSQL ]  [ REST APIs ]  (Green pill badges)            |
|                                                                                         |
|  Section 3: Missing Prerequisites & Gaps                                                 |
|  [ Apache Kafka ]  [ Kubernetes ]  (Subtle grey dashed-border pills)                    |
|                                                                                         |
|  Section 4: Itemized Score Deductions                                                   |
|  - (-4 pts) Missing Apache Kafka: Required for high-throughput event processing        |
|  - (-2 pts) Missing Kubernetes: Preferred for microservices orchestration               |
|                                                                                         |
|  Section 5: Job Description Overview                                                    |
|  - Structured duties and responsibilities extracted from posting                       |
|  - (If Aggregator teaser: clean notice with direct apply redirection)                   |
|                                                                                         |
|  Footer:                                                                                |
|  [ Close ]                                                  [ Apply on Company Site -> ]|
+-----------------------------------------------------------------------------------------+
```

### Two-Tier Match Badge Contract

| Badge Type | Color & Styling | Criteria |
|---|---|---|
| **`Exact Match`** | Emerald Badge (`bg-emerald-50 text-emerald-800 border-emerald-200`) | Final Score $\ge 75\%$ **AND** candidate has $\ge 3$ verified explicit matching skills |
| **`Broader Fit`** | Zinc / Amber Badge (`bg-zinc-100 text-zinc-700 border-zinc-300`) | Final Score $< 75\%$ **OR** candidate matched via inferred transferrable skills ($< 3$ explicit skills) |

---

## 13. Security Model, Isolation & Threat Mitigation

### 1. Row Level Security (RLS) Isolation
Every table containing candidate data (`resumes`, `profiles`, `matches`) has PostgreSQL RLS enabled. Policies strictly check `auth.uid() = user_id`. No user can query or mutate another user's files, profiles, or scores under any circumstances.

### 2. Service Role Key Isolation
The Supabase `SERVICE_ROLE_KEY` is exclusively configured on the backend API and crawler environments. It is strictly never exposed to the frontend Next.js bundle (which receives only `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`).

### 3. Isolated Storage Buckets
Candidate resumes are stored in private Supabase Storage at paths formatted as `resumes/{user_id}/{safe_filename}`. Download URLs are pre-signed with a 15-minute expiration window.

### 4. Input Sanitization & Path Traversal Guards
All uploaded filenames are stripped of non-alphanumeric characters, parent directory tokens (`..`), and null bytes (`\0`). Documents undergo strict magic byte validation to prevent MIME-type spoofing.
