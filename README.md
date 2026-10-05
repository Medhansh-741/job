<div align="center">

# Job Matcher Engine 🎯
**Production-Grade, Zero-Hallucination Semantic Job Matching & Grounded Verification Platform**

*Engineered for Early-Career Engineers, Freshers, and Technical Talent*

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16.3-black.svg)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.2-61DAFB.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0-3178C6.svg)](https://www.typescriptlang.org/)
[![TailwindCSS](https://img.shields.io/badge/TailwindCSS-v4-38B2AC.svg)](https://tailwindcss.com/)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL%20%2B%20pgvector-3ECF8E.svg)](https://supabase.com/)
[![Groq](https://img.shields.io/badge/Groq-LPU%20LLM%20Inference-F05A28.svg)](https://groq.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## 📖 Executive Overview

**Job Matcher** is a full-stack, enterprise-grade job matching and candidate evaluation engine designed to solve the two biggest flaws in modern AI job search tools:
1. **Senior Job Leakage for Freshers:** Most ATS platforms omit explicit year requirements in job postings, causing senior, lead, architect, and director roles to flood early-career candidate feeds. Job Matcher eliminates this completely via an exact **SQL-layer regex knockout barrier**.
2. **AI Hallucinations & Generic Scores:** Standard AI matchers invent candidate capabilities or score jobs on superficial keyword overlap (e.g. 1-skill JDs scoring 90%+). Job Matcher employs a **Schema-to-Schema matching pipeline** combining a **Bayesian Denominator Floor**, a **Non-Linear Reality Dampener**, and a listwise **Groq LLM cross-attention re-ranker** that legally mandates verifiable project citations before rendering a match verdict.

---

## ⚡ Key Highlights & Core Differentiators

- 🛡️ **SQL-Layer Seniority Knockout Barrier:** Stored procedure (`match_jobs`) on Supabase PostgreSQL applies a strict database-level regex barrier excluding `senior|sr|lead|architect|manager|staff|principal|director|vp|head of` titles whenever a fresher profile is evaluated.
- 📐 **Bayesian Denominator Floor:** Replaces naive Jaccard recall with $\frac{|\text{Matches}|}{\max(|\text{Job Skills}|, 3)}$, permanently curing the single-skill terse JD anomaly.
- 💥 **Non-Linear Reality Dampener:** If a candidate possesses 0% of the required explicit tools on a multi-skill job, a non-linear $0.35\times$ knockout penalty is applied, preventing high-similarity semantic illusions.
- 🔍 **Sub-Millisecond Structured JD Parsing:** Deterministic section parser (`jd_parser.py`) extracts `responsibilities`, `required_skills`, `preferred_skills`, `experience_level`, and `education` in $<1\text{ms}$ without LLM overhead.
- 🤖 **Zero-Hallucination Grounded Citations:** Groq LLM re-ranker operates under an immutable system contract requiring every verdict to cite concrete candidate projects (e.g. *RailMind*, *JanSamadhan*, *QMax*) and contrast them with explicit JD requirements.
- ⚖️ **Deterministic Python Score Blending:** Prevents LLM arithmetic inaccuracies by calculating calibrated scores in Python:  
  $$\text{Final Score} = \text{round}(0.30 \times \text{Score}_{\text{math}} + 0.70 \times \text{Score}_{\text{llm}})$$
- 🚀 **In-Process Async Worker with Concurrency Shield:** Embedded `asyncio.Queue` with `asyncio.Semaphore(2)` throttling and in-flight deduplication. Zero Redis, Zero Celery, Zero infrastructure bloat.
- 🌐 **On-Demand Live Search Fallback:** Automatically triggers Adzuna & Jooble India API live queries whenever a candidate's high-confidence catalog matches drop below threshold.
- 💎 **Modern, Cognitive-Fatigue-Free Dashboard:** Streamlined UI with Two-Tier Badges (**Emerald Exact Match** vs **Zinc Broader Fit**), green strength pills, greyed-out dashed gap pills, and itemized deductions.

---

## 🏗️ System Architecture at a Glance

```
 [User Resume Upload]
         |
         v
+-----------------------+
| 5-Layer Security Gate | -> Validates Magic Bytes, Zip Bombs, Size & MIME
+-----------------------+
         |
         v
+-----------------------+
| Deterministic Parsing | -> Extracts Sections, Skills, Internship/Full-time Tenures
+-----------------------+
         |
         v
+-----------------------+
| Local FastEmbed ONNX  | -> Produces 384-dim dense float vector (all-MiniLM-L6-v2)
+-----------------------+
         |
         v
+-----------------------+
| Stage 1: pgvector     | -> Supabase HNSW ANN (ef_search=150) + Seniority SQL Knockout
+-----------------------+
         |
         v
+-----------------------+
| Stage 2: Hybrid Math  | -> S_norm + Bayesian Denominator Floor + Reality Dampener
+-----------------------+
         |
         v
+-----------------------+
| Stage 3: Groq LLM     | -> Listwise Cross-Attention, Mandatory Project Citations
+-----------------------+
         |
         v
+-----------------------+
| Persist & Render UI   | -> Top 15 Matches, Emerald/Zinc Badges, Grounded Modal
+-----------------------+
```
> 📄 For exhaustive architectural diagrams of every subsystem, see [architecture.md](architecture.md).

---

## 🗂️ Monorepo Directory Layout

```
.
├── apps/
│   ├── api/                          # FastAPI Backend Application (Python 3.11+)
│   │   ├── app/
│   │   │   ├── core/
│   │   │   │   ├── auth.py           # Supabase JWT decoding, validation & user context
│   │   │   │   ├── db.py             # Psycopg2 connection pool & repository queries
│   │   │   │   └── worker.py         # In-process asyncio queue worker & semaphore shield
│   │   │   ├── services/
│   │   │   │   ├── catalog_normalizer.py   # Job normalization, tokenization & deduping
│   │   │   │   ├── document_validator.py   # 5-layer document security verification
│   │   │   │   ├── embedding_service.py    # FastEmbed ONNX embeddings & cache hashing
│   │   │   │   ├── jd_parser.py            # Sub-ms regex JD section parsing engine
│   │   │   │   ├── live_fallback.py        # Live Adzuna / Jooble search fallback
│   │   │   │   ├── llm_reranker.py         # Groq listwise cross-attention re-ranker
│   │   │   │   ├── matching_engine.py      # Two-stage matching pipeline & hybrid math
│   │   │   │   ├── resume_parser.py        # Deterministic resume parsing & tenure math
│   │   │   │   └── storage.py              # Supabase private storage integration
│   │   │   └── main.py               # FastAPI entry point, lifespan, & HTTP routes
│   │   └── requirements.txt          # Python dependencies
│   │
│   └── web/                          # Next.js 16 Web Dashboard (React 19, TypeScript)
│       ├── src/
│       │   ├── app/
│       │   │   ├── dashboard/page.tsx # Authenticated candidate dashboard
│       │   │   ├── login/page.tsx     # Supabase Auth login & registration
│       │   │   ├── layout.tsx         # Global root layout & styling
│       │   │   └── globals.css        # Tailwind CSS imports & theme tokens
│       │   └── components/
│       │       └── dashboard/
│       │           ├── active-resume-card.tsx  # Resume status, replacement & deletion
│       │           ├── job-card.tsx            # Ranked match card with Two-Tier badges
│       │           ├── job-modal.tsx           # Grounded verdict, strengths & gaps modal
│       │           ├── matches-feed.tsx        # Filterable Top 15 matches feed
│       │           ├── navbar.tsx              # Application header & user identity
│       │           └── resume-dropzone.tsx     # Drag-and-drop resume upload zone
│       ├── package.json              # Web dependencies
│       └── tsconfig.json             # TypeScript compiler configuration
│
├── scripts/                          # Data, migration, and verification utilities
│   ├── migrate.py                    # Supabase PostgreSQL schema, HNSW index & RPCs
│   ├── test_matching_engine.py       # 16-suite non-rubber-stamp automated test runner
│   ├── recompute_palak_matches.py    # Match calibration verification script
│   ├── backfill_job_skills.py        # Catalog skill extraction backfiller
│   └── crawler/                      # ATS scraper modules (Greenhouse, Lever, Ashby)
│
├── architecture.md                   # Explicit system architecture & ASCII diagrams
├── decision.md                       # Architectural Decision Records (ADRs 1–10)
├── .env.example                      # Environment variables template
└── README.md                         # Project documentation
```

---

## 🛠️ Tech Stack & Dependencies

### Application Layer
- **Backend API:** [FastAPI](https://fastapi.tiangolo.com/) (0.110+) running on [Uvicorn](https://www.uvicorn.org/) with asynchronous event loops.
- **Frontend Dashboard:** [Next.js](https://nextjs.org/) 16.3 (App Router), [React](https://react.dev/) 19.2, [TypeScript](https://www.typescriptlang.org/) 5.0, and [Tailwind CSS](https://tailwindcss.com/) v4.
- **Authentication:** [Supabase Auth](https://supabase.com/auth) issuing asymmetric RS256/HS256 JWT tokens.

### Data & Machine Learning
- **Database:** [PostgreSQL 15](https://www.postgresql.org/) hosted on [Supabase](https://supabase.com/) with the [`pgvector`](https://github.com/pgvector/pgvector) extension.
- **Vector Search:** Hierarchical Navigable Small World (HNSW) cosine index (`m=16`, `ef_construction=64`, runtime `ef_search=150`).
- **Dense Embeddings:** [FastEmbed](https://qdrant.github.io/fastembed/) running `sentence-transformers/all-MiniLM-L6-v2` locally via ONNX Runtime (384 dimensions, zero external API latency/cost).
- **Document Extractors:** `pdfplumber` (for native PDF streams) and `python-docx` (for Word documents).
- **LLM Cross-Attention:** [Groq LPU](https://groq.com/) using `llama-3.3-70b-versatile` or `openai/gpt-oss-120b` (batch listwise evaluation, 8,000 token output buffer).

---

## 🚀 Quickstart & Local Setup Guide

### 1. Prerequisites
- **Python:** Version `3.11` or higher
- **Node.js:** Version `18.18` or `20.x`+ and `npm`
- **Supabase Account:** Free project with PostgreSQL and pgvector enabled
- **Groq API Key:** Free account at [console.groq.com](https://console.groq.com)

---

### 2. Clone Repository & Setup Virtual Environment

```bash
git clone https://github.com/your-username/job-matcher.git
cd job-matcher

# Create and activate Python virtual environment
python -m venv .venv

# Windows Powershell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# Install backend dependencies
pip install -r apps/api/requirements.txt
```

---

### 3. Install Web Dependencies

```bash
cd apps/web
npm install
cd ../..
```

---

### 4. Configure Environment Variables

Create a `.env` file in the root directory:

```bash
cp .env.example .env
```

Populate the `.env` file with your credentials:

```ini
# Supabase Configuration
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your-supabase-anon-public-key
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
DATABASE_URL=postgresql://postgres:your-db-password@db.your-project-id.supabase.co:5432/postgres
JWT_SECRET=your-supabase-jwt-secret

# Frontend Supabase Environment (Required by Next.js)
NEXT_PUBLIC_SUPABASE_URL=https://your-project-id.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-supabase-anon-public-key
NEXT_PUBLIC_API_URL=http://localhost:8000

# Groq LLM Inference API
GROQ_API_KEY=gsk_your_groq_api_key_here

# External Job Sources (Live Search Fallback)
ADZUNA_APP_ID=your_adzuna_app_id
ADZUNA_APP_KEY=your_adzuna_app_key
JOOBLE_API_KEY=your_jooble_api_key
```

---

### 5. Execute Database Schema Migrations

Run the automated migration script to create tables, HNSW indexes, RLS policies, and stored procedures:

```bash
python scripts/migrate.py
```

Expected output:
```text
Connecting to database...
Executing schema migration...
Schema successfully applied!
Verified Public Tables: ['jobs', 'matches', 'profiles', 'resumes']
```

---

### 6. Start Development Servers

Open two terminal sessions:

#### Terminal 1: Backend API (FastAPI)
```bash
# From workspace root with .venv activated:
uvicorn app.main:app --app-dir apps/api --reload --port 8000
```
Backend will be available at: `http://localhost:8000` (API documentation at `http://localhost:8000/docs`).

#### Terminal 2: Frontend Web App (Next.js)
```bash
cd apps/web
npm run dev
```
Frontend will be available at: `http://localhost:3000`.

---

## 🔌 API Reference & Specifications

All user endpoints require a valid Supabase JWT bearer token passed in the `Authorization` header:  
`Authorization: Bearer <SUPABASE_JWT_TOKEN>`

### Endpoints Overview

| Method | Endpoint | Description | Request Body | Response Status |
|---|---|---|---|---|
| `GET` | `/health` | System health check & service status | None | `200 OK` |
| `GET` | `/me` | Returns authenticated user profile & role | None | `200 OK` |
| `POST` | `/resumes/upload` | 5-layer document validation, parsing & background matching enqueue | `multipart/form-data` (`file`) | `200 OK` |
| `GET` | `/resumes/active` | Retrieves current active resume metadata & signed download URL | None | `200 OK` |
| `DELETE` | `/resumes/active` | Purges active resume, storage file, profile, and all matches | None | `200 OK` |
| `GET` | `/profiles/me` | Retrieves parsed structured profile JSON | None | `200 OK` |
| `GET` | `/matches` | Fast read-aside (<2ms) retrieval of Top 15 matches | Query params: `region`, `limit` | `200 OK` |

---

### Sample Request: Upload Resume

```bash
curl -X POST "http://localhost:8000/resumes/upload" \
  -H "Authorization: Bearer YOUR_SUPABASE_JWT" \
  -F "file=@/path/to/resume.pdf"
```

#### Sample Response:
```json
{
  "success": true,
  "active": {
    "id": "7b5e40e2-63b7-4c31-904d-616a17850001",
    "filename": "candidate_resume.pdf",
    "file_size": 145280,
    "storage_path": "resumes/13d60130-2efb-4a6b-b8b1-730e616a1785/candidate_resume.pdf"
  },
  "profile": {
    "headline": "Full Stack Developer",
    "skills": ["Python", "FastAPI", "React", "PostgreSQL", "Docker"],
    "experience_years": 0.0,
    "full_time_experience_years": 0.0,
    "internship_months": 6,
    "is_fresher": true,
    "preferred_roles": ["Software Engineer", "Backend Developer"],
    "is_cache_hit": false,
    "has_embedding": true
  },
  "characters_extracted": 3412
}
```

---

### Sample Request: Get Top Matches

```bash
curl -X GET "http://localhost:8000/matches?region=india&limit=15" \
  -H "Authorization: Bearer YOUR_SUPABASE_JWT"
```

#### Sample Response:
```json
{
  "matches": [
    {
      "job_id": "c7a8b9e0-f1d2-4e3a-8b5c-6d7e8f9a0b1c",
      "title": "Associate Software Engineer",
      "company": "Mitratech",
      "location": "Hyderabad, India",
      "region": "india",
      "match_score": 94,
      "matched_skills": ["python", "fastapi", "postgresql", "rest"],
      "missing_skills": ["docker", "aws"],
      "explanation": "Your RailMind project proves strong proficiency with FastAPI and relational database design. However, you lack experience with AWS container deployments.",
      "score_breakdown": {
        "verdict": "Your RailMind project proves strong proficiency with FastAPI and relational database design. However, you lack experience with AWS container deployments.",
        "strengths": ["Python", "FastAPI", "PostgreSQL", "REST APIs"],
        "gaps": ["Docker", "AWS"],
        "deductions": [
          {"skill": "Docker", "points": 4, "reason": "No containerization in portfolio"},
          {"skill": "AWS", "points": 2, "reason": "Cloud deployment experience missing"}
        ],
        "capability_fit": 95,
        "tooling_fit": 80,
        "seniority_fit": 90,
        "math_score": 92,
        "blended_score": 94
      },
      "source_url": "https://boards.greenhouse.io/mitratech/jobs/123456"
    }
  ],
  "total_evaluated": 15,
  "live_fallback_triggered": false,
  "strong_matches_count": 12
}
```

---

## 🧮 Matching Engine Math & Grounding Rubric

### 1. Stage 1: pgvector Distance & Seniority Knockout
- Cosine Distance: $D = j.\text{embedding} \Leftrightarrow \text{query\_embedding}$
- Raw Cosine Similarity: $S_{\text{raw}} = 1.0 - D$
- **SQL Hard Knockout Invariant:** If `is_fresher_candidate = true`, any posting with `normalized_title` containing `(senior|sr|lead|architect|manager|staff|principal|director|vp|head of)` is filtered out at the query level.

### 2. Stage 2: Hybrid Mathematical Scoring
1. **Semantic Scaling:**  
   $$S_{\text{norm}} = \text{clamp}\left(\frac{S_{\text{raw}} - 0.30}{0.75 - 0.30}, 0.0, 1.0\right)$$
2. **Bayesian Denominator Floor:**  
   $$C_{\text{skill}} = \frac{|\text{Candidate Skills} \cap \text{Job Skills}|}{\max(|\text{Job Skills}|, 3)}$$
3. **Title Boost:** $B_{\text{title}} = +0.05$ (+5%) if candidate preferred role matches job title tokens.
4. **Base Score:**  
   $$\text{Base Score} = 0.40 \times S_{\text{norm}} + 0.60 \times C_{\text{skill}} + B_{\text{title}}$$
5. **Non-Linear Reality Dampener ($D_{\text{skill}}$):**
   - $C_{\text{skill}} \ge 0.50 \implies 1.00$
   - $0.25 \le C_{\text{skill}} < 0.50 \implies 0.85$
   - $0.00 < C_{\text{skill}} < 0.25 \implies 0.60$
   - $C_{\text{skill}} = 0.00 \implies 0.35$ (Knockout penalty for 0 matching skills)
6. **Deterministic Math Score:**  
   $$\text{Score}_{\text{math}} = \text{round}(\text{clamp}(\text{Base Score} \times D_{\text{skill}} \times 100, 0, 100))$$

### 3. Stage 3: Groq LLM Cross-Attention Rubric
Groq evaluates Top 15 finalists in a listwise batch prompt (`max_tokens: 8000`, `temperature: 0.1`):
1. **Capability Fit ($50\%$ weight):** Evaluates candidate's verified projects fulfilling core responsibilities.
2. **Tooling Fit ($30\%$ weight):** Evaluates explicit tool alignment minus gaps.
3. **Seniority & Scope Fit ($20\%$ weight):** Entry-level suitability (typically 65–85 for freshers).
4. **Itemized Deductions:** Subtracted directly from raw LLM score (capped at 15 points maximum deduction):  
   $$\text{Score}_{\text{llm}} = \text{clamp}\left(0.50 \times \text{Cap} + 0.30 \times \text{Tool} + 0.20 \times \text{Sen} - \min\left(15, \sum \text{Deductions}\right), 0, 100\right)$$
5. **Final Blended Score:**  
   $$\text{Score}_{\text{final}} = \text{round}(0.30 \times \text{Score}_{\text{math}} + 0.70 \times \text{Score}_{\text{llm}})$$

---

## 🧪 Comprehensive Automated Verification Suite

The repository contains an exhaustive 16-suite non-rubber-stamp integration test runner covering edge cases, math clamping, Bayesian floors, reality dampeners, SQL seniority knockouts, and real PDF resumes.

### Running the Test Suite

```bash
# Make sure .venv is active and .env is configured:
python scripts/test_matching_engine.py
```

### Verification Matrix (16 Passed Suites)

| Test ID | Test Suite Name | Verified Behavior |
|---|---|---|
| **SUITE 1** | Math Clamping & Invariant Bounds | Evaluates 1,000 synthetic cosine/skill pairs; asserts $\text{Score} \in [0, 100]$ strictly. |
| **SUITE 2** | Zero-Division & Empty Profile Guard | Tests 0 candidate skills, 0 job skills; asserts 0 runtime exceptions and clean fallback. |
| **SUITE 3** | Bayesian Denominator Floor Verification | Asserts 1-skill job match cannot exceed 60% without multi-skill evidence. |
| **SUITE 4** | Reality Dampener Knockout Verification | Asserts candidate with 0 matching skills on multi-skill job drops to $<25\%$. |
| **SUITE 5** | Role Title Alignment Boost | Asserts matching title tokens grant +5% bonus without distorting math clamping. |
| **SUITE 6** | SQL Seniority Knockout Invariant | Asserts 0 jobs with `required_years > 1` or senior titles are returned for freshers. |
| **SUITE 7** | SQL Regional Partition Isolation | Asserts `'india'` query returns 0 US jobs and `'us'` query returns 0 India jobs. |
| **SUITE 8** | HNSW Graph Node Exploration | Verifies `ef_search = 150` yields identical nearest neighbors across repeated executions. |
| **SUITE 9** | Groq Listwise JSON Schema Adherence | Validates batch JSON response format, deduction arithmetic, and score blending. |
| **SUITE 10**| Groq 429 Rate-Limit Fallback Resilience| Simulates 429 rate limit; asserts graceful fallback to deterministic math scores. |
| **SUITE 11**| In-Process Worker Concurrency Shield | Tests concurrent enqueueing; asserts `Semaphore(2)` and deduplication shield work. |
| **SUITE 12**| Database Persistence & Cache Contract | Verifies identical content hash bypasses worker; verify deletion cascades to 0. |
| **SUITE 13**| Read-Aside Latency Benchmark | Asserts cached `get_persisted_matches` executes in $<2\text{ms}$ ($0.11\text{ms}$ measured). |
| **SUITE 14**| Real Candidate PDF 1: Medhansh | AI/ML profile: confirms Applied AI, ML, and MLOps roles dominate Top 15. |
| **SUITE 15**| Real Candidate PDF 2: Palak | Full-Stack Fresher: confirms `getwingapp` calibrates to ~74% honest fit. |
| **SUITE 16**| Frontend TypeScript Compiler Check | Runs `npx tsc --noEmit` across `apps/web`; asserts **0 type errors**. |

---

## 🔒 Security Model & Isolation

1. **Row-Level Security (RLS):** All user tables (`resumes`, `profiles`, `matches`) enforce PostgreSQL RLS policies checking `auth.uid() = user_id`. Cross-user access is impossible at the database engine level.
2. **Private Storage Isolation:** Candidate documents are stored in private Supabase Storage buckets under `resumes/{user_id}/{safe_filename}`. Download URLs are pre-signed with short 15-minute expirations.
3. **Secret Isolation:** The Supabase `SERVICE_ROLE_KEY` is exclusively configured on the backend and crawler environments. The Next.js frontend receives only the public `anon` key.
4. **Input Defense:** The 5-layer document validation pipeline blocks MIME spoofing, path traversal (`../`), null-byte poisoning, and zip bomb decompression attacks.

---

## 🚢 Deployment Architecture

| Component | Target Host | Tier / Details |
|---|---|---|
| **Frontend** | [Vercel](https://vercel.com/) | Next.js App Router (Hobby / Pro tier) |
| **Backend API** | [Railway](https://railway.app/) or [Render](https://render.com/) | Always-on Python container running Uvicorn |
| **Database & Vector** | [Supabase](https://supabase.com/) | Managed PostgreSQL 15 + pgvector (Mumbai / US-East) |
| **Catalog Crawler** | [GitHub Actions](https://github.com/features/actions) | Scheduled cron job executing ingestion scripts |
| **LLM Inference** | [Groq Cloud](https://groq.com/) | High-speed LPU inference endpoints |

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
