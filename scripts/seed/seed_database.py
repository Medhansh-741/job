"""Day-1 Database Seeding Pipeline.

Seeds Supabase Postgres with pre-crawled IC engineering jobs and their 384-dimensional
vector embeddings from the spike dataset.
"""
import os
import sys
import json
from pathlib import Path
from typing import List, Tuple, Any
import numpy as np
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
    raise ValueError("DATABASE_URL not found in .env")

SPIKE_DATA = ROOT / "scripts" / "spike" / "data"
JOBS_PATH = SPIKE_DATA / "jobs.json"
EMB_PATH = SPIKE_DATA / "job_emb.npy"


def main():
    print(f"Loading jobs from {JOBS_PATH}...")
    jobs = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(jobs)} raw jobs.")

    print(f"Loading precomputed embeddings from {EMB_PATH}...")
    emb = np.load(EMB_PATH)
    if len(emb) != len(jobs):
        raise ValueError(f"Mismatch: {len(jobs)} jobs but {len(emb)} embeddings.")

    # Normalize vectors just to be safe
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    emb = emb / norms

    records: List[Tuple[Any, ...]] = []
    skipped_senior = 0
    skipped_region = 0

    seen_ids = set()

    print("Filtering and formatting records...")
    for i, j in enumerate(jobs):
        title = j.get("title", "").strip()
        if not title:
            continue

        if is_senior_role(title):
            skipped_senior += 1
            continue

        region = (j.get("region") or "").lower()
        if region not in ("india", "us", "remote"):
            skipped_region += 1
            continue

        url = j.get("url", "").strip()
        if not url:
            continue

        ats = j.get("ats", "ats")
        slug = j.get("slug", "company")
        ext_id = url.rstrip("/").split("/")[-1].split("?")[0]
        job_id = f"{ats}:{slug}:{ext_id}"

        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        company = j.get("company", slug).strip()
        norm_company = normalize_company(company)
        norm_title = normalize_title(title)
        location = j.get("location", "").strip() or region.capitalize()
        category = "Engineering"
        desc = strip_html_and_truncate(j.get("description", ""), 1500)
        date_posted = parse_date_posted(j.get("date_posted") or j.get("postedAt"))
        req_years = extract_required_years(desc)
        skills = extract_skills(title + " " + desc)
        embedding_list = emb[i].tolist()

        records.append((
            job_id,
            title,
            company,
            norm_company,
            norm_title,
            location,
            region,
            category,
            desc,
            url,
            date_posted,
            req_years,
            skills,
            embedding_list,
        ))

    print(f"Prepared {len(records)} pure IC engineering jobs.")
    print(f"Filtered out: {skipped_senior} senior/leadership roles, {skipped_region} non-target regions.")

    print(f"Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    insert_sql = """
    INSERT INTO public.jobs (
        id, title, company, normalized_company, normalized_title,
        location, region, category, description, source_url,
        date_posted, last_seen_at, is_active, required_years, skills, embedding
    ) VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        title = EXCLUDED.title,
        company = EXCLUDED.company,
        normalized_company = EXCLUDED.normalized_company,
        normalized_title = EXCLUDED.normalized_title,
        location = EXCLUDED.location,
        region = EXCLUDED.region,
        description = EXCLUDED.description,
        source_url = EXCLUDED.source_url,
        last_seen_at = now(),
        is_active = true,
        required_years = EXCLUDED.required_years,
        skills = EXCLUDED.skills,
        embedding = EXCLUDED.embedding;
    """

    batch_size = 500
    total_inserted = 0

    with conn.cursor() as cur:
        for start_idx in range(0, len(records), batch_size):
            chunk = records[start_idx:start_idx + batch_size]
            # Format row tuples to include last_seen_at=now() and is_active=true
            formatted_chunk = [
                (
                    r[0], r[1], r[2], r[3], r[4],
                    r[5], r[6], r[7], r[8], r[9],
                    r[10], True, r[11], r[12], str(r[13])
                )
                for r in chunk
            ]
            template = "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s, %s::vector)"
            execute_values(cur, insert_sql, formatted_chunk, template=template)
            conn.commit()
            total_inserted += len(chunk)
            print(f"Upserted {total_inserted} / {len(records)} jobs...")

        # Run verification queries
        cur.execute("SELECT count(*) FROM public.jobs;")
        total_in_db = cur.fetchone()[0]

        cur.execute("SELECT region, count(*) FROM public.jobs GROUP BY region;")
        by_region = cur.fetchall()

        cur.execute("SELECT pg_size_pretty(pg_total_relation_size('public.jobs'));")
        table_size = cur.fetchone()[0]

        print("\n--- DATABASE VERIFICATION ---")
        print(f"Total jobs in public.jobs: {total_in_db}")
        print(f"Jobs by region: {dict(by_region)}")
        print(f"Total disk size of public.jobs (data + vector + indexes): {table_size}")
        print("-----------------------------\n")

    conn.close()
    print("Database seeding completed successfully!")


if __name__ == "__main__":
    main()
