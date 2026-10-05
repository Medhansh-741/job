"""Live Fallback Aggregator Service (Adzuna & Jooble).

Triggered when catalog matches with hybrid score >= 60% are scarce (< 10).
Queries Adzuna (India) or Jooble (India & US), normalizes results,
generates FastEmbed embeddings, and upserts them into public.jobs for caching.
"""
import os
import re
import httpx
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

from app.services.catalog_normalizer import (
    normalize_company,
    normalize_title,
    is_senior_role,
    extract_skills,
    strip_html_and_truncate,
)
from app.services.embedding_service import generate_embedding

ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
JOOBLE_KEY_IN = os.getenv("JOOBLE_API_KEY_IN")
JOOBLE_KEY_US = os.getenv("JOOBLE_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")


async def fetch_adzuna_india(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Fetches live engineering jobs from Adzuna India API."""
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        return []

    url = f"https://api.adzuna.com/v1/api/jobs/in/search/1"
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
            data = r.json()
            raw_jobs = data.get("results", [])

            normalized = []
            for j in raw_jobs:
                title = j.get("title", "")
                if is_senior_role(title):
                    continue

                company = j.get("company", {}).get("display_name", "Unknown")
                desc = strip_html_and_truncate(j.get("description", ""))
                skills = extract_skills(f"{title} {desc}")
                job_id = f"adzuna:{j.get('id')}"

                normalized.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "normalized_company": normalize_company(company),
                    "normalized_title": normalize_title(title),
                    "location": j.get("location", {}).get("display_name", "India"),
                    "region": "india",
                    "category": "Engineering",
                    "description": desc,
                    "source_url": j.get("redirect_url"),
                    "date_posted": j.get("created"),
                    "required_years": None,
                    "skills": skills,
                })
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
            data = r.json()
            raw_jobs = data.get("jobs", [])

            normalized = []
            for j in raw_jobs:
                title = j.get("title", "")
                if is_senior_role(title):
                    continue

                company = j.get("company", "Unknown")
                desc = strip_html_and_truncate(j.get("snippet", ""))
                skills = extract_skills(f"{title} {desc}")
                job_id = f"jooble:{j.get('id')}"

                normalized.append({
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "normalized_company": normalize_company(company),
                    "normalized_title": normalize_title(title),
                    "location": j.get("location", region),
                    "region": region,
                    "category": "Engineering",
                    "description": desc,
                    "source_url": j.get("link"),
                    "date_posted": j.get("updated"),
                    "required_years": None,
                    "skills": skills,
                })
            return normalized
    except Exception as e:
        print(f"[Live Fallback] Jooble query failed: {e}")
        return []


async def execute_live_fallback_search(
    role_query: str,
    region: str = "india",
) -> List[Dict[str, Any]]:
    """Runs live search, generates embeddings, and persists to Supabase."""
    jobs: List[Dict[str, Any]] = []

    if region in ("india", "all"):
        adzuna_jobs = await fetch_adzuna_india(role_query, limit=10)
        jobs.extend(adzuna_jobs)

    if len(jobs) < 10 and region in ("india", "us", "all"):
        target_reg = "india" if region == "india" else "us"
        jooble_jobs = await fetch_jooble(role_query, region=target_reg, limit=10)
        jobs.extend(jooble_jobs)

    if not jobs or not DATABASE_URL:
        return []

    # Generate embeddings and upsert into Supabase
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    persisted_jobs = []

    with conn.cursor() as cur:
        for j in jobs:
            text = f"{j['title']}. {j['description'][:600]}"
            emb = generate_embedding(text)
            j["embedding"] = emb
            j["similarity"] = 0.65  # placeholder until exact cosine evaluated

            cur.execute(
                """
                INSERT INTO public.jobs (
                    id, title, company, normalized_company, normalized_title,
                    location, region, category, description, source_url,
                    date_posted, last_seen_at, is_active, required_years, skills, embedding
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(), true, %s, %s, %s::vector)
                ON CONFLICT (id) DO UPDATE SET
                    last_seen_at = now(),
                    is_active = true;
                """,
                (
                    j["id"], j["title"], j["company"], j["normalized_company"], j["normalized_title"],
                    j["location"], j["region"], j["category"], j["description"], j["source_url"],
                    j["required_years"], j["skills"], str(emb)
                )
            )
            persisted_jobs.append(j)

    conn.close()
    return persisted_jobs
