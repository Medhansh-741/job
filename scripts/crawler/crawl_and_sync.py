"""Production Incremental Crawler & Sync Service.

Crawls the 530 curated company boards (Greenhouse, Lever, Ashby), normalizes
postings, updates last_seen_at for existing jobs, generates FastEmbed embeddings
for net-new postings, and runs the 14-day inactivity and 15,000-job safeguard cleanup.
"""
import os
import sys
import json
import asyncio
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
import httpx
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.catalog_normalizer import (
    normalize_company,
    normalize_title,
    is_senior_role,
    extract_required_years,
    extract_skills,
    strip_html_and_truncate,
    parse_date_posted,
)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in environment")

URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}

# Regional keyword matching
INDIA_RE = re.compile(
    r"\b(india|bengaluru|bangalore|hyderabad|pune|gurgaon|gurugram|noida|delhi|mumbai|chennai)\b",
    re.IGNORECASE,
)
US_RE = re.compile(
    r"\b(united states|usa|u\.s\.a|u\.s\.|california|san francisco|new york|seattle|austin|texas|boston)\b",
    re.IGNORECASE,
)
REMOTE_RE = re.compile(
    r"\b(remote|anywhere|distributed|work from home|wfh)\b",
    re.IGNORECASE,
)

# Technical role keyword matching
ENG_TITLE_RE = re.compile(
    r"\b(engineer|developer|architect|programmer|scientist|devops|sre|qa|ml|ai|software|data|full\s*stack|frontend|backend|platform|mobile|ios|android|systems|security)\b",
    re.IGNORECASE,
)


def classify_job(title: str, location: str) -> Tuple[bool, str]:
    """Determines whether a job is technical engineering and classifies its region."""
    if not ENG_TITLE_RE.search(title):
        return False, ""

    text = f"{title} {location}".lower()
    if INDIA_RE.search(text):
        return True, "india"
    if REMOTE_RE.search(text):
        return True, "remote"
    if US_RE.search(text):
        return True, "us"

    return False, ""


def normalize_ats_payload(ats: str, slug: str, data: Any) -> List[Dict[str, Any]]:
    """Normalizes raw ATS JSON payloads into flat job dicts."""
    raw_jobs = []
    if ats == "greenhouse" and isinstance(data, dict):
        for j in data.get("jobs", []):
            url = j.get("absolute_url") or ""
            ext_id = str(j.get("id") or url.rstrip("/").split("/")[-1])
            raw_jobs.append({
                "ats": "greenhouse",
                "slug": slug,
                "ext_id": ext_id,
                "title": (j.get("title") or "").strip(),
                "company": (j.get("company_name") or slug).strip(),
                "location": ((j.get("location") or {}).get("name") or "").strip(),
                "url": url,
                "description": j.get("content") or "",
                "date_posted": j.get("updated_at") or j.get("first_published_at"),
            })
    elif ats == "lever" and isinstance(data, list):
        for j in data:
            url = j.get("hostedUrl") or ""
            ext_id = str(j.get("id") or url.rstrip("/").split("/")[-1])
            raw_jobs.append({
                "ats": "lever",
                "slug": slug,
                "ext_id": ext_id,
                "title": (j.get("text") or "").strip(),
                "company": slug,
                "location": ((j.get("categories") or {}).get("location") or "").strip(),
                "url": url,
                "description": j.get("descriptionPlain") or "",
                "date_posted": j.get("createdAt"),
            })
    elif ats == "ashby" and isinstance(data, dict):
        for j in data.get("jobs", []):
            url = j.get("jobUrl") or ""
            ext_id = str(j.get("id") or url.rstrip("/").split("/")[-1])
            raw_jobs.append({
                "ats": "ashby",
                "slug": slug,
                "ext_id": ext_id,
                "title": (j.get("title") or "").strip(),
                "company": slug,
                "location": (j.get("location") or "").strip(),
                "url": url,
                "description": j.get("descriptionPlain") or "",
                "date_posted": j.get("publishedAt"),
            })
    return raw_jobs


async def fetch_board(client: httpx.AsyncClient, sem: asyncio.Semaphore, ats: str, slug: str) -> List[Dict[str, Any]]:
    """Asynchronously fetches a single company board."""
    url = URLS[ats].format(slug=slug)
    async with sem:
        try:
            r = await client.get(url)
            if r.status_code == 200:
                return normalize_ats_payload(ats, slug, r.json())
        except Exception:
            pass
    return []


async def crawl_all_boards() -> List[Dict[str, Any]]:
    """Crawls all 530 boards in parallel with rate-limiting."""
    seed_file = ROOT / "scripts" / "seed" / "seed.json"
    boards = json.loads(seed_file.read_text(encoding="utf-8"))
    print(f"Crawling {len(boards)} boards...")

    sem = asyncio.Semaphore(15)
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, headers={"User-Agent": "JobMatcherBot/1.0"}) as client:
        tasks = [fetch_board(client, sem, b["ats"], b["slug"]) for b in boards]
        batches = await asyncio.gather(*tasks)

    all_raw = [j for batch in batches for j in batch]
    print(f"Retrieved {len(all_raw)} total postings from all boards.")

    # Filter and format
    candidates: List[Dict[str, Any]] = []
    seen_ids = set()

    for j in all_raw:
        title = j["title"]
        if not title or is_senior_role(title):
            continue

        is_eng, region = classify_job(title, j["location"])
        if not is_eng or not region:
            continue

        job_id = f"{j['ats']}:{j['slug']}:{j['ext_id']}"
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        desc = strip_html_and_truncate(j["description"], 1500)
        candidates.append({
            "id": job_id,
            "title": title,
            "company": j["company"],
            "normalized_company": normalize_company(j["company"]),
            "normalized_title": normalize_title(title),
            "location": j["location"] or region.capitalize(),
            "region": region,
            "category": "Engineering",
            "description": desc,
            "source_url": j["url"],
            "date_posted": parse_date_posted(j.get("date_posted")),
            "required_years": extract_required_years(desc),
            "skills": extract_skills(title + " " + desc),
        })

    print(f"Filtered to {len(candidates)} valid IC engineering jobs.")
    return candidates


def sync_to_database(jobs: List[Dict[str, Any]]):
    """Updates last_seen_at for existing jobs and embeds/inserts net-new jobs."""
    if not jobs:
        print("No jobs to sync.")
        return

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    with conn.cursor() as cur:
        # 1. Fetch all existing IDs from database
        cur.execute("SELECT id FROM public.jobs;")
        existing_ids = {r[0] for r in cur.fetchall()}
        print(f"Existing IDs in database: {len(existing_ids)}")

        crawled_map = {j["id"]: j for j in jobs}
        crawled_ids = set(crawled_map.keys())

        matched_existing = list(crawled_ids & existing_ids)
        net_new_ids = list(crawled_ids - existing_ids)

        print(f"Existing jobs seen in this crawl: {len(matched_existing)}")
        print(f"Net-new jobs discovered: {len(net_new_ids)}")

        # 2. Bulk update last_seen_at for existing jobs
        if matched_existing:
            update_sql = """
            UPDATE public.jobs
            SET last_seen_at = now(), is_active = true
            WHERE id = ANY(%s);
            """
            cur.execute(update_sql, (matched_existing,))
            conn.commit()
            print(f"Updated last_seen_at for {len(matched_existing)} existing jobs.")

        # 3. Generate embeddings and insert net-new jobs
        if net_new_ids:
            from fastembed import TextEmbedding
            print(f"Initializing FastEmbed model for {len(net_new_ids)} new jobs...")
            model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")

            new_records = [crawled_map[nid] for nid in net_new_ids]
            texts = [f"{j['title']}. {j['description'][:600]}" for j in new_records]
            embeddings = list(model.embed(texts, batch_size=64))

            insert_rows = []
            for j, emb in zip(new_records, embeddings):
                norm = sum(x * x for x in emb) ** 0.5 or 1.0
                norm_emb = [float(x / norm) for x in emb]
                insert_rows.append((
                    j["id"], j["title"], j["company"], j["normalized_company"], j["normalized_title"],
                    j["location"], j["region"], j["category"], j["description"], j["source_url"],
                    j["date_posted"], True, j["required_years"], j["skills"], str(norm_emb)
                ))

            insert_sql = """
            INSERT INTO public.jobs (
                id, title, company, normalized_company, normalized_title,
                location, region, category, description, source_url,
                date_posted, last_seen_at, is_active, required_years, skills, embedding
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                last_seen_at = now(),
                is_active = true;
            """
            template = "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s, %s::vector)"
            execute_values(cur, insert_sql, insert_rows, template=template)
            conn.commit()
            print(f"Successfully inserted {len(insert_rows)} new jobs with embeddings.")

        # 4. Automated Cleanup:
        # A. Mark inactive if not seen for 14 days
        cur.execute("""
            UPDATE public.jobs
            SET is_active = false
            WHERE is_active = true AND last_seen_at < NOW() - INTERVAL '14 days';
        """)
        stale_count = cur.rowcount
        conn.commit()
        if stale_count > 0:
            print(f"Marked {stale_count} stale jobs as inactive (>14 days unseen).")

        # B. Safeguard cap: Ensure active jobs do not exceed 15,000
        cur.execute("""
            DELETE FROM public.jobs
            WHERE id IN (
                SELECT id FROM public.jobs
                WHERE is_active = true
                ORDER BY last_seen_at ASC
                LIMIT GREATEST(0, (SELECT count(*) - 15000 FROM public.jobs WHERE is_active = true))
            );
        """)
        pruned_count = cur.rowcount
        conn.commit()
        if pruned_count > 0:
            print(f"Pruned {pruned_count} oldest jobs to maintain 15,000 free-tier ceiling.")

        # Final active count
        cur.execute("SELECT count(*) FROM public.jobs WHERE is_active = true;")
        active_total = cur.fetchone()[0]
        print(f"Total active jobs in database: {active_total}")

    conn.close()


def main():
    print("--- STARTING SCHEDULED CRAWL & SYNC ---")
    jobs = asyncio.run(crawl_all_boards())
    sync_to_database(jobs)
    print("--- CRAWL & SYNC COMPLETED SUCCESSFULLY ---")


if __name__ == "__main__":
    main()
