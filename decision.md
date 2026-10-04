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

### 2. Experience Classification: Fresher vs. Internship Distinction
A candidate who completes multiple college internships is **not** an experienced mid-level engineer (2+ years). In tech recruiting, classifying a multi-internship fresher as "1.5 years experience" causes them to get filtered out from mid-level roles while missing entry-level/graduate openings.

1. **Role Title Classification:**
   - During parsing of the `Experience` section, each role title is inspected:
     - Titles containing `intern`, `internship`, `trainee`, `apprentice`, or `fellow` are tracked under `internship_months`.
     - Only roles without intern keywords are counted toward `full_time_experience_years`.
2. **Seniority Classification for Matching:**
   - **Fresher / Entry-Level (0–1 yr):** Any candidate where `full_time_experience_years < 1.0`—**regardless of how many internships they completed**.
   - **Junior / Mid / Senior (1+ yrs):** Determined strictly by `full_time_experience_years`.
3. **Role of Internships in the Scoring Engine:**
   - Internships are **never discarded**. They serve as **practical proof, skill validation, and project quality signals** in the hybrid scoring engine (boosting match score for entry-level jobs over candidates with zero practical experience), but they do not artificially inflate seniority levels.

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

## Next Steps
- **Step 4:** Funnel & Deterministic Scoring Math (Hard filters, exact mathematical formulas, boost weights, ranking pipeline).
- **Step 5:** "Why It Matches" LLM Explanation Contract.
- **Step 6:** Trigger Mechanics, Async Pipeline & UI Notification.


