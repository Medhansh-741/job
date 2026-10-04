# Architecture

**Pipeline:** Resume → Candidate Profile → Job Matching → Ranked Matches → Why It Matches → Apply Link.

Multi-user web app. A user uploads a resume, we extract a structured profile, match it against a shared catalog of jobs (with live API fallback), explain the best matches, and link to the original apply page.

**Budget:** $0 (free tiers and trial credits). **Audience:** small evaluation cohort.

---

## 1. Tech Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js (App Router) + TypeScript + Tailwind, on Vercel |
| Backend API | Python 3.11+ / FastAPI + Uvicorn, on Railway |
| Database + vectors | Supabase Postgres + pgvector |
| Auth | Supabase Auth (email + password), JWT verified by backend |
| File storage | Supabase Storage (private per-user paths) |
| Realtime | Supabase Realtime (pipeline progress to UI) |
| Resume extraction | pdfplumber (PDF) + python-docx (DOCX), local |
| Profile structuring | Groq LLM |
| Embeddings | FastEmbed (all-MiniLM-L6-v2, ONNX, CPU) |
| Job sources (ATS, keyless) | Greenhouse, Lever, Ashby (global companies hiring in India/US/remote), SmartRecruiters (Indian companies, e.g. Swiggy) |
| Job sources (aggregators) | Adzuna and Jooble (India key) as primary for Indian roles; JSearch and Remotive as fallback |
| Scheduled crawler | GitHub Actions cron over a curated seed of ~530 company boards |
| Matching | Deterministic hybrid: semantic similarity + skill overlap + boosts |
| Explanations | Groq LLM, grounded on computed signals only |
| Apply | Direct redirect to original apply URL |

---

## 2. System Diagram

```
LOOP 1 - SCHEDULED CRAWL
GitHub Actions (cron) -> seed company boards (Greenhouse / Lever / Ashby / SmartRecruiters)
   -> normalize + dedupe -> embed (FastEmbed) -> upsert into Supabase `jobs`

LOOP 2 - USER MATCHING
+------------------------------------------------------------+
| Frontend (Next.js / Vercel)                                |
| Login | Upload | Profile | Ranked Matches | Apply          |
+--------------------+---------------------------------------+
                     | HTTPS + Supabase JWT      ^ Realtime progress
                     v                           |
+------------------------------------------------------------+
| Backend (FastAPI / Railway)                                |
| Auth + rate limit + file validation                        |
| 1. Extract text -> Groq -> Profile                         |
| 2. Embed profile                                           |
| 3. Search shared job catalog (pgvector)                    |
|    + live Adzuna / Jooble (India) query per upload,        |
|      new jobs embedded and upserted into the catalog       |
|      too few strong matches? -> JSearch / Remotive         |
|                                 fallback, then upsert      |
| 4. Deterministic scoring + ranking                         |
| 5. Groq explanations for top matches                       |
| 6. Persist matches, notify UI                              |
+--------------------+---------------------------------------+
                     v
+------------------------------------------------------------+
| Supabase: Auth | Postgres + pgvector | Storage | Realtime   |
+------------------------------------------------------------+
                     v
         Apply link -> original ATS / job-board URL
```

---

## 3. Data Entities

- `profiles`: extracted candidate profile (per user).
- `resumes`: file reference + profile embedding (per user).
- `jobs`: shared global catalog with embeddings.
- `matches`: per-user scores, matched/missing skills, explanation.

RLS on user-owned tables; `jobs` is read-only for authenticated users and written only by the backend/crawler via the service role.

---

## 4. Key Decisions

1. Multi-user with Supabase Auth and strict per-user isolation.
2. Backend in Python (FastAPI).
3. Resume text is extracted locally; the LLM only structures it.
4. Job data comes from free sources only; no scraping, no LinkedIn/Indeed direct. ATS boards cover global companies hiring in India/US/remote; Indian product companies are mostly not on Greenhouse/Lever/Ashby, so Adzuna and Jooble (India) are primary for India, plus SmartRecruiters.
5. Ranking is deterministic; the LLM never scores, it only phrases explanations.
6. Hybrid retrieval: shared catalog plus one cheap live Adzuna/Jooble query per upload; JSearch and Remotive only as fallback (small free quotas).
7. Seed list: ~530 companies chosen by data-derived relevance cutoffs (India, fresher and hiring-scale), not by brand.
8. Apply is a redirect only; no auto-apply.
9. Pipeline runs in FastAPI background tasks; progress via Supabase Realtime. No queue or Redis in v1.
10. Monorepo: `apps/web` and `apps/api`; crawler lives in the same repo as a GitHub Actions workflow.

---

## 5. Deployment

| Piece | Host |
|---|---|
| Frontend | Vercel (Hobby) |
| Backend | Railway (always-on; $5 trial credit, so paid or a fallback host after the trial) |
| Data / auth / storage / realtime | Supabase (free) |
| Crawler | GitHub Actions (free minutes) |

**Secrets:** the service-role key lives only in the backend and the crawler, never in the frontend. The frontend gets only the public Supabase URL and anon key.

---

## 6. Deferred to v2

- Queue/worker (RQ/Celery) + Redis.
- Workday adapter (public but POST-based, per-tenant) and other ATS without a standard public API (Darwinbox, Keka, in-house pages).
- Extra caching layers and additional job sources.
