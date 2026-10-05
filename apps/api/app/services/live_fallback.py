"""Live Fallback Aggregator Service (Adzuna & Jooble).

Triggered only when the catalog returns fewer than 10 candidate rows for a user.
Queries Adzuna (India) and Jooble (India & US) in parallel, normalizes results,
tags skills deterministically from the FULL description, embeds them in one batch,
and upserts them into public.jobs for caching. No LLM calls happen here.

Blocking work (embedding model, psycopg2) runs in a worker thread so the event loop
(status polling, other requests) is never stalled.
"""
import asyncio
import os
from typing import List, Dict, Any

import httpx
from dotenv import load_dotenv
from psycopg2.extras import execute_values

from app.services.catalog_normalizer import (
    normalize_company,
    normalize_title,
    is_senior_role,
    extract_skills,
    extract_required_years,
    clean_html_text,
)
from app.services.embedding_service import generate_embeddings_batch

load_dotenv()

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
JOOBLE_KEY_IN = os.getenv("JOOBLE_API_KEY_IN")
JOOBLE_KEY_US = os.getenv("JOOBLE_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

DESCRIPTION_LIMIT = 1500


def _normalize_live_job(job_id: str, title: str, company: str, location: str, region: str,
                        raw_description: str, source_url: Any, date_posted: Any) -> Dict[str, Any]:
    """Skills are extracted from the FULL cleaned text; only the stored description is truncated."""
    full_text = clean_html_text(raw_description)
    return {
        "id": job_id,
        "title": title,
        "company": company,
        "normalized_company": normalize_company(company),
        "normalized_title": normalize_title(title),
        "location": location,
        "region": region,
        "category": "Engineering",
        "description": full_text[:DESCRIPTION_LIMIT],
        "source_url": source_url,
        "date_posted": date_posted,
        # Parsed from the full text so the fresher filter can drop "5+ years" roles from live results too
        "required_years": extract_required_years(full_text),
        "skills": extract_skills(f"{title} {full_text}"),
    }


async def fetch_adzuna_india(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Fetches live engineering jobs from Adzuna India API."""
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []

    url = "https://api.adzuna.com/v1/api/jobs/in/search/1"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": limit,
        "what": query,
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return []
            raw_jobs = r.json().get("results", [])

            normalized = []
            for j in raw_jobs:
                title = j.get("title", "")
                if is_senior_role(title):
                    continue
                normalized.append(_normalize_live_job(
                    job_id=f"adzuna:{j.get('id')}",
                    title=title,
                    company=j.get("company", {}).get("display_name", "Unknown"),
                    location=j.get("location", {}).get("display_name", "India"),
                    region="india",
                    raw_description=j.get("description", ""),
                    source_url=j.get("redirect_url"),
                    date_posted=j.get("created"),
                ))
            return normalized
    except Exception as e:
        print(f"[Live Fallback] Adzuna query failed: {e}")
        return []


async def fetch_jooble(query: str, region: str = "india", limit: int = 10) -> List[Dict[str, Any]]:
    """Fetches live engineering jobs from Jooble API."""
    api_key = JOOBLE_KEY_IN if region == "india" else JOOBLE_KEY_US
    if not api_key:
        return []

    url = f"https://jooble.org/api/{api_key}"
    payload = {
        "keywords": query,
        "location": "India" if region == "india" else "United States",
        "page": 1,
        "result_on_page": limit,
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                return []
            raw_jobs = r.json().get("jobs", [])

            normalized = []
            for j in raw_jobs:
                title = j.get("title", "")
                if is_senior_role(title):
                    continue
                normalized.append(_normalize_live_job(
                    job_id=f"jooble:{j.get('id')}",
                    title=title,
                    company=j.get("company", "Unknown"),
                    location=j.get("location", region),
                    region=region,
                    raw_description=j.get("snippet", ""),
                    source_url=j.get("link"),
                    date_posted=j.get("updated"),
                ))
            return normalized
    except Exception as e:
        print(f"[Live Fallback] Jooble query failed: {e}")
        return []


def _embed_and_persist(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Blocking: batch-embeds jobs and upserts them in one statement. Run via asyncio.to_thread."""
    from app.core.db import get_db

    texts = [f"{j['title']}. {j['description'][:600]}" for j in jobs]
    embeddings = generate_embeddings_batch(texts)

    rows = []
    for j, emb in zip(jobs, embeddings):
        j["embedding"] = emb
        j["similarity"] = 0.65  # placeholder until exact cosine evaluated
        rows.append((
            j["id"], j["title"], j["company"], j["normalized_company"], j["normalized_title"],
            j["location"], j["region"], j["category"], j["description"], j["source_url"],
            j["required_years"], j["skills"], str(emb),
        ))

    with get_db() as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO public.jobs (
                    id, title, company, normalized_company, normalized_title,
                    location, region, category, description, source_url,
                    date_posted, last_seen_at, is_active, required_years, skills, embedding
                ) VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    last_seen_at = now(),
                    is_active = true,
                    skills = CASE
                        WHEN COALESCE(cardinality(EXCLUDED.skills), 0) > COALESCE(cardinality(public.jobs.skills), 0)
                        THEN EXCLUDED.skills ELSE public.jobs.skills END;
                """,
                rows,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(), true, %s, %s::text[], %s::vector)",
            )
        conn.commit()
    return jobs


async def execute_live_fallback_search(
    role_query: str,
    region: str = "india",
) -> List[Dict[str, Any]]:
    """Runs the live search (sources in parallel), embeds, and persists to Supabase."""
    fetches = []
    if region in ("india", "all"):
        fetches.append(fetch_adzuna_india(role_query, limit=10))
    if region in ("india", "us", "all"):
        fetches.append(fetch_jooble(role_query, region="india" if region == "india" else "us", limit=10))

    results = await asyncio.gather(*fetches, return_exceptions=True)

    jobs: List[Dict[str, Any]] = []
    seen = set()
    for res in results:
        if isinstance(res, Exception):
            print(f"[Live Fallback] source failed: {res}")
            continue
        for j in res:
            if j["id"] not in seen:
                seen.add(j["id"])
                jobs.append(j)

    if not jobs or not DATABASE_URL:
        return []

    return await asyncio.to_thread(_embed_and_persist, jobs)
