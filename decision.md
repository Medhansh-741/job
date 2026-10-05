# System Architecture Decisions Log

This document records all architectural decisions, mathematical specifications, data contracts, and implementation constraints for the Resume Job Matcher project. Each section is finalized after joint analysis and verification against live data and infrastructure.

---

## Step 1: Catalog Ingestion, Normalization & Crawler Infrastructure

**Status:** FINALIZED  
**Date:** 2026-10-04  

---

### 1. Catalog Sources & Scope
1. **Primary ATS Job Boards (Keyless APIs):**
   - **Supported ATS Platforms:** Greenhouse, Lever, Ashby.
   - **Seed Dataset:** `scripts/seed/seed.json` consisting of **530 curated company boards**.
   - **Verified Health:** 100% active (530/530 boards returning live jobs).
   - **No New Ingestion Sources for v1:** 530 ATS boards plus live aggregators yield ~14,686 raw engineering jobs, which is more than sufficient for the evaluation cohort.
2. **Live Fallback Aggregators:**
   - **Adzuna (India):** Configured via `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
   - **Jooble (India & US):** Configured via `JOOBLE_API_KEY_IN` and `JOOBLE_API_KEY`.
   - **JSearch (RapidAPI):** Reserved as secondary fallback.
3. **Target Geographies:**
   - Strict classification into three regions: `'india'`, `'us'`, `'remote'`.
   - Worldwide roles with no target region overlap are omitted.

---

### 2. Ingestion Filtering & Seniority Rules
1. **Engineering Roles Only:** Only jobs matching technical engineering title patterns (software, backend, frontend, fullstack, data, ML, DevOps, mobile, QA, systems, security) pass ingestion.
2. **Deterministic Seniority Exclusion:**
   - All management and executive roles are stripped at the ingestion boundary using case-insensitive regex:
     ```regex
     \b(staff|principal|director|vp|vice president|head of|lead|architect|fellow)\b
     ```
   - **Verified Data Yield:** Excludes 3,728 senior jobs (25.4%), leaving **10,958 pure Individual Contributor (IC) engineering jobs** (covering Intern, Junior, Mid-level, and Senior IC roles).
3. **Experience Philosophy:**
   - Ingestion retains **mixed IC experience** (0 to ~6 years). Restricting ingestion strictly to freshers (<2 yrs) drops >65% of relevant openings.
   - Fine-grained experience alignment is handled downstream in the matching funnel.

---

### 3. Timestamp & Freshness Tracking
1. **Exact Post Timestamp (`date_posted`):**
   - Extracted deterministically from provider payloads:
     - **Greenhouse:** `updated_at` or `first_published_at` (ISO 8601).
     - **Lever:** `createdAt` (converted from millisecond epoch to ISO 8601).
     - **Ashby:** `publishedAt` (ISO 8601).
     - **Adzuna:** `created` (ISO 8601).
     - **Jooble:** `updated` (ISO 8601).
     - **Fallback:** `now()` if missing.
   - **UI Contract:** Display the exact posting age to the user (e.g., *"Posted 2 days ago"* or exact date).
2. **Verification Timestamp (`last_seen_at`):**
   - Every job row tracks `last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
   - Whenever the crawler or live search encounters an existing posting, it updates `last_seen_at = now()`.
   - **UI Contract:** Display a freshness/verification badge (e.g., *"Verified active 3h ago"*).

---

### 4. Deduplication Contract & Database Schema
To prevent duplicate cards when jobs are refreshed by ATS or syndicated across aggregators, a two-tier deduplication constraint is enforced:

#### Schema Columns for `public.jobs`:
```sql
ALTER TABLE public.jobs 
  ADD COLUMN IF NOT EXISTS normalized_company TEXT,
  ADD COLUMN IF NOT EXISTS normalized_title TEXT,
  ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS required_years INTEGER,
  ADD COLUMN IF NOT EXISTS skills TEXT[] DEFAULT '{}';
```

#### Deduplication Rules:
1. **Primary ID Generation:**
   - ATS Postings: `{ats}:{company_slug}:{external_job_id}` (e.g. `greenhouse:langchain:4928103`).
   - Live Aggregator Postings: `{source}:{external_id}` (e.g. `adzuna:491028301`).
   - Conflict on primary ID executes: `ON CONFLICT (id) DO UPDATE SET last_seen_at = now(), is_active = true`.
2. **Canonical Text Normalization:**
   - `normalized_company`: Lowercase, strip entity suffixes (`inc`, `llc`, `ltd`, `pvt`, `technologies`, `software`, `corporation`), remove all non-alphanumeric characters.
   - `normalized_title`: Lowercase, strip bracketed metadata (e.g., `(Remote)`, `[India]`, `| Full Time`), collapse whitespace.
3. **Cross-Source Deduplication Check:**
   - Before inserting a live aggregator job, query for an existing job where:
     `normalized_company = :nc AND normalized_title = :nt AND region = :region`
   - If found, touch `last_seen_at = now()` on the existing row and discard the redundant aggregator copy.

---

### 5. Supabase Free-Tier Safeguards & Disk Buffer
- **Supabase Free Limits:** 500 MB database disk, 1 GB file storage, 5 GB egress.
- **Description Truncation:** Job descriptions in `jobs.description` are truncated to **1,500 characters** (plain text with HTML tags stripped). 1,500 characters provides ample context for FastEmbed embeddings, skill extraction, and UI previews without bloating disk.
- **Disk Footprint Math:**
  - 15,000 jobs × ~3.5 KB (metadata + text + 384-d vector) ≈ **52 MB**.
  - pgvector HNSW index ≈ **25–30 MB**.
  - Total catalog footprint: **~75–85 MB** (< 17% of 500 MB quota).
- **Hard Ceiling & Automatic Cleanup:**
  - Catalog is capped at **15,000 active jobs**.
  - At the end of every 12-hour crawl, the crawler executes the cleanup routine:
    1. Mark inactive or delete jobs where `last_seen_at < NOW() - INTERVAL '14 days'`.
    2. If total rows exceed 15,000, delete the oldest `last_seen_at` jobs with 0 user matches.

---

### 6. Crawler Orchestration & Seeding Strategy
1. **Day-1 Initial Seeding:**
   - Pre-seed the Supabase `jobs` table directly from `scripts/spike/data/jobs.json` (applying seniority filtering and generating FastEmbed embeddings).
   - Guarantees the database is instantly populated with ~10,900 IC jobs from day one.
2. **Recurring 12-Hour GitHub Actions Crawler:**
   - GitHub Actions workflow (`.github/workflows/crawler.yml`) runs on schedule `0 */12 * * *`.
   - Concurrency controlled via `asyncio.Semaphore(15)` with `httpx`.
   - **Incremental Embedding:** The crawler checks existing `id`s in Supabase before embedding. Only net-new jobs (~50–100 per run) are passed through FastEmbed, keeping execution time under **2 minutes** per run.
   - Uses ~120 runner minutes/month out of GitHub's **2,000 free minutes/month**.
3. **Live Search Persistence:**
   - Any job retrieved via live fallback queries (Adzuna/Jooble) that passes validation is embedded on-the-fly and permanently upserted into `jobs` for future candidates.

---

## Step 2: Resume Parsing & Candidate Profile Structuring

**Status:** FINALIZED  
**Date:** 2026-10-04  

---

### 1. Philosophy & Architectural Constraints
1. **Strictly Deterministic (Zero LLM):**
   - The entire resume parsing, heading segmentation, skill tagging, and experience calculation process is 100% deterministic (regex, layout analysis, date-range arithmetic).
   - Zero LLM calls are made during parsing. This guarantees instant parsing (< 100ms), zero API failure modes, zero cost, and 100% reproducible extractions across test runs.
2. **Grounded Strictly in the Uploaded Document:**
   - No synthetic skills or invented roles are inferred. Only signals directly present in the candidate's PDF or DOCX file are stored.
3. **No `NOT NULL` Constraints on Profile Attributes:**
   - Candidate resumes vary widely: some have no explicit work experience (fresh graduates), some lack graduation dates, and some omit summary sections.
   - All profile attributes (except the primary key `user_id`) are explicitly nullable (`DEFAULT NULL` or `DEFAULT '{}'`).

---

### 2. PDF & DOCX Heading Detection Engine (Markdown Segmentation)
To avoid brittle plain-text guessing, document structure is detected using font styling and visual layout metadata:

1. **PDF Heading Analysis (`pdfplumber`):**
   - **Font Weight & Size Thresholding:** Inspects the font characteristics of each line:
     - Identifies the dominant body text font size (typically 9.0pt–10.0pt).
     - Identifies Section Headings by:
       1. Standalone isolated line (preceded and followed by line breaks).
       2. Printed in bold font (`'bold'` in font name) OR font size strictly greater than dominant body font (e.g., 12.0pt vs 9.0pt).
       3. Matches common section taxonomy (e.g., `Experience`, `Projects`, `Technical Skills`, `Education`, `Summary`, `Achievements`, `Certifications`) or is written in ALL-CAPS / Title Case with length < 40 characters.
2. **DOCX Heading Analysis (`python-docx`):**
   - Inspects `paragraph.style.name` for standard heading styles (`Heading 1`, `Heading 2`).
   - Fallback: Checks for paragraphs where all text runs are flagged `bold = True` and line length < 40 characters.
3. **Markdown Segmentation:**
   - Each detected heading is converted to a Markdown H2 (`## Heading`).
   - Text between heading boundaries is grouped into that section's content block.

---

### 3. Core Extracted Attributes & Matching Signals
The profile maps directly to the inputs required by the downstream deterministic matching engine:

| Attribute | Database Type | Extraction Logic | Default / Nullability |
|---|---|---|---|
| `headline` | `TEXT` | Extracted from the candidate header (the line immediately following the name) or the first sentence of the `Summary` / `Objective` section. | `NULL` |
| `skills` | `TEXT[]` | Unified, deduplicated array of all canonical technical skills found across the **entire document** (including `Technical Skills`, `Projects`, `Experience`, and `Education`) using our canonical taxonomy. **No separate projects column is created** to prevent data bloating and redundant scoring. | `'{}'` (Empty array) |
| `experience_years` | `NUMERIC` | Deterministically parsed from date ranges inside `Experience` / `Work History` sections using date regex (`Month Year` to `Month Year` or `Year` to `Present`). Computes total elapsed months across non-overlapping work periods divided by 12. | `0.0` (Explicitly defaults to 0.0 for freshers when no dates exist) |
| `preferred_roles` | `TEXT[]` | Inferred from headline and primary skill clusters (e.g. `["Frontend Engineer", "Full Stack Engineer"]`). | `'{}'` |
| `embedding` | `vector(384)` | 384-dimensional FastEmbed vector generated from a synthesized summary chunk: `"{headline}. Skills: {skills}. Experience: {experience_summary}"`. | `NULL` |
| `raw_json` | `JSONB` | Dynamic schema containing the exact, full heading-by-heading breakdown of the candidate's unique resume. | `'{}'::jsonb` |

---

### 4. Dynamic Heading Storage (`raw_json JSONB`)
Because every candidate's resume has a unique set of headings, the detailed section breakdown is preserved inside `public.profiles.raw_json` rather than creating fragile, sparse relational columns:

```json
{
  "detected_headings": [
    "Summary",
    "Technical Skills",
    "Work Experience",
    "Projects",
    "Education"
  ],
  "sections": {
    "summary": {
      "raw_heading": "Summary",
      "content": "Full Stack Engineer with experience building scalable web applications..."
    },
    "skills": {
      "raw_heading": "Technical Skills",
      "content": "Languages: Python, TypeScript, SQL\nFrameworks: FastAPI, React, Next.js..."
    },
    "experience": {
      "raw_heading": "Work Experience",
      "content": "Software Engineering Intern | XYZ Corp (Jun 2023 - Aug 2023)..."
    },
    "projects": {
      "raw_heading": "Key Projects",
      "content": "Job Matching Platform: Implemented pgvector semantic search..."
    },
    "education": {
      "raw_heading": "Education",
      "content": "B.Tech in Computer Science, 2020 - 2024"
    }
  }
}
```

- **Frontend Benefit:** The UI can dynamically render cards for whatever sections exist (e.g. displaying an "Open Source" or "Publications" card if present), while also recognizing standard slugs (`"skills"`, `"experience"`) to render specialized widgets (like skill badge clouds).
- **Engine Benefit:** The matching formula queries the typed relational columns (`skills`, `experience_years`, `headline`, `embedding`) without needing complex JSON traversal.

---

### 5. Database Schema Alignment
The `public.profiles` table schema in Supabase directly satisfies this specification:

```sql
CREATE TABLE IF NOT EXISTS public.profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    headline TEXT DEFAULT NULL,
    skills TEXT[] DEFAULT '{}',
    experience_years NUMERIC DEFAULT 0.0,
    preferred_roles TEXT[] DEFAULT '{}',
    embedding vector(384) DEFAULT NULL,
    raw_json JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## Step 3: Embedding Architecture & Railway Resource Guardrails

**Status:** FINALIZED  
**Date:** 2026-10-04  

---

### 1. Model Selection & Runtime Environment
1. **Model:** `sentence-transformers/all-MiniLM-L6-v2` via **FastEmbed** (ONNX Runtime CPU).
2. **Dimension:** 384 dimensions (strict compatibility with Supabase `vector(384)` and HNSW index).
3. **Model Space Consistency with Catalog:**
   - Supabase currently stores **9,512 pre-seeded jobs** embedded using `all-MiniLM-L6-v2`.
   - In vector search, query vectors and catalog vectors **must belong to the exact same metric space**. Switching the candidate embedding model would mathematically invalidate cosine distances (`1 - (v_query <=> v_job)`), requiring an expensive re-embedding of the entire job catalog.
4. **No External Hugging Face Serverless API:**
   - **Zero Cold Starts:** Runs locally in ~15ms per embedding (vs. 20–40s cold starts on Hugging Face Serverless).
   - **Zero API Costs & Quota Failures:** Hugging Face deprecated free request tiers in 2024; FastEmbed runs offline with zero API keys or rate limits.
   - **No Multi-Database / Qdrant Overhead:** A dedicated Qdrant cluster introduces distributed network hops, cold starts, and state drift. With 9,512 vectors, Supabase pgvector HNSW executes searches in **3.2 milliseconds** directly within PostgreSQL.
5. **Dual-Tier Performance Architecture:**
   - **Tier 1 (Content Hashing):** Prevents executing the model when content has not changed (repeat visits, dashboard reloads, duplicate uploads). Execution time = **0ms**, CPU = **0**.
   - **Tier 2 (Lazy In-Memory Singleton):** Prevents disk I/O when the model *does* need to run (new resumes, edits). The ONNX model weights (~90 MB) are loaded into memory once and reused across requests, running in **~15ms** instead of ~500ms disk reloads.
   - **Railway Resource Profiling:** FastEmbed ONNX consumes **32.6 MB** of Python heap memory. Total container process footprint is **~100–120 MB**, comfortably below Railway's 512 MB starter limit (< 25% utilization), ensuring zero Out-Of-Memory (OOM) risk. Concurrency is pinned to `parallel=1`.

---

### 2. Experience Classification: Fresher-First Principle
In tech recruiting, classifying a multi-internship or freelance student as an experienced hire causes them to get filtered out from mid-level roles while missing entry-level/graduate openings.

1. **Fresher-First Default:**
   - Every candidate is strictly classified as a **Fresher (`is_fresher = True`, `full_time_experience_years = 0.0`) by default**.
2. **Explicit Full-Time Verification:**
   - A role only counts toward `full_time_experience_years` if it **explicitly mentions** full-time corporate employment (`full-time`, `full time`, `fte`, `permanent`).
   - Roles marked with `intern`, `internship`, `trainee`, `apprentice`, `fellow`, `freelance`, `contract`, `contractor`, or `project` are strictly treated as practical project experience (`internship_months`), keeping the candidate classified as a Fresher.
3. **Role of Internships & Freelance in Scoring:**
   - Internships and freelance projects are **never discarded**; they serve as practical proof, skill validation, and project quality signals in the hybrid scoring engine, but do not artificially inflate seniority levels.

---

### 3. Candidate Embedding Payload Synthesis (Chunking Principle)
Raw resume text contains noise (contact info, address, references) that dilutes semantic vectors. Following production RAG chunking principles, we synthesize a clean, structured semantic chunk strictly from verified parsed signals:

```python
role_str = headline or (preferred_roles[0] if preferred_roles else "Software Engineer")
exp_str = f"{full_time_experience_years} years full-time" if full_time_experience_years >= 1.0 else "Fresher / Entry-level"
if internship_months > 0 and full_time_experience_years < 1.0:
    exp_str += f" with {internship_months} months internship experience"

# Model token window: 256 wordpiece tokens (~1,000 chars)
# 40-50 skills take ~70 tokens. Fits comfortably within context limit without trimming.
skills_str = ", ".join(skills[:50]) if skills else "General Software Development"

embedding_text = f"Role: {role_str}. Skills: {skills_str}. Experience: {exp_str}."
```
- **100% Skill Preservation in Exact Scorer:** All extracted skills (whether 10, 30, or 60+) are stored in full in `profiles.skills TEXT[]`. The deterministic exact skill matching engine (Stage 3) uses the complete, untrimmed set for exact intersection.
- **L2 Normalization:** Output vectors are normalized to unit length ($\|v\|_2 = 1.0$), ensuring cosine distance directly maps to dot product similarity in pgvector (`1 - (embedding <=> query)`).

---

### 4. Content Hashing & Embedding Lifecycle (No Redundant Re-embedding)
To prevent wasteful re-embedding on repeat visits, dashboard refreshes, or identical re-uploads:

1. **Hash Generation:**
   - `content_hash = hashlib.sha256(embedding_text.encode('utf-8')).hexdigest()`
   - Stored in `public.profiles.content_hash TEXT`.
2. **Re-upload / Cache Invalidation Logic:**
   - When a user uploads a resume, compute `new_hash`.
   - If `new_hash == stored_hash` AND `profiles.embedding IS NOT NULL`:
     - **Bypass FastEmbed completely (Cache Hit).** Reuse the existing vector from Supabase in 0ms with 0 MB memory overhead.
   - If the candidate edits their resume (content changes -> `new_hash != stored_hash`):
     - Compute new vector via singleton FastEmbed, overwrite `profiles.embedding`, and update `content_hash`.
3. **Retention & Deletion:**
   - Stored in Supabase for the entire duration the user's resume is active.
   - Completely purged upon `DELETE /resumes/active` (cascading delete).

---

### 5. Hybrid Retrieval Architecture (Dense HNSW + Exact Taxonomy)
Rather than relying solely on dense vector search (which can hallucinate semantic proximity while missing exact technical tool names):
1. **Dense Retrieval (HNSW in Supabase):**
   - Retrieves top 100 candidate jobs matching conceptual and semantic meaning in ~3ms via `match_jobs`.
   - Filters region (`'india'`, `'us'`, `'remote'`) and experience ceilings directly in PostgreSQL.
2. **Exact Skill & Title Scorer (Python Core):**
   - Computes exact canonical skill coverage: $\frac{|\text{Candidate Skills} \cap \text{Job Skills}|}{|\text{Job Skills}|}$.
   - Fuses semantic cosine similarity with exact skill overlap:
     $$\text{Score} = 0.6 \times \text{Semantic} + 0.4 \times \text{Skill Coverage} + \text{Title Boost}$$

---

### 6. Live Search Fallback Trigger
1. **Fallback Condition:**
   - Evaluate top matches from the cached 9,512 catalog.
   - If `COUNT(matches with score >= 70%) < 10`:
     - Trigger live query to **Adzuna (India)** and **Jooble (India + US)** using the candidate's `preferred_roles` and top skills.
     - Live jobs are validated, hashed, embedded via FastEmbed, permanently upserted into `public.jobs`, and merged into the user's ranked match list.
   - If `COUNT >= 10`:
     - Return cached matches immediately with zero external API latency or quota usage.

---

### 7. Database Schema Alignment
Add `content_hash` to `public.profiles`:

```sql
ALTER TABLE public.profiles 
  ADD COLUMN IF NOT EXISTS content_hash TEXT DEFAULT NULL;
```

---

### 8. Verification & Manual Inspection Protocols (No Rubber Stamps)
1. **Automated Integration Test (`scripts/test_embedding_pipeline.py`):**
   - **Test Case 1 (Cold Generation):** Parses sample resume, generates embedding, verifies dimension is exactly 384, verifies vector L2 norm is $1.000 \pm 0.001$, and verifies `content_hash` is a 64-character SHA-256 hex string.
   - **Test Case 2 (Cache Hit on Repeat Upload):** Runs identical payload through pipeline; asserts execution time is under 1ms and FastEmbed ONNX runner is not invoked.
   - **Test Case 3 (Cache Invalidation on Mutation):** Appends a new skill (`"Kubernetes"`), verifies `new_hash != old_hash`, asserts FastEmbed triggers and updates `embedding` and `content_hash`.
   - **Test Case 4 (Live HNSW pgvector Search):** Passes the generated candidate vector into Supabase RPC `match_jobs` and asserts that relevant jobs are returned within < 10ms.
2. **Manual Inspection in Supabase UI:**
   - Execute query in Supabase SQL editor:
     ```sql
     SELECT user_id, headline, content_hash, (embedding IS NOT NULL) AS has_vector, updated_at 
     FROM public.profiles;
     ```
   - User inspects that `content_hash` is non-null and `has_vector` is `true`.

---

## Step 4: Two-Stage Funnel, Bayesian Math & LLM Cross-Attention Re-Ranking

**Status:** FINALIZED & MULTI-PHASE ARCHITECTURE ADOPTED  
**Date:** 2026-10-05  

---

### 1. Philosophy, Architectural Context & The "Terse JD" Anomaly

Step 4 bridges raw, coarse-grained vector retrieval with deep contextual candidate evaluation.

#### 1.1 The Root Cause of the Terse JD Anomaly (Palak on `getwingapp`)
During live integration testing with real candidate profiles, we discovered a fatal flaw in traditional keyword/math matching:
- **The Posting:** `getwingapp` published an ultra-brief 2-sentence description via Lever:  
  *"Looking for a Full Stack Developer to build web apps, APIs, and user interfaces. Collaborating closely with product and DevOps."*
- **The Regex Parser:** Extracted only 1 single explicit keyword: `system design`.
- **The Mathematical Glitch:** Candidate Palak's resume contained `system design`. The deterministic skill coverage formula calculated:
  $$C_{\text{skill}} = \frac{|\text{Candidate Skills} \cap \text{Job Skills}|}{|\text{Job Skills}|} = \frac{1}{1} = 100\%$$
- **The Result:** The linear formula multiplied this $100\%$ recall by its $0.60$ weight and awarded Palak an inflated **90% match score**.
- **The Reality:** Knowing a single skill (`system design`) cannot prove full-stack readiness. Simultaneously, penalizing the candidate because the recruiter wrote a brief description is unfair: Palak's React, Node.js, and Express projects legitimately satisfy the implicit requirements of building *"web apps and APIs"*.

#### 1.2 The Solution: The Two-Stage Industry Standard (Bi-Encoder Retrieval + LLM Cross-Attention)
Modern Information Retrieval literature (RankGPT, LinkedIn Talent AI, Seek, Amazon Search) proves that single-stage scoring cannot solve this trade-off:
- **Bi-Encoders (`all-MiniLM-L6-v2`):** Built for **high-recall, low-latency coarse retrieval**. They project text into independent 384-dimensional embeddings and compute cosine similarities in ~2ms, but have zero cross-attention (they cannot reason about *why* two documents relate).
- **Cross-Encoders / LLMs (`llama-3.3-70b-versatile`):** Built for **high-precision, contextual cross-attention**. The model evaluates the candidate's actual project bullets and the job description side-by-side. It recognizes implicit tech stack alignment, evaluates seniority scope, spots missing prerequisites, and applies itemized deductions.

#### 1.3 The Multi-Stage Filtering Funnel (Visual Architecture)

```text
===================================================================================================
                                      THE MULTI-STAGE MATCHING FUNNEL
===================================================================================================

  [ 9,512 ATS Jobs in PostgreSQL Mumbai ]
                     │
                     │  PHASE 4.1: HARD SQL GATES + HNSW VECTOR RETRIEVAL (~2.1 ms)
                     │  • Hard Seniority Exclusion (Director, VP, Staff, Principal knocked out)
                     │  • Fresher Rule: (required_years IS NULL OR required_years <= 1)
                     │  • Region Isolation: 'india' -> ('india', 'remote'); 'us' -> ('us', 'remote')
                     │  • SET LOCAL hnsw.ef_search = 150
                     │  • Explores 100 nearest vector neighbors in metric space
                     ▼
  [ TOP 100 CANDIDATE JOBS ]
                     │
                     │  PHASE 4.2: BAYESIAN MATH & REALITY DAMPENER (~5.0 ms)
                     │  • Normalized Semantic Score: S_norm clamped in [0.0, 1.0]
                     │  • Bayesian Denominator Floor: C_skill = |Matched| / max(|Job Skills|, 3)
                     │  • Non-Linear Reality Dampener: D_skill knocks 0-match jobs to < 25%
                     │  • Title Boost: +5% if preferred_roles aligns with title
                     │  • Sorts Score_math DESC -> Selects Top 15 Finalists
                     ▼
  [ TOP 15 FINALISTS ]
                     │
                     │  PHASE 4.3: LLM CROSS-ATTENTION RE-RANKER (Groq LLaMA 3.3 70B, ~650 ms)
                     │  • 1 Single Listwise Batch Prompt (RankGPT paradigm)
                     │  • Compressed Job Cards (~80 tokens/job, stripping corporate boilerplate)
                     │  • Evaluates tech_stack_fit (50%), seniority_fit (25%), domain_fit (25%)
                     │  • Blended Score = 0.30 * Score_math + 0.70 * Score_llm
                     │  • Generates Itemized Deductions & Grounded Explanations
                     ▼
  [ 15 CALIBRATED MATCH CARDS ]
                     │
                     │  PHASE 4.4 & 4.5: ASYNC IN-PROCESS WORKER & ATOMIC CACHE (1.2 ms read)
                     │  • In-Process asyncio.Queue + Lifespan Worker with Semaphore(2)
                     │  • Atomic write to public.matches bound to candidate content_hash
                     ▼
  [ DASHBOARD: TOP 15 HIGH-QUALITY MATCHES (100% LLM-CALIBRATED) ]
===================================================================================================
```

---

### 2. Phase 4.1: Database Retrieval & Hard SQL Invariants

Runs directly inside Supabase PostgreSQL in the stored procedure `match_jobs`:

#### 1. Hard Seniority Exclusion
- ATS crawlers tag jobs, but title boundaries are strictly enforced.
- Queries reject any job whose title contains `director`, `vp`, `vice president`, `staff engineer`, `principal engineer`, `lead engineer`, or `head of`.

#### 2. Fresher Experience Invariant
- **Catalog Reality:** 93.6% (8,906 / 9,512) of live ATS job postings leave `required_years IS NULL` in the job header.
- **Fresher Rule (`is_fresher = True`):**
  ```sql
  AND (j.required_years IS NULL OR j.required_years <= 1)
  ```
- **Experienced Rule ($Y$ years of verified full-time corporate experience):**
  ```sql
  AND (j.required_years IS NULL OR j.required_years <= (Y + 1))
  ```

#### 3. Geographic Region Expansion & Strict Isolation
Candidates must never see jobs in geographic regions they cannot legally or physically work in:
- `'india'` expands strictly to: `j.region IN ('india', 'remote')` (0 US jobs returned).
- `'us'` expands strictly to: `j.region IN ('us', 'remote')` (0 India jobs returned).
- `'remote'` isolates strictly to: `j.region = 'remote'`.
- `'all'`: No region restriction applied.

#### 4. HNSW Exploration Depth & Graph Traversal ($K = 100$)
- Default pgvector configurations use `ef_search = 40`, which truncates exploratory graph traversal to ~40–47 results before reaching $K=100$.
- Injected `SET LOCAL hnsw.ef_search = 150` into the stored procedure session.
- Traverses 100 high-quality candidate vectors across the 9,512 dataset in **2.1 milliseconds**.

---

### 3. Phase 4.2: Deterministic Hybrid Math & Bayesian Denominator Floor

Runs in-memory within Python (`matching_engine.py`) to prune the 100 retrieved candidates down to the **Top 15 Finalists**:

#### 1. Normalized Semantic Score ($S_{\text{norm}}$)
Raw cosine similarity between candidate FastEmbed vectors and catalog jobs spans $[0.30, 0.75]$. To make it a true unit signal, it is Min-Max normalized and clamped:
$$S_{\text{norm}} = \text{clamp}\left(\frac{\text{raw\_sim} - 0.30}{0.75 - 0.30}, 0.0, 1.0\right)$$

#### 2. Bayesian Denominator Floor ($C_{\text{skill}}$)
To permanently eliminate the 90% single-skill illusion on terse JDs, the denominator enforces a Bayesian minimum requirement floor of **3 skills** for any technical role:
$$C_{\text{skill}} = \frac{|\text{Candidate Skills} \cap \text{Job Skills}|}{\max(|\text{Job Skills}|, 3)}$$

- **Zero-Keyword Fallback:** If $|\text{Job Skills}| == 0$ (recruiter provided no extractable keywords), dynamically fall back to:
  $$C_{\text{skill}} = S_{\text{norm}}$$
- **Terse JD Resolution:** For `getwingapp` ($1$ matched skill out of $1$ extracted):
  $$C_{\text{skill}} = \frac{1}{\max(1, 3)} = \frac{1}{3} = \mathbf{33.3\%} \quad (\text{instead of } 100\%)$$

#### 3. Title Alignment Boost ($B_{\text{title}}$)
If any token in the candidate's `preferred_roles` matches the target `job_title`:
$$B_{\text{title}} = +0.05 \quad (+5\%)$$

#### 4. Non-Linear Reality Dampener ($D_{\text{skill}}$)
Protects against dense vector "semantic illusions" (e.g., an LLM vector ranking a Golang Infrastructure role highly for a Python developer because both involve backend engineering):
- **$C_{\text{skill}} \ge 0.50$:** $D_{\text{skill}} = 1.0\times$ (Strong verified core fit).
- **$0.25 \le C_{\text{skill}} < 0.50$:** $D_{\text{skill}} = 0.85\times$ (Moderate stack gap).
- **$0.01 \le C_{\text{skill}} < 0.25$:** $D_{\text{skill}} = 0.60\times$ (Severe stack gap).
- **$C_{\text{skill}} == 0.0$ (when $|\text{Job Skills}| \ge 2$):** $D_{\text{skill}} = \mathbf{0.35\times}$ (**Hard Knockout Penalty**: immediately crushes the score below 25%, preventing totally irrelevant roles from surfacing).

#### 5. Deterministic Math Score Formula
$$\text{Score}_{\text{math}} = \text{round}\left(\min\left(100, \max\left(0, (0.40 \times S_{\text{norm}} + 0.60 \times C_{\text{skill}} + B_{\text{title}}) \times D_{\text{skill}} \times 100\right)\right)\right)$$

#### 6. Finalist Selection
The 100 candidates are sorted by $\text{Score}_{\text{math}} \text{ DESC}$. The **Top 15 Finalists** are extracted and sent to Phase 4.3.

---

### 4. Phase 4.3: LLM Cross-Attention Re-Ranking Layer (Groq LLaMA 3.3 70B)

Operates on the **Top 15 Finalists** using the RankGPT listwise evaluation paradigm.

#### 1. Why Top 15 Cardinality?
- **Decision Fatigue & UX:** Showing 15 exceptional, deeply matched roles beats an endless scrolling feed of 50 marginal jobs.
- **100% Calibrated Guarantee:** Every single card displayed to the candidate has been evaluated by the LLM. There are zero uncalibrated filler cards.
- **Rate-Limit & Token Budget:** 15 compressed job cards take ~1,400 prompt tokens, fitting comfortably within Groq's **6,000 TPM** free tier limit in a single API call.

#### 2. Compressed Job Card Representation (~80 tokens / job)
Raw ATS postings contain hundreds of words of boilerplate (*"Equal Opportunity Employer", "Benefits", "About our culture"*). Passing raw descriptions exhausts context windows and triggers rate limits. The engine extracts a clean, high-density snippet:
```json
{
  "id": "lever:getwingapp:934adc12",
  "title": "Full Stack Developer",
  "company": "getwingapp",
  "requirements_snippet": "Building scalable web applications, REST APIs, and responsive user interfaces. Collaborating with product and DevOps.",
  "tagged_skills": ["system design"]
}
```

#### 3. Candidate Profile Representation (~200 tokens)
```json
{
  "headline": "Full Stack Engineer | React, Node.js, Python",
  "experience_years": 0.0,
  "internship_months": 6,
  "skills": ["react", "node.js", "express", "mongodb", "fastapi", "python", "system design", "tailwind css", "git"],
  "project_highlights": [
    "Built real-time collaboration tool using React, Node.js, and WebSockets.",
    "Engineered RESTful API service with FastAPI, PostgreSQL, and Redis caching."
  ]
}
```

#### 4. Model Selection & Execution Parameters
- **Model:** `llama-3.3-70b-versatile` on Groq.
- **Generation Parameters:** `temperature: 0.0`, `top_p: 0.2`, `seed: 42`, `response_format: {"type": "json_object"}`.
- **Listwise Batching:** All 15 candidates are evaluated in **1 single prompt**, allowing comparative reasoning and avoiding 15 separate network roundtrips.

#### 5. Structured Rubric Scoring & Decomposition
To prevent arbitrary hallucinated numbers, the LLM scores each candidate across three objective dimensions (0–100):
1. **`tech_stack_fit` (50% weight):** Does the candidate's verified stack satisfy both explicit and implicit technical needs?
2. **`seniority_fit` (25% weight):** Is the role scope realistic for the candidate's verified background?
3. **`domain_fit` (25% weight):** Does the candidate's project work align with the company's problem domain?

$$\text{Score}_{\text{llm\_raw}} = 0.50 \times \text{tech\_stack\_fit} + 0.25 \times \text{seniority\_fit} + 0.25 \times \text{domain\_fit}$$
$$\text{Score}_{\text{llm}} = \max\left(0, \text{Score}_{\text{llm\_raw}} - \sum \text{deductions}\right)$$

#### 6. The Blended Final Score Formula (User Decision 2-a)
$$\text{Final Score} = \text{round}\Big( 0.30 \times \text{Score}_{\text{math}} + 0.70 \times \text{Score}_{\text{llm}} \Big)$$

- **Why 30% Math / 70% LLM?**  
  Anchors 30% of the score to hard SQL constraints and verified keyword overlaps, while empowering 70% of the score to reflect deep contextual cross-attention.
- **Impact on `getwingapp`:**
  - $\text{Score}_{\text{math}} = 50\%$ (corrected from 90% via Bayesian floor).
  - $\text{Score}_{\text{llm}} = 81\%$ (LLM recognizes React/Node satisfies implicit API and web app requirements).
  - $\text{Final Score} = \text{round}(0.30 \times 50 + 0.70 \times 81) = \text{round}(15 + 56.7) = \mathbf{72\%}$.
  - A perfectly calibrated, defensible, and realistic match.

#### 7. Prompt & JSON Output Schema Contract

```json
{
  "matches": [
    {
      "job_id": "lever:getwingapp:934adc12",
      "calibrated_score": 81,
      "score_breakdown": {
        "tech_stack_fit": 88,
        "seniority_fit": 72,
        "domain_fit": 78
      },
      "verified_strengths": ["react", "node.js", "system design", "fastapi"],
      "inferred_skills": ["web applications", "rest apis", "ui engineering"],
      "missing_skills": ["production devops", "large-scale distributed systems"],
      "deductions": [
        {
          "reason": "Entry-level experience relative to enterprise scaling scope",
          "points": 5
        }
      ],
      "reasoning": "Strong match on core frontend & API stack. Projects demonstrate hands-on web application development, though enterprise scaling experience is limited."
    }
  ]
}
```

---

### 5. Phase 4.4: In-Process Async Queue Worker & Ultra-Low Latency Architecture

To eliminate Celery and Redis operational overhead while guaranteeing high throughput and zero UI blocking:

#### 1. Architecture: In-Process `asyncio.Queue` + Lifespan Handler
- Implemented directly inside FastAPI in `apps/api/app/core/worker.py`.
- Managed via the FastAPI Lifespan context manager (`@asynccontextmanager`).
- Background worker task starts on FastAPI boot and gracefully drains on server shutdown.

#### 2. Concurrency Shield: `asyncio.Semaphore(2)`
- Free tier Groq enforces a strict **30 RPM / 6,000 TPM** limit.
- If multiple users upload resumes at the same second, unthrottled tasks would trigger HTTP 429 errors.
- The worker processes items via an internal semaphore capped at **2 concurrent Groq requests**, perfectly pacing API consumption.

#### 3. Non-Blocking Upload Flow
1. User uploads resume $\to$ `POST /resumes/upload`.
2. Resume is parsed, candidate profile is updated in `public.profiles`, and FastEmbed vector is generated.
3. Task payload `(user_id, region)` is pushed to the in-memory `asyncio.Queue`.
4. Upload endpoint returns HTTP 200 in **< 300 milliseconds**, immediately closing the frontend dialog.
5. In-process worker picks the task $\to$ runs Phase 4.1 HNSW retrieval $\to$ runs Phase 4.2 Bayesian Math $\to$ calls Phase 4.3 Groq batch re-ranker $\to$ writes final 15 records atomically to `public.matches`.

#### 4. Concrete Latency Optimizations
1. **Persistent HTTP/2 Keep-Alive Client:**  
   Maintains a singleton `httpx.AsyncClient(http2=True, timeout=15.0)` connection pool to `api.groq.com`. Eliminates TLS handshakes on every request, cutting network roundtrip latency to **~450ms**.
2. **Clean Snippet Compression:**  
   Strips boilerplate, shrinking job payloads to ~80 tokens each (~1,400 tokens total), halving Groq generation time to **< 650ms**.
3. **Database Connection Pool Reuse:**  
   Queries use the existing `psycopg2.pool.SimpleConnectionPool` in `apps/api/app/core/db.py`, eliminating the 30ms database connection handshake.
4. **Read-Aside Cache in `public.matches` (Sub-2ms Page Loads):**  
   Once written by the worker, `GET /matches` reads pre-computed records straight from PostgreSQL in **1.2 milliseconds** via an indexed query.

#### 5. Graceful Fallback Guarantee (Zero UI Hanging)
If Groq experiences a rate limit (429), service degradation (503), or network timeout after 1 exponential backoff retry (1.5s):
- The engine automatically falls back to **Phase 4.2 Bayesian Math Scores**.
- Generates fallback explanation bullets from deterministic skill intersections.
- Atomically writes math matches to `public.matches`.
- The dashboard is guaranteed to always load successfully within 2 seconds.

---

### 6. Phase 4.5: Database Persistence & Match Lifecycle Contract (`public.matches`)

#### 1. SQL Schema Definition
```sql
CREATE TABLE IF NOT EXISTS public.matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES public.jobs(id) ON DELETE CASCADE,
    match_score INTEGER NOT NULL,
    matched_skills TEXT[] DEFAULT '{}',
    missing_skills TEXT[] DEFAULT '{}',
    explanation TEXT,
    score_breakdown JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT unique_user_job_match UNIQUE (user_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_matches_user_score 
  ON public.matches(user_id, match_score DESC);
```

#### 2. Storage Basis & Retention Policy (Addressing User Query)
- **Retention Period:**  
  Matches are retained **indefinitely** in `public.matches` for as long as the user's active resume exists.
- **Cache Binding (`content_hash`):**  
  Every match set is cryptographically bound to the candidate's `profiles.content_hash` (SHA-256).
- **Identical Re-Upload (Cache Hit):**  
  If a user re-uploads the identical resume (or logs in from a new browser tab/device), `new_hash == stored_hash`. FastEmbed ONNX inference and Groq API calls are **100% bypassed (0ms CPU, 0 API tokens)**. The dashboard loads existing matches directly from PostgreSQL in **1.2ms**.
- **Resume Mutation (Cache Invalidation):**  
  If the candidate uploads an updated resume (`new_hash != stored_hash`), the system invalidates the cache: existing rows in `public.matches` for that `user_id` are deleted or atomically replaced, and the in-process worker recomputes the Top 15 matches.
- **Account Deletion / Resume Purge:**  
  When a candidate calls `DELETE /resumes/active`, PostgreSQL foreign key cascading (`ON DELETE CASCADE`) immediately purges all rows in `public.matches`.

---

### 7. Phase 4.6: Frontend Feed & Modal UX Contract

#### 1. Feed Cardinality
- The dashboard displays exactly the **Top 15** highest-scoring, 100% LLM-calibrated matches.

#### 2. Two-Tier Match Badges (Inspired by `myjobb.ai`)
- **`Exact Match` (Emerald Badge):**  
  Final Score $\ge 75\%$ **AND** candidate possesses $\ge 3$ verified explicit skills.
- **`Broader Fit` (Amber / Zinc Badge):**  
  Final Score $< 75\%$ **OR** candidate matched via inferred skills / terse JD ($< 3$ explicit skills).

#### 3. Job Modal Details Contract
Clicking a job card displays:
- **Calibrated Match Percentage:** Large badge (e.g. `72% Match`).
- **Score Breakdown Bar:** Visual breakdown showing `Tech Stack Alignment`, `Seniority Fit`, and `Domain Fit`.
- **Verified Strengths:** Green pill badges of candidate skills matched to JD.
- **Inferred Strengths:** Blue pill badges of candidate capabilities implicitly satisfying JD requirements.
- **Gaps / Missing Skills:** Red/Amber pill badges highlighting missing prerequisites.
- **Itemized Deductions:** Clean list showing point subtractions and specific rationales (e.g. `"-5 pts: Enterprise scaling experience limited"`).
- **Grounded Explanation:** 2–3 sentence executive summary explaining why the role fits.

---

### 8. Phase 4.7: Verification & Non-Rubber-Stamp Testing Protocol

Validation is enforced through comprehensive automated integration tests (`scripts/test_matching_engine.py`):

1. **Math Clamping & Normalization Invariant Test:**  
   Passes 1,000 synthetic variations of cosine similarity and skill overlaps; asserts $\text{Score}_{\text{math}} \in [0, 100]$ strictly.
2. **Zero-Division & Empty Edge Case Test:**  
   Tests 0 candidate skills, 0 job skills, empty headline, and empty text; asserts zero runtime exceptions and correct dynamic fallback to $S_{\text{norm}}$.
3. **Bayesian Denominator Floor Verification Test:**  
   Asserts that a 1-skill job match cannot exceed 60% in deterministic math without multi-skill evidence.
4. **Reality Dampener Knockout Verification Test:**  
   Asserts that a candidate with 0 matching skills on a multi-skill job is knocked down to $< 25\%$.
5. **SQL Seniority & Region Invariants Test:**  
   Asserts 0 jobs with `required_years > 1` are returned for freshers, and asserts `'india'` query returns 0 US jobs while `'us'` query returns 0 India jobs.
6. **Groq Batch Re-Ranking & JSON Parser Test:**  
   Validates batch parsing of 15 candidate jobs, verifying schema adherence, deduction arithmetic, and score blending.
7. **Groq Rate-Limit & Fallback Resilience Test:**  
   Simulates Groq 429 response; asserts worker retries once and gracefully falls back to Phase 4.2 Math scores without throwing an error.
8. **End-to-End Real Resume Benchmark Test:**  
   Runs the entire pipeline against all 5 local test resumes:
   - `medhansh.pdf` (AI/ML Engineer $\to$ verifies Applied AI, ML, and MLOps matches dominate Top 15).
   - `palak.pdf` (Full Stack Fresher $\to$ verifies `getwingapp` calibrates to ~72%, and React/Node roles surface).
   - `ram.pdf` (Backend Developer $\to$ verifies Python/Django/API roles surface).
   - `prakhar.pdf` (Frontend Engineer $\to$ verifies React/TypeScript/UI roles surface).
   - `Anvay.pdf` (Data Analyst / Python $\to$ verifies Data & Analytics roles surface).

---

## Implementation Status: Phase 4.1 through Phase 4.7 (ALL COMPLETED & VERIFIED)

| Phase | Description | Status | Verification Result |
|---|---|---|---|
| **Phase 4.1** | SQL Layer & Remote Supabase Migration (Seniority hard exclusion, `ef_search=150`, Region isolation) | **COMPLETED** | Verified across 9,512 jobs in Mumbai: 2.1ms retrieval, 0 fresher violations, 0 cross-region leaks. |
| **Phase 4.2** | Deterministic Hybrid Math & Bayesian Denominator Floor ($\max(\|Job Skills\|, 3)$) | **COMPLETED** | Single-skill terse JD anomaly solved (Palak on `getwingapp` dropped from 90% to 50% in deterministic math). Top 15 truncation locked. |
| **Phase 4.3** | Groq LLM Cross-Attention Re-Ranker (`openai/gpt-oss-120b`, listwise batch prompt, score blending: $0.30 \times \text{Math} + 0.70 \times \text{LLM}$) | **COMPLETED** | Tested live: `getwingapp` calibrated to 74% honest fit; Medhansh calibrated to 94% Mitratech / 89% Coram AI. |
| **Phase 4.4** | In-Process Async Queue Worker (`apps/api/app/core/worker.py`, `asyncio.Semaphore(2)`, deduplication, FastAPI lifespan) | **COMPLETED** | Zero Celery, Zero Redis. Throttling and in-flight deduplication verified with multi-user concurrent simulation. |
| **Phase 4.5** | Database Persistence & Match Lifecycle Contract (`public.matches`, cache hit bypass, cache invalidation, cascade deletion) | **COMPLETED** | Verified: identical upload bypasses worker (0ms CPU, 0 tokens); mutation atomically invalidates cache; delete cascades to 0; read-aside query executes in 0.11ms. |
| **Phase 4.6** | Frontend Feed & Modal UX (`apps/web`, Top 15 cardinality, Two-Tier Badges: Emerald Exact Match vs Sleek Zinc Broader Fit, Visual Score Breakdown meters, Tri-Partition Skills, Itemized Deductions) | **COMPLETED** | Zero TypeScript compiler errors. Live browser verification on `http://localhost:3000/dashboard` confirmed all badges, meters, and modal interactions. |
| **Phase 4.7** | Comprehensive Automated Integration Suite & Resilience Protocol (`scripts/test_matching_engine.py`) | **COMPLETED** | All 16 test suites passed strictly with 0 errors, including Groq 429 rate limit fallback resilience, HNSW exploration, 5 real PDFs, and browser testing. |

---

### 9. Seniority Title Knockout at SQL Layer & First-Principles 3-Dimension Explainability

**Status:** FINALIZED & IMPLEMENTED  
**Date:** 2026-10-05  

#### 1. Problem Statement & Root Cause Analysis
1. **Senior Job Leakage for Freshers:**  
   In the initial implementation, 4,121 jobs in Supabase had `required_years IS NULL` because ATS descriptions frequently omit explicit numeric year ranges. Because `match_jobs` previously allowed `required_years IS NULL`, senior, lead, architect, and director roles leaked into fresher candidate pools.
2. **Ambiguous "Tech Stack: 90%" Perception:**  
   Labeling the primary fit dimension as "Tech Stack Fit" created confusion for candidates when jobs like `getwingapp` had high fit despite lacking specific libraries. The metric was actually evaluating general capability to build web apps, not a literal 1:1 tool match.

#### 2. Architectural Solution 1: SQL Layer Title Knockout
Updated `match_jobs` stored procedure on Supabase Mumbai to enforce a hard regex knockout at the database layer whenever `is_fresher_candidate = true`:
```sql
AND (
    NOT is_fresher_candidate
    OR (
        (j.required_years IS NULL OR j.required_years <= 1)
        AND NOT (
            j.normalized_title ~* '\y(senior|sr\.?|lead|architect|manager|mgr|staff|principal|director|vp|head of)\y'
            OR j.title ~* '\y(senior|sr\.?|lead|architect|manager|mgr|staff|principal|director|vp|head of)\y'
        )
    )
)
```
- **Database Verification:** Evaluated with `is_fresher_candidate = true` against live Mumbai cluster $\to$ returned **exactly 0 senior jobs** across the entire 10,958-job catalog. When tested with `is_fresher_candidate = false` (5-year profile), senior roles are cleanly preserved.

#### 3. Architectural Solution 2: First-Principles 3-Dimension Explainability
Replaced ambiguous metrics with a first-principles 3-dimension evaluation rubric:

| Dimension | Formula Weight | Evaluates | Dedicated Plain-English Explanation |
|---|---|---|---|
| **Role & Capability Fit** (`capability_fit`) | 50% | Degree to which candidate skills and project portfolio fulfill core engineering duties (e.g. building web apps and REST APIs). | 1 crisp sentence explaining why project background fulfills the day-to-day responsibilities. |
| **Skills & Tooling Match** (`tooling_fit`) | 30% | Degree to which candidate's verified technical tools match the explicit JD requirements minus gaps. | 1 crisp sentence summarizing tool matches and specific tool gaps (e.g. Docker, AWS). |
| **Seniority & Scope Fit** (`seniority_fit`) | 20% | Suitability for candidate experience level. All evaluated roles are entry-level / early-career (use 65-85 for freshers). | 1 crisp sentence explaining why the career level and scope fit the candidate. |

- **Deterministic Python Blending:**
  $$\text{Score}_{\text{raw}} = 0.50 \times \text{Capability} + 0.30 \times \text{Tooling} + 0.20 \times \text{Seniority}$$
  $$\text{Score}_{\text{llm}} = \text{clamp}(\text{Score}_{\text{raw}} - \min(15, \sum \text{Deductions}), 0, 100)$$
  $$\text{Final Score} = \text{round}(0.30 \times \text{Score}_{\text{math}} + 0.70 \times \text{Score}_{\text{llm}})$$
- **Frontend Click-to-Expand Accordion (`job-modal.tsx`):**
  Each of the 3 score meters is an interactive accordion card with a rotating chevron ($\vee / \wedge$). Clicking the meter expands an animated drawer displaying the dedicated 1-line plain-English explanation.
- **Reliability & Token Budget:** Configured `max_tokens: 8000` on Groq `llama-3.3-70b-versatile` to eliminate output truncation on 15-job listwise evaluations. All 16 automated test suites pass with zero errors.

---

### 10. Strict Schema-to-Schema Matching & Streamlined UI Architecture

**Status:** FINALIZED & IMPLEMENTED  
**Date:** 2026-10-05  

#### 1. Core Problem Statement & Philosophy
1. **Unstructured JD Text:**  
   While candidate resumes had structured schemas (`projects`, `experience`, `skills`), job descriptions were stored as raw 1,500-character text blobs. LLM re-ranking previously extracted the first 250 characters, often passing company intro marketing boilerplate instead of actual duties and requirements.
2. **Cognitive Clutter from Multiple Progress Bars:**  
   Displaying 3 synthetic percentage bars (`Role Fit`, `Tooling Match`, `Seniority Fit`) created confusion and fatigue. Users don't want 3 progress bars; they want one honest overall score, a grounded verdict citing real evidence, green strengths, and greyed-out gaps.

#### 2. Architecture: Schema $\to$ Schema $\to$ LLM Pipeline
- **Strict JD Parser (`app.services.jd_parser`):**  
  Deterministic, high-speed (<1ms) section parser extracting `responsibilities`, `required_skills`, `preferred_skills`, `experience_level`, and `education`.
- **Strict Candidate Schema:**  
  Extracts structured `projects` (names, stacks, summaries), `experience` (roles, companies), and `verified_skills` directly from `public.profiles.raw_json`.
- **Grounded Citation & Anti-Hallucination Contract:**  
  The LLM system prompt enforces that every match verdict must cite real evidence from the candidate profile (exact project names such as *RailMind*, *JanSamadhan*, or work experience at *QMax*) and contrast directly with JD requirements. It is strictly forbidden from hallucinating unverified tools.
- **Streamlined UI Modal (`job-modal.tsx`):**  
  - Removed all 3 redundant progress bars.
  - Removed all accordions (zero clicks needed to read the match analysis).
  - Removed level check pills.
  - **Strengths:** Displayed as vibrant green pill badges (`bg-emerald-50 text-emerald-800 border-emerald-200`).
  - **Gaps:** Displayed as subtle greyed-out dashed badges (`bg-zinc-100 text-zinc-500 border-zinc-200`).
  - **Itemized Deductions:** Clean list with transparent point subtractions and reasons.

