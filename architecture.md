# Technical Architecture: Job Matcher

> Describes the system as it runs today. Numbers marked "measured" come from runs on 2026-10-05 (development machine in
> India, Supabase project, warm connections). For setup and day-to-day usage see [README.md](README.md).

**Pipeline in one line:** upload, validate, parse, embed, SQL vector retrieval with seniority filters, deterministic
scoring, one LLM call that explains the best jobs, deterministic blending, atomic save, read-only dashboard.

## Table of Contents
1. [System overview](#1-system-overview)
2. [Catalog ingestion](#2-catalog-ingestion)
3. [Upload validation](#3-upload-validation)
4. [Resume parsing](#4-resume-parsing)
5. [Job description parsing](#5-job-description-parsing)
6. [Stage 1: SQL retrieval and filters](#6-stage-1-sql-retrieval-and-filters)
7. [Stage 2: deterministic scoring](#7-stage-2-deterministic-scoring)
8. [Candidate pool and live fallback](#8-candidate-pool-and-live-fallback)
9. [Stage 3: LLM explanation](#9-stage-3-llm-explanation)
10. [Groq gateway](#10-groq-gateway)
11. [Worker, retries and progress tracking](#11-worker-retries-and-progress-tracking)
12. [Upload and match lifecycle](#12-upload-and-match-lifecycle)
13. [Database schema](#13-database-schema)
14. [Frontend](#14-frontend)
15. [Security](#15-security)
16. [Performance and capacity](#16-performance-and-capacity)
17. [Known limitations](#17-known-limitations)

---

## 1. System overview

Two decoupled loops:

- **Catalog loop (scheduled):** a GitHub Actions job crawls ATS boards every 12 hours, normalizes postings, embeds new
  ones and upserts them into Supabase.
- **Candidate loop (interactive):** upload, parse, embed, match, explain, display.

```
                         +------------------------------------------------------+
                         |  Browser: Next.js 16 app (React 19, Tailwind v4)       |
                         |  /  sign in/up   /dashboard   /resume                  |
                         +--------------------------+---------------------------+
                                                    | fetch /api/backend/*
                                                    v
                         +------------------------------------------------------+
                         |  Next.js route handler (proxy)                         |
                         |  reads the Supabase session, adds Authorization: Bearer|
                         +--------------------------+---------------------------+
                                                    | HTTP
                                                    v
+---------------------------------------------------------------------------------------------+
|  FastAPI process (single process; Python 3.11)                                               |
|                                                                                             |
|  routes (main.py)        services                                   in-memory state         |
|  - POST /resumes/upload  - document_validator, resume_parser       - TaskTracker            |
|  - GET  /matches         - embedding_service (FastEmbed, local)    - MatchingWorker queue   |
|  - GET  /matches/status  - matching_engine (funnel, math)            (semaphore 2, dedupe,  |
|  - GET/DELETE /resumes/* - llm_reranker -> groq_gateway               retry timers)         |
|                          - live_fallback (Adzuna, Jooble)                                   |
+-------+-------------------------------+---------------------------------+-------------------+
        | psycopg2 pool (DATABASE_URL)  | Storage REST (service role)      | HTTPS, JSON mode
        v                               v                                  v
+--------------------------+   +-----------------------------+   +--------------------------------+
| Supabase Postgres 15     |   | Supabase Storage            |   | Groq: openai/gpt-oss-20b       |
| pgvector 0.8 (HNSW)      |   | private bucket "resumes"    |   | key pool (k1, k2)              |
| jobs, profiles, matches, |   +-----------------------------+   +--------------------------------+
| resumes, llm_evaluations |
+------------+-------------+
             ^
             | upserts (every 12 h)
+------------+-----------------------------------------------+
| GitHub Actions: scripts/crawler/crawl_and_sync.py            |
| 530 boards (Greenhouse 362, Ashby 98, Lever 70)              |
+--------------------------------------------------------------+
```

Process model: one Uvicorn worker. The queue, the in-flight set, retry timers and the progress tracker live in memory
(Section 17). Heavy or blocking work (PDF parsing, embedding, psycopg2 calls, file validation) runs through
`asyncio.to_thread` so the event loop stays free for status polling.

On startup the lifespan hook starts the worker and a background warm-up that opens the database pool, builds the Groq
HTTP clients (SSL context creation costs about 0.65 s) and loads the embedding model, so the first user request does not
pay for them.

---

## 2. Catalog ingestion

`scripts/crawler/crawl_and_sync.py`, scheduled by `.github/workflows/crawler.yml` (cron `0 */12 * * *` and manual
dispatch, 20-minute timeout, only `DATABASE_URL` as a secret).

```
scripts/seed/seed.json (530 boards)
        |  parallel, rate-limited httpx
        v
Greenhouse  boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Lever       api.lever.co/v0/postings/{slug}?mode=json
Ashby       api.ashbyhq.com/posting-api/job-board/{slug}
        |
        v  normalize
  - drop senior titles (staff, principal, director, vp, vice president, head of, lead, architect, fellow)
  - keep engineering titles only (ENG_TITLE_RE)
  - region by keyword, in this order: india -> remote -> us  (anything else is dropped)
  - id = "{ats}:{slug}:{external id}"      (stable, de-duplicates re-crawls)
  - description = HTML-stripped, whitespace-collapsed, truncated to 1,500 chars for storage
  - skills and required_years are extracted from the FULL cleaned text, before truncation
        |
        v
  existing ids  -> UPDATE last_seen_at = now(), is_active = true
  new ids       -> embed "{title}. {first 600 chars of description}" with FastEmbed (batch 64) and INSERT
        |
        v  housekeeping
  - jobs not seen for 14 days -> is_active = false
  - if more than 15,000 active -> delete the least recently seen rows
```

Current catalog (measured): 9,618 active jobs: US 7,060, India 1,701, remote 857. Sources: Greenhouse 6,516, Ashby 2,041,
Lever 955, Jooble 80, Adzuna 26 (the last two arrive through the live fallback).

**Skills taxonomy** (`catalog_normalizer.py`): 118 canonical skills with 274 aliases, matched with word-boundary-aware
regexes. Candidate skills and job skills use the same vocabulary, which is what keeps the coverage maths meaningful.
`canonicalize_skill()` maps free-form text (for example LLM output) back onto it.

**Years of experience:** the lowest "N years" / "N-M years" figure up to 15 found in the text. About 94% of the catalog
(88% of India and remote jobs) states none, which is why seniority is also filtered by title.

---

## 3. Upload validation

`document_validator.validate_document` runs five layers in order and raises a typed error on the first failure:

```
1. Size          non-empty and at most 5 MB
2. Filename      no path traversal; no executable/script extension anywhere in the name
                 (exe, bat, sh, ps1, js, py, php, jar, dll ...); only .pdf and .docx allowed
3. Magic bytes   PDF must start with %PDF-, DOCX with the ZIP signature PK\x03\x04
4. DOCX structure  at most 200 archive entries; at most 25 MB uncompressed; no VBA/macros;
                 must contain word/document.xml (a generic ZIP is rejected)
5. Content       text extraction must yield at least 50 readable alphanumeric characters
                 (scanned/image-only documents fail here)
```

The stored file name is a random UUID plus the extension, never the uploaded name. Validation runs in a worker thread.

---

## 4. Resume parsing

`resume_parser.parse_resume` is deterministic (no LLM):

```
PDF:  pdfplumber lines with font size and bold flags      DOCX: python-docx paragraphs
        |
        v  heading detection (size, boldness, known heading names; aliases such as "internships" -> experience)
   sections: skills, experience, projects, education, ...  +  a markdown rendering of the document
        |
        +-- skills          shared taxonomy applied to the full text
        +-- headline        the line under the candidate's name (at most 60 chars, no email/link/phone markers),
        |                   else the first sentence of a summary section (at most 90 chars)
        +-- preferred_roles headline split on "|" and "/"
        +-- tenure          date ranges found in the experience section
```

**Fresher-first rule:** a dated experience range counts as internship/project time unless the surrounding lines
explicitly say full-time, FTE or permanent without intern/contract words. Overlapping ranges are merged. Then:

```
full_time_experience_years = merged full-time months / 12
internship_months          = merged internship months
is_fresher                 = full_time_experience_years < 1.0
```

`profile_enricher` (one small LLM call) runs only if the parser produced no headline or no roles, and it is skipped when
the stored profile already holds an LLM-derived result for identical resume text (`markdown_hash`).

**Candidate embedding payload:** `"Role: {headline}. Skills: {skills}. Experience: {Fresher / Entry-level [with N months
internship experience] | N years full-time}."` embedded with `all-MiniLM-L6-v2`. The SHA-256 of that payload is the
profile `content_hash`; it also keys the evaluation cache.

---

## 5. Job description parsing

`jd_parser.parse_job_description` turns a stored description into `responsibilities`, `required_skills`,
`preferred_skills`, `experience_level` and `education`. It runs for the 12 to 18 jobs sent to the LLM, in about a millisecond each.

Stored descriptions are whitespace-collapsed, so structure has to be recovered:

```
- headings that end in a colon ("Responsibilities:", "Skills and qualifications:") are isolated onto their own line
- a sentence that starts with a heading word followed by a capital ("Responsibilities Design, ...") is split from it
- split points are newlines, bullet glyphs, spaced dashes " - " and sentence ends;
  hyphens inside words ("hands-on", "end-to-end") are never split points
- only lines of 80 characters or fewer can be headings
- skills: all tagged skills minus those that appear only under a preferred/nice-to-have heading
```

In the reranker, a posting whose only listed skills sit under a "Preferred" heading treats them as required. A posting
with no tagged skills at all is sent with `skills_unknown: true`.

---

## 6. Stage 1: SQL retrieval and filters

`match_jobs(query_embedding, match_threshold, match_count, filter_region, filter_max_years, is_fresher_candidate)` is a
PL/pgSQL function. The funnel calls it with threshold 0.20 and `match_count` 100.

```
PERFORM set_config('hnsw.ef_search', '150', true)               wider graph exploration per query

WHERE is_active AND embedding IS NOT NULL
  AND cosine similarity >= threshold
  AND NOT title ~* '\y(director|vp|vice president|head of)\y'       everyone
  AND (NOT is_fresher OR NOT title ~* '\y(senior|sr\.?|lead|architect|manager|mgr|staff|principal)\y')
  AND region rule      'india' -> india + remote | 'us' -> us + remote | 'remote' -> remote | 'all' | exact match
  AND experience rule  required_years IS NULL
                       OR (fresher AND required_years <= 1)
                       OR (experienced AND required_years <= filter_max_years + 1)
ORDER BY embedding <=> query_embedding  LIMIT match_count
```

The seniority and experience rules live in SQL on purpose: application code cannot forget to apply them. The index is
HNSW with cosine ops and pgvector's default build parameters (`m=16`, `ef_construction=64`).

---

## 7. Stage 2: deterministic scoring

`matching_engine.score_job` scores each of the up to 100 rows (about 2 ms in total):

```
S_norm  = clamp((cosine - 0.30) / (0.75 - 0.30), 0, 1)
C_skill = |candidate ∩ job skills| / max(|job skills|, 3)            Bayesian floor: a 1-skill posting cannot reach 100%
B_title = 0.05 if any role token (frontend, backend, ai, ml, devops, ...) appears in both the candidate's
          roles/headline and the job title, else 0

standard track (job has skills):   Base = 0.40*S_norm + 0.60*C_skill + B_title
                                   D = 1.00 (C >= 0.50) | 0.85 (C >= 0.25) | 0.60 (C > 0) | 0.35 (C = 0 on a multi-skill job)
                                   Score = round(clamp(Base * D * 100, 0, 100))
dual track (job has no skills):    Score = round(min(65, 0.70*S_norm + B_title)*100)
```

The reality dampener stops high semantic similarity from hiding a total tooling mismatch. The dual track stops terse
postings from outranking well-described ones.

---

## 8. Candidate pool and live fallback

After scoring, rows are sorted by score, then date, then id, and a candidate pool of up to 20 is built:

- at most **2 jobs per company** (by normalized company name);
- at most **one posting per (company, normalized title)**, which removes duplicate aggregator copies.

**Live fallback** (`live_fallback.py`) runs only when `match_jobs` returned **fewer than 10 rows** and the profile has
preferred roles. Adzuna (India) and Jooble run in parallel, results are normalized with the same skill and years
extraction as the crawler, embedded in one batch, and upserted into `public.jobs` (skills are only replaced when the new
list is longer). Embedding and psycopg2 work run in a worker thread. The fallback uses no LLM.

---

## 9. Stage 3: LLM explanation

`llm_reranker.rerank_finalists_with_llm` receives the ordered pool and a target of 10.

```
pool (best math score first, up to 20)
   |
   |-- cache lookup: llm_evaluations rows for (user_id, resume content_hash, job ids)
   |       a row is reused only if its job_sig (hash of title + skills) still matches the job
   |
   |-- call 1: the first 12 jobs that are not cached           (target 10 + 2 spare)
   |-- if fewer than 10 jobs have an explanation:
   |       call 2 (top-up): the next-ranked uncached jobs, at most min(6, missing + 1)
   |-- at most 4 Groq calls per run in total
   |
   |-- new valid evaluations are written back to the cache
   |
   '-- blend, sort, keep the best 10 explained jobs
```

**Prompt.** One static system prompt (rules, rubric, output schema) and one compact JSON user message (no indentation).
Jobs are keyed `"1"` to `"N"` instead of by their long ids, so the model cannot mangle an id. Each job carries title,
company, level, up to 3 duties of at most 140 characters, `match` and `gaps` (required skills the candidate has or lacks,
pre-computed in Python), preferred skills, and `skills_unknown` when applicable. The candidate block lists headline,
years, `is_fresher`, all verified skills (deduplicated), up to 5 projects and up to 3 experience entries.

System rules: skills in `candidate.skills` are ground truth and must never be called missing; gaps and deductions may
only use that job's pre-computed gaps; every verdict must cite a candidate project or experience; verdicts are at most 25
words in the second person; blank-skill jobs get no deductions.

**Request parameters.** `temperature=0`, `seed=42`, JSON mode, `max_tokens = 350 + 170 * jobs`,
`reasoning_effort=low`, `include_reasoning=false` (both dropped automatically if the model rejects them).

**Validation.** An evaluation counts only if it has a verdict of at least 8 characters and three integer sub-scores in
0 to 100. Invalid items are treated as missing.

**Blending (Python only).**

```
LLM   = clamp(0.50*capability + 0.30*tooling + 0.20*seniority - min(15, valid deductions), 0, 100)
Final = round(0.30*Score_math + 0.70*LLM);  jobs with no tagged skills are capped at 68
```

A deduction is ignored if the candidate has that skill or the job does not list it. Strengths are intersected with the
candidate's skills, gaps are filtered against them, and any verdict phrase like "lacks X" for a skill the candidate has is
rewritten.

**Outcomes.**

| Situation | Result |
|---|---|
| 10 explained | saved and shown |
| Output truncated or invalid JSON | the batch is split in halves (depth at most 2) and retried, never another model |
| Groq unavailable (rate limit, outage) | explained jobs so far are kept; unexplained candidates are saved **hidden** (`score_breakdown.llm_pending`); `retry_after` is returned |
| No Groq key configured | funnel reports an error |

A job without an explanation is never returned by `GET /matches`.

---

## 10. Groq gateway

`groq_gateway.py` is the only code that talks to Groq. It is also used by profile enrichment and the offline backfill.

```
chat_json(messages, max_tokens, purpose, max_wait)
   |
   v  estimate = chars/3 + 40 + max_tokens
 pick the key that is ready soonest (ties: most spare budget)       keys: k1 = GROQ_API_KEY, k2 = GROQ_API_KEY_FALLBACK
   |  per key: sliding 60 s windows for requests (RPM 25) and estimated tokens (TPM 6500),
   |  cooldown timestamp, x-ratelimit-remaining/reset headers
   |  reserve capacity, wait if needed (> max_wait -> LLMUnavailable)
   v
 POST (timeout 20 s, at most 2 requests in flight)
   |
   +-- 200  -> finish_reason "length" or invalid JSON -> LLMTruncated ; else parsed result
   +-- 429  -> cooldown = Retry-After; if the error names an organization, cool down every key of that org
   |           retry once on the other key, else LLMUnavailable(retry_after)
   +-- 400  -> reasoning params rejected: drop them and retry ; json_validate_failed -> LLMTruncated ; else LLMBadResponse
   +-- 413  -> LLMTruncated
   +-- 401/403 -> key disabled
   +-- 5xx / timeout -> short cooldown, retry once
```

Every attempt logs purpose, key label, status, latency, tokens and remaining-token headers; the key itself is never
logged. Rate limits are per organization and per model, so two keys help only if they belong to different
organizations; the gateway logs a warning when it detects two keys sharing one.

---

## 11. Worker, retries and progress tracking

`core/worker.py`:

```
enqueue(user_id, region, limit, attempt)
   |  attempt 0 (a fresh request) cancels any scheduled retry for that user
   |  user already queued or running -> ignored (in-flight set)
   v
asyncio.Queue -> Semaphore(2) -> execute_matching_funnel
   |
   '-- result.retry_after set?  attempt < 3 -> schedule a delayed re-run (delay = retry_after clamped to 5 s..1 h, plus jitter)
                                attempt = 3 -> tracker "failed": "AI analysis is temporarily unavailable..."
```

A retry re-runs the whole funnel, but the evaluation cache means only jobs that were never explained reach Groq.
The semaphore bounds concurrent funnels; Groq pressure is controlled by the gateway, not by the semaphore.

`core/task_tracker.py` keeps, per user: `status` (idle, processing, completed, failed), `progress` 0 to 100, `step_label`,
`error`, `analysis_pending`, `retry_in`, `updated_at`. Funnel milestones: 10 validating, 25 parsing, 50 enqueued,
55 vector search, 70 scoring, 82 LLM, 95 saving, 100 done. A finished run with missing explanations is reported as
`completed` with `analysis_pending: true`, so the upload dialog can hand over to the dashboard, which keeps an "analysis
in progress" state until it clears.

---

## 12. Upload and match lifecycle

`POST /resumes/upload` overlaps independent work:

```
read file -> validate (thread)
   |
   +-- start: storage upload (network, about 1.2 s)          \
   +-- start: fetch existing profile (thread)                  } concurrent
   +-- parse resume (thread)                                  /
   |
   v  enrichment only if the parser found no headline/roles and the stored result is not reusable
   embed payload (thread; reuse the stored vector if the content hash is unchanged)
   save profile (headline, skills, vector, content_hash, markdown_hash, ...)
   |
   +-- identical content AND 10 saved matches  -> bypass: 0 tokens
   +-- otherwise: if the content changed, clear this user's matches and cached evaluations immediately
   |             then enqueue the funnel (it only needs the profile, so it runs while the file is still uploading)
   |
   v  await storage upload -> save the resume record -> delete the previous file in the background -> respond
```

If the storage upload or the record save fails after the funnel was enqueued, the tracker is marked failed and the error
is returned.

`GET /matches` is read-only: it reads up to 10 explained rows, applies the region view (a miss returns an empty list,
never a re-run) and reports the state. If there are no saved matches, no run is active or scheduled, the last run finished more
than 60 seconds ago (or none has run in this process), and the profile has skills and an embedding, it enqueues exactly
one background run and returns `status: "processing"`.

`DELETE /resumes/active` cancels the user's scheduled retry, deletes resume, matches, profile and cached evaluations in
the database, deletes the stored file, and clears the tracker.

---

## 13. Database schema

```
auth.users (Supabase)
   |1                |1                  |1
   |                 |                   |
   v N               v 1                 v N
public.resumes    public.profiles      public.llm_evaluations
 id uuid PK        user_id uuid PK      user_id uuid  FK  \
 user_id FK        headline text        content_hash text   > PK (user_id, content_hash, job_id)
 filename          skills text[]        job_id text         /
 storage_path      experience_years     job_sig text
 file_size         preferred_roles[]    evaluation jsonb
 mime_type         embedding vector(384) created_at
 raw_text          content_hash text
 is_active         raw_json jsonb (sections, markdown, markdown_hash, enriched_by_llm, is_fresher, ...)
 created_at        updated_at
 updated_at

auth.users 1 --- N public.matches ------ N:1 --- public.jobs
                   id uuid PK                      id text PK  ("greenhouse:slug:id", "adzuna:id", ...)
                   user_id FK                      title, company, normalized_company, normalized_title
                   job_id FK -> jobs.id            location, region (india | us | remote)
                   match_score int                 description (<= 1,500 chars), source_url, date_posted
                   matched_skills text[]           required_years int, skills text[]
                   missing_skills text[]           embedding vector(384), is_active, last_seen_at
                   explanation text
                   score_breakdown jsonb  (llm_pending: true marks hidden rows)
                   created_at
                   UNIQUE (user_id, job_id)
```

`score_breakdown` holds `math_score`, `llm_score`, `verdict`, `strengths`, `gaps`, `deductions`, the three sub-scores and
`weights`.

| Table | Index | Purpose |
|---|---|---|
| jobs | HNSW `embedding vector_cosine_ops` (default `m=16`, `ef_construction=64`) | nearest-neighbor retrieval |
| jobs | btree `region`, `is_active`, `last_seen_at` | filters and housekeeping |
| jobs | btree `(normalized_company, normalized_title, region)` | de-duplication lookups |
| matches | btree `(user_id, match_score DESC)`; unique `(user_id, job_id)` | dashboard read and one row per pair |
| resumes | btree `user_id`; partial unique `(user_id) WHERE is_active` | one active resume per user |
| llm_evaluations | PK `(user_id, content_hash, job_id)`; btree `user_id` | cache lookup and purge |

DDL: `scripts/migrate.py` (all tables except `llm_evaluations`, indexes, policies, `match_jobs`) and
`apps/api/sql/llm_evaluations.sql`.

---

## 14. Frontend

Next.js 16 App Router, client components for the interactive pages, Tailwind v4.

| Route | Purpose |
|---|---|
| `/` | Email and password sign in or sign up (Supabase). Signed-in users are redirected to `/dashboard`. |
| `/dashboard` | Matches feed, processing state, upload dialog, job modal |
| `/resume` | Active resume: download via signed URL, replace, delete (with confirmation) |
| `/upload` | Redirects to `/dashboard` |
| `/api/backend/[...path]` | Proxy to FastAPI for GET, POST, PUT, PATCH and DELETE; attaches the session access token |

`middleware.ts` refreshes the session and redirects unauthenticated requests to `/`.

**Dashboard states** (driven by `GET /matches` and `GET /matches/status`):

```
no resume                       -> "No active resume found" + upload button
loading                         -> 3 skeleton cards
processing, no matches yet      -> "AI analysis in progress" panel with the live step label
matches + analysis pending      -> cards plus a slim "Finishing AI analysis for more roles..." note
failed, no matches              -> message from the server + "Try again"
ready                           -> up to 10 cards
```

While analysis is pending the dashboard polls `/matches/status` with backoff (3 s growing to 10 s, or slowly when a retry
is scheduled), skips polling while the tab is hidden, stops after 10 minutes, and refetches matches once when the run
finishes. The upload dialog polls every 500 ms for up to 48 s and closes 250 ms after completion. `JobCard` is memoized and
the select handler is stable.

**Cards and modal.** A match is an "Exact Match" when the score is at least 75 and at least 3 matched skills; otherwise
"Broader Fit". The modal shows the AI verdict (hidden if empty), strengths, gaps, itemized deductions and the job
description, with an apply link.

---

## 15. Security

- **Authentication.** The API validates the Supabase JWT on every route except `/health`: ES256 or RS256 through the
  project's JWKS endpoint, HS256 through `SUPABASE_JWT_SECRET`; audience `authenticated`, 60 s leeway.
- **Authorization.** The API connects to Postgres with `DATABASE_URL` as the database owner (RLS does not apply to it) and
  scopes every query by the verified `user_id`. RLS is enabled everywhere as defense in depth: `resumes`, `profiles` and
  `matches` allow only `auth.uid() = user_id`; `jobs` is readable by authenticated users; `llm_evaluations` has RLS with
  no policies, so clients cannot read it.
- **Storage.** Private bucket `resumes`, object path `{user_id}/{random-uuid}.{ext}`, signed download URLs valid 1 hour.
  The service-role key exists only on the backend.
- **CORS.** Allowed origins come from `CORS_ORIGINS` (default: `http://localhost:3000`, `http://127.0.0.1:3000`); methods GET, POST,
  DELETE, OPTIONS; headers `Authorization` and `Content-Type`; no credentials. Browsers reach the API only through the Next.js
  proxy, so no direct cross-origin access is needed in normal use.
- **Configuration safety.** `SUPABASE_URL` has no default; auth and storage refuse to start without it.
- **Input.** Five-layer validation (Section 3); filenames are never trusted; the LLM prompt never contains the user's raw
  file name.
- **Secrets.** `.env` files are git-ignored; `.env.example` documents every variable. Groq keys are never logged.

---

## 16. Performance and capacity

Measured on 2026-10-05 (see the note at the top):

| Operation | Time | Groq tokens |
|---|---|---|
| `GET /matches` (10 jobs, about 22 KB) | 100 to 250 ms | 0 |
| `POST /resumes/upload` request | about 2.4 to 2.6 s | 0 |
| `match_jobs` (warm) | 0.17 to 0.45 s | 0 |
| Scoring 100 jobs | about 2 ms | 0 |
| Groq rerank call (12 jobs) | about 1.9 to 2.3 s | 3.0 to 3.3k |
| Funnel from cache | about 0.7 to 1 s | 0 |
| Changed resume, upload to results | about 3 s | one call |
| Identical re-upload with saved matches | no funnel | 0 |

Event-loop behavior: with the gateway pre-built at startup, no step of the funnel blocks the loop for more than 50 ms.

Capacity (Groq free plan, `gpt-oss-20b`, per organization): 30 requests/min, 1K requests/day, 8K tokens/min, 200K
tokens/day. At about 3.2k tokens per fresh run that is roughly 60 fresh runs per organization per day; cached runs are free.
The 8K tokens/min limit means a second fresh run inside the same minute waits or is deferred (the user sees "analysis in
progress" and the worker retries).

---

## 17. Known limitations

- **In-memory state.** Queue, in-flight set, retry timers and the progress tracker are per process. Use one Uvicorn worker;
  scheduled retries are lost on restart (the next `GET /matches` re-enqueues when nothing is saved).
- **Shared Groq budget.** Keys from the same organization share limits. No second model is configured, although limits are per model.
- **Truncated, whitespace-collapsed descriptions** (1,500 characters) limit skill extraction and JD structure; about a
  quarter of the catalog has no tagged skills (a one-time LLM backfill script exists for India and remote jobs).
- **No LICENSE file** and no deployment configuration beyond the crawler workflow.
