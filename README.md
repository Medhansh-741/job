<div align="center">

# Job Matcher

**Semantic job matching for early-career engineers, with grounded, per-job explanations**

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16.3-black.svg)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.2-61DAFB.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6.svg)](https://www.typescriptlang.org/)
[![Tailwind](https://img.shields.io/badge/Tailwind-v4-38B2AC.svg)](https://tailwindcss.com/)
[![Supabase](https://img.shields.io/badge/Supabase-Postgres%20%2B%20pgvector-3ECF8E.svg)](https://supabase.com/)
[![Groq](https://img.shields.io/badge/Groq-gpt--oss--20b-F05A28.svg)](https://groq.com/)

</div>

---

## What it does

A candidate uploads a PDF or DOCX resume. The system parses it deterministically, embeds it, finds the closest jobs in a
shared catalog (about 9.6k active postings crawled from Greenhouse, Lever and Ashby), scores them with a deterministic
formula, and asks an LLM to **explain the best ones**. The dashboard shows up to **10 matches, every one with an
LLM-written verdict that cites the candidate's own projects or experience**. A job without an explanation is never shown.

Two problems it is built around:

1. **Senior roles leaking into fresher feeds.** Most postings do not state years of experience. A SQL-level title
   knockout inside the `match_jobs` function removes senior, lead, architect, manager, staff and principal roles for
   fresher profiles (and director, VP and head-of roles for everyone), so it cannot be bypassed by application code.
2. **Hallucinated or inflated scores.** Ranking is deterministic math (a Bayesian denominator floor and a non-linear
   dampener). The LLM only explains and adjusts: it never ranks the catalog, and the final blend is computed in Python,
   not by the model.

## How a match is produced

```
 Upload (PDF/DOCX)
   |
   |-- 5-layer validation ------------ size, filename/extension, magic bytes, DOCX structure, readable text
   |-- Deterministic parse ----------- sections, skills, tenure, headline, preferred roles
   |-- FastEmbed (all-MiniLM-L6-v2) -- 384-dim vector, SHA-256 content hash
   |
   v
 Funnel (background worker)
   1. match_jobs()            pgvector HNSW top-100, seniority + region + experience filters in SQL
   2. Hybrid math score       semantic similarity + skill coverage + title boost, reality dampener
   3. Live fallback           only if the catalog returned fewer than 10 rows (Adzuna / Jooble)
   4. Candidate pool          best score first, max 2 jobs per company, one posting per (company, title)
   5. LLM explanation         ONE Groq call for the top 12; one small top-up call if fewer than 10 came back
   6. Blend and persist       30% math + 70% LLM rubric, atomic replace in public.matches
   |
   v
 Dashboard: GET /matches (read-only, ~100-250 ms) -> up to 10 explained jobs
```

Details of every stage are in [architecture.md](architecture.md).

## Behaviors worth knowing

- **Read-only dashboard load.** `GET /matches` only reads saved rows. It never runs the funnel inside the request. If
  the user has no saved matches and nothing is running, it enqueues one background run (deduplicated, with a
  60-second cooldown) and returns `status: "processing"`.
- **Free repeats.** Identical resume content with a full saved set of matches costs 0 Groq tokens. LLM evaluations are
  cached per `(user, resume content hash, job)`, so a re-run only sends jobs that were never explained.
- **Changed resume = instant replace.** Uploading different content clears that user's old matches and cached
  evaluations at once and recomputes (about 3 seconds end to end in measurements, one Groq call).
- **Rate limits never break the page.** All Groq traffic goes through one gateway with a per-key limiter, cooldowns and
  retry-after handling. If the LLM cannot explain enough jobs, the unexplained ones are stored hidden and the worker
  retries them later (up to 3 times); the dashboard shows an "AI analysis in progress" state instead of weak results.
- **Blank-skill postings.** About a quarter of the catalog has no tagged skills. Those jobs use a dual-track score
  (capped at 65 before the LLM, 68 after) and are flagged to the LLM, which infers requirements from the title and duties
  and applies no gap penalties.
- **Fast startup path.** On boot the API pre-opens the DB pool, builds the Groq HTTP clients and loads the embedding
  model so the first user request is not the slow one.

## Repository layout

```
.
├── apps/
│   ├── api/                              FastAPI backend (Python 3.11)
│   │   ├── app/
│   │   │   ├── main.py                   Routes, upload orchestration, lifespan
│   │   │   ├── core/
│   │   │   │   ├── auth.py               Supabase JWT validation (JWKS for ES256/RS256, secret for HS256)
│   │   │   │   ├── db.py                 psycopg2 pool, resume/profile/match queries, LLM-evaluation cache
│   │   │   │   ├── task_tracker.py       In-memory per-user funnel progress (status, progress, analysis_pending)
│   │   │   │   └── worker.py             asyncio queue worker, dedupe, delayed retries, startup warm-up
│   │   │   └── services/
│   │   │       ├── catalog_normalizer.py Company/title normalisation, skills taxonomy (118 skills, 274 aliases), HTML cleaning
│   │   │       ├── document_validator.py 5-layer upload validation
│   │   │       ├── embedding_service.py  FastEmbed model, content hashing, batch embedding
│   │   │       ├── groq_gateway.py       Key pool, rate limiter, cooldowns, error classification
│   │   │       ├── jd_parser.py          Deterministic job-description section parser
│   │   │       ├── live_fallback.py      Adzuna / Jooble live search (no LLM)
│   │   │       ├── llm_reranker.py       Prompt building, cache, top-up, deterministic score blending
│   │   │       ├── matching_engine.py    Funnel orchestration, hybrid math, persistence
│   │   │       ├── profile_enricher.py   LLM headline/role inference (only when the parser finds none)
│   │   │       ├── resume_parser.py      pdfplumber / python-docx parsing, tenure maths
│   │   │       └── storage.py            Supabase private Storage (bucket "resumes")
│   │   ├── sql/llm_evaluations.sql       DDL for the per-user evaluation cache table
│   │   ├── tests/test_core_logic.py      Offline unit tests (no network, no DB writes)
│   │   └── requirements.txt
│   └── web/                              Next.js 16 App Router (React 19, TypeScript, Tailwind v4)
│       └── src/
│           ├── app/
│           │   ├── page.tsx              Sign in / sign up (Supabase email + password)
│           │   ├── dashboard/page.tsx    Matches feed, processing state, status polling
│           │   ├── resume/page.tsx       Active resume: download, replace, delete
│           │   ├── upload/page.tsx       Redirects to /dashboard
│           │   └── api/backend/[...path]/route.ts   Proxy to FastAPI, attaches the Supabase session token
│           ├── components/{auth,dashboard,ui}/      auth card, job card/modal, sidebar, upload modal, primitives
│           ├── lib/supabase/             Browser/server clients and session middleware
│           └── middleware.ts             Route protection
├── scripts/
│   ├── migrate.py                        Tables, indexes, RLS policies, match_jobs()
│   ├── crawler/crawl_and_sync.py         Crawls 530 ATS boards, embeds new jobs, marks stale jobs inactive
│   ├── seed/                             Board lists for the crawler (seed.json) and a one-off seeding pipeline
│   ├── backfill_job_skills.py            Offline skills + required_years re-extraction (dry-run by default)
│   ├── backfill_job_skills_llm.py        One-time batched Groq skills backfill for blank jobs (dry-run by default)
│   ├── e2e_full_path.py                  End-to-end run of the real app for one account (uses real Groq)
│   ├── live_smoke_rerank.py              One real rerank call for one user, optional cache
│   ├── test_matching_engine.py           16-test integration script (needs the database)
│   └── ...                               parser, embedding and upload verification utilities
├── .github/workflows/crawler.yml         Catalog crawl every 12 hours
├── architecture.md                       System architecture
├── decision.md, steps.md                 Historical design log (see note at the end)
└── .env.example                          Environment template
```

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI, Uvicorn, httpx, psycopg2 |
| Web | Next.js 16.3.8, React 19.2.8, TypeScript 5, Tailwind CSS v4, `@supabase/ssr` |
| Auth | Supabase Auth (JWT verified by the API: JWKS for ES256/RS256, shared secret for HS256) |
| Database | Supabase PostgreSQL with `pgvector` 0.8 (HNSW cosine index, default `m=16`, `ef_construction=64`, `ef_search=150` set inside `match_jobs`) |
| Embeddings | FastEmbed running `sentence-transformers/all-MiniLM-L6-v2` locally (384 dimensions) |
| Documents | pdfplumber (PDF), python-docx (DOCX) |
| LLM | Groq `openai/gpt-oss-20b` (JSON mode, `reasoning_effort=low`) through `groq_gateway.py` |
| Job sources | Greenhouse, Lever, Ashby (crawler); Adzuna and Jooble (live fallback) |

## Quickstart

### Prerequisites
Python 3.11, Node.js 20+, a Supabase project with the `vector` extension, and a Groq API key.

### 1. Install

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell   (macOS/Linux: source .venv/bin/activate)
pip install -r apps/api/requirements.txt
cd apps/web && npm install && cd ../..
```

### 2. Configure

```bash
cp .env.example .env                  # backend and scripts (repo root)
```

Create `apps/web/.env.local` with `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` and, if the API is not on
`http://127.0.0.1:8000`, `FASTAPI_BACKEND_URL`. Next.js does not read the repo-root `.env`. See
[Configuration](#configuration) for every variable.

### 3. Create the database objects

```bash
python scripts/migrate.py                         # tables, indexes, RLS, match_jobs()
# cache table: run apps/api/sql/llm_evaluations.sql in the Supabase SQL editor
```

The API works without `llm_evaluations` (caching is simply disabled and a warning is logged once), but repeat runs then
re-pay Groq.

### 4. Populate the job catalog

```bash
python scripts/crawler/crawl_and_sync.py          # crawls the boards in scripts/seed/seed.json and embeds new jobs
```

In production this runs every 12 hours via GitHub Actions (needs the `DATABASE_URL` repository secret).

### 5. Run

```bash
# terminal 1, from the repo root with the venv active
uvicorn app.main:app --app-dir apps/api --reload --port 8000

# terminal 2
cd apps/web && npm run dev
```

API docs: `http://localhost:8000/docs`. App: `http://localhost:3000` (sign up, upload a resume, wait a few seconds).

> Run the API as **one process**. The task tracker and queue worker are in memory; multiple Uvicorn workers would each
> have their own copy (see Known limitations).

## Configuration

| Variable | Used by | Default / notes |
|---|---|---|
| `DATABASE_URL` | API, scripts | Required. Direct Postgres connection string. |
| `SUPABASE_URL` | API | Required, no default. The API refuses to start without it (a silent fallback could point auth and storage at the wrong project). |
| `CORS_ORIGINS` | API | Comma-separated browser origins allowed to call the API directly. Default `http://localhost:3000,http://127.0.0.1:3000`. The web app does not need it: browsers only reach the API through the Next.js proxy. |
| `SUPABASE_SERVICE_ROLE_KEY` | API | Required for Storage upload, delete and signed URLs. Never sent to the browser. |
| `SUPABASE_JWT_SECRET` | API | Only for HS256 tokens. ES256/RS256 tokens are verified through the project's JWKS endpoint. |
| `GROQ_API_KEY` | API | Main key. Without any key, explanations are unavailable and the funnel reports an error. |
| `GROQ_API_KEY_FALLBACK` | API | Optional second key. Only adds capacity if it belongs to a **different Groq organization**. |
| `GROQ_MODEL` | API | `openai/gpt-oss-20b` |
| `GROQ_RPM` / `GROQ_TPM` | API | `25` / `6500` per key (local limiter, kept under the free-tier 30 RPM / 8K TPM). |
| `GROQ_TIMEOUT` | API | `10` seconds per request (a normal rerank call takes about 2 s) |
| `GROQ_REASONING_EFFORT` | API | `low`. Removed automatically if the model rejects it. |
| `GROQ_INCLUDE_REASONING` | API | `false` |
| `GROQ_MAX_INFLIGHT` | API | `2` concurrent Groq requests |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | API | Live fallback (India). Optional. |
| `JOOBLE_API_KEY`, `JOOBLE_API_KEY_IN` | API | Live fallback for US / India. Optional. |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Web | Required, in `apps/web/.env.local`. |
| `FASTAPI_BACKEND_URL` | Web | `http://127.0.0.1:8000` |

The API loads the repo-root `.env` first and `python-dotenv` never overrides variables that are already set. If you keep
a second copy at `apps/api/.env`, keep the two identical.

## API reference

All endpoints except `/health` require `Authorization: Bearer <Supabase access token>`. In the web app the Next.js proxy
(`/api/backend/...`) adds it from the session.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check. |
| `GET` | `/me` | Authenticated user id, email and role. |
| `POST` | `/resumes/upload` | Validate, store, parse, embed and enqueue matching. `multipart/form-data` with `file`. |
| `GET` | `/resumes/active` | Active resume metadata and a signed download URL (valid 1 hour). |
| `DELETE` | `/resumes/active` | Deletes the resume record, stored file, profile, matches and cached evaluations. |
| `GET` | `/profiles/me` | Parsed profile. |
| `GET` | `/matches/status` | Funnel progress for the current user (polled by the UI). |
| `GET` | `/matches?region=india&limit=10` | Saved, explained matches (read-only). `limit` is 1 to 10. |

### `GET /matches/status`

```json
{ "status": "processing", "progress": 82, "step_label": "AI is evaluating your best matches...",
  "error": null, "analysis_pending": false, "retry_in": null, "updated_at": 1759670000.0 }
```

`status` is `idle`, `processing`, `completed` or `failed`. `analysis_pending: true` with `completed` means some
explanations are still being retried in the background and `retry_in` is the delay in seconds.

### `GET /matches`

```json
{
  "matches": [
    {
      "id": "ashby:coram-ai:4689a957-bf88-4eea-9b32-004025bf4544",
      "title": "Backend Engineer", "company": "coram-ai", "location": "Bangalore", "region": "india",
      "description": "...", "source_url": "https://...", "date_posted": "2026-10-04T00:00:00+00:00",
      "required_years": null, "skills": ["aws", "etl", "python"],
      "match_score": 81,
      "matched_skills": ["aws", "etl", "python"], "missing_skills": ["observability"],
      "inferred_skills": [],
      "explanation": "Your AWS and ETL experience supports coram-ai's backend and data needs.",
      "score_breakdown": {
        "math_score": 81, "llm_score": 81, "verdict": "...", "strengths": ["python"], "gaps": ["observability"],
        "deductions": [], "capability_fit": 82, "tooling_fit": 78, "seniority_fit": 80,
        "weights": { "math": 0.3, "llm": 0.7 }
      }
    }
  ],
  "total_evaluated": 10,
  "live_fallback_triggered": false,
  "strong_matches_count": 10,
  "status": "ready",
  "analysis_pending": false,
  "error": null
}
```

`status` is `ready`, `processing` (a run is active or queued) or `failed` (nothing saved and the last run failed).

### `POST /resumes/upload`

```bash
curl -X POST http://localhost:8000/resumes/upload -H "Authorization: Bearer $TOKEN" -F "file=@resume.pdf"
```

Returns `success`, the stored resume (`active`), the parsed `profile` (headline, skills, experience, `is_fresher`,
`preferred_roles`, `content_hash`, `is_cache_hit`) and `characters_extracted`. Matching continues in the background;
poll `/matches/status`.

## Scoring

**Stage 1, SQL (`match_jobs`).** Cosine similarity over the HNSW index, top 100, minimum similarity 0.20. Director, VP and
head-of titles are always excluded. For fresher profiles, senior, sr, lead, architect, manager, staff and principal titles
are excluded. Fresher candidates only see jobs with `required_years` of 1 or less (or unknown). Region `india` includes
`remote`.

**Stage 2, deterministic math.**

```
S_norm   = clamp((cosine - 0.30) / 0.45, 0, 1)
C_skill  = |candidate skills ∩ job skills| / max(|job skills|, 3)          (Bayesian denominator floor)
Base     = 0.40 * S_norm + 0.60 * C_skill + 0.05 (if a role token matches the title)
D_skill  = 1.00 if C >= 0.50 | 0.85 if C >= 0.25 | 0.60 if C > 0 | 0.35 if C = 0   (reality dampener)
Score    = round(clamp(Base * D_skill * 100, 0, 100))
```

A job with no tagged skills uses `0.70 * S_norm + title boost`, capped at 65.

**Stage 3, LLM.** The top 12 candidates go to Groq in one listwise call. The model returns, per job, a verdict
(one or two sentences citing a candidate project or experience), strengths, gaps, at most two deductions and three scores.
Python then computes:

```
LLM    = clamp(0.50 * capability + 0.30 * tooling + 0.20 * seniority - min(15, valid deductions), 0, 100)
Final  = round(0.30 * Score_math + 0.70 * LLM)            (capped at 68 for jobs with no tagged skills)
```

Deductions are ignored for any skill the candidate actually has or the job does not list, and gaps are filtered against
the candidate's verified skills. If fewer than 10 jobs were explained, one top-up call evaluates the next-ranked jobs.
The 10 highest blended scores are saved and shown.

## Groq usage and limits

Groq's free plan for `openai/gpt-oss-20b` allows 30 requests/min, 1K requests/day, 8K tokens/min and **200K tokens/day**,
applied **per organization**. A fresh funnel run costs about 3.0 to 3.3k tokens (one call); cached runs cost 0, so the
free daily budget covers roughly 60 fresh runs per organization.

`groq_gateway.py` enforces this: per-key sliding-window limits (requests and estimated tokens), key selection by
readiness, cooldown on 429 using `Retry-After`, automatic cooldown for every key in the same organization when a 429
names it, one retry on the other key, and a distinction between "unavailable" (retry later), "truncated or invalid JSON"
(retry with a smaller batch) and "bad response". Every attempt is logged with the key label, status, latency and tokens
(never the key). Limits are per model, so a second model on the same key would be a separate daily budget; none is
configured today.

## Operations

- **Catalog crawl:** `.github/workflows/crawler.yml` runs `scripts/crawler/crawl_and_sync.py` every 12 hours. Jobs not seen
  for 14 days are marked inactive, and the active set is capped at 15,000 by deleting the least recently seen rows.
- **Skills and years backfill (no LLM):** `python scripts/backfill_job_skills.py` prints what would change;
  add `--apply` to write. It only adds skills and only fills `required_years` where it is `NULL`.
- **Skills backfill (LLM):** `python scripts/backfill_job_skills_llm.py` prints the call estimate; add `--apply` to run.
  It targets blank India/remote jobs, about 15 per call, and is safe to stop and resume.
- **Evaluation cache:** purged automatically when a resume is replaced with different content or deleted.

## Testing

```bash
# Offline unit tests: gateway, rerank, cache, JD parser, funnel rules (no network, no DB writes), under a second
cd apps/api && python -m unittest discover -s tests -v

# Integration script (16 tests): needs DATABASE_URL, writes test data, and test 9 makes one real Groq call
python scripts/test_matching_engine.py

# End-to-end on a real account and resume. WRITES to that account. Add --fresh to force a real Groq call (~3k tokens).
python scripts/e2e_full_path.py <user_id> <email> resumes/medhansh.pdf [--fresh]

# One real rerank call for one user, nothing written unless --cache is given
python scripts/live_smoke_rerank.py <user_id> [--cache]

# Frontend
cd apps/web && npx tsc --noEmit && npm run lint
```

`npm run lint` currently reports 3 existing errors in `dashboard/page.tsx` (one `any`, two set-state-in-effect rules).

## Measured performance

Measured on 2026-10-05 from a development machine in India against the Supabase project, with warm connections.
Your numbers will vary with region and network.

| Operation | Measured |
|---|---|
| `GET /matches` (10 jobs, about 22 KB) | 100 to 250 ms, 0 Groq calls |
| `POST /resumes/upload` request | about 2.4 to 2.6 s (storage upload dominates) |
| Funnel from cache (identical resume, no matches saved) | about 1 s, 0 Groq calls |
| Funnel with one real Groq call | about 3 s total, Groq call about 2 s, 3.0 to 3.3k tokens |
| Identical re-upload with 10 saved matches | no funnel, 0 Groq calls |

## Security model

- **Database access.** The API connects with `DATABASE_URL` as the database owner, which bypasses Row Level Security, and
  scopes every query by the `user_id` from the verified JWT. RLS is enabled on every table as defense in depth for direct
  client access: `resumes`, `profiles` and `matches` allow only `auth.uid() = user_id`, and `jobs` is readable by
  authenticated users. `llm_evaluations` has RLS enabled with no policies, so clients cannot read it.
- **Storage.** Resumes live in the private `resumes` bucket under `{user_id}/{random-uuid}.{ext}`. Signed download URLs
  last 1 hour. The service-role key is used only by the API.
- **CORS.** Only the origins in `CORS_ORIGINS` (default: local dev) are allowed, with methods GET, POST, DELETE, OPTIONS, the
  `Authorization` and `Content-Type` headers, and no credentials (the API uses Bearer tokens, not cookies).
- **Upload validation.** Maximum 5 MB; only `.pdf` and `.docx`; path traversal and executable double extensions rejected;
  magic bytes must match (`%PDF-` or the ZIP signature); DOCX archives are rejected for more than 200 entries, more than
  25 MB uncompressed, embedded macros, or a missing `word/document.xml`; at least 50 readable alphanumeric characters
  are required. Files are stored under a random name, never the uploaded one.

## Known limitations

- **Single process only.** The queue, in-flight set, retry timers and progress tracker are in memory. Do not run several
  Uvicorn workers, and expect scheduled retries to be lost on restart (the next `GET /matches` re-enqueues if nothing is saved).
- **One Groq budget per organization.** Check your keys really belong to different organizations before relying on two.
- **Stored descriptions are truncated to 1,500 characters and whitespace-collapsed**, which limits skill extraction and
  JD section detection for long postings. About a quarter of the catalog still has no tagged skills.
- **No LICENSE file** is present in the repository yet.
- **Deployment is not configured in this repo** beyond the crawler workflow. Any host that can run one long-lived Python
  process (API) and a Next.js app (web) will work.

## Design log

`decision.md` and `steps.md` are the original step-by-step design log. They predate the Groq gateway, the evaluation
cache and the top-10 / explained-only behavior (for example they describe a top-15 list and a 70B model), so treat
this README and `architecture.md` as the source of truth for current behavior.
