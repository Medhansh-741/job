"""Prerequisite Migration: Catalog Skills Backfill.

Populates the `skills` column for the 2,841 jobs where `skills = '{}' OR skills IS NULL`
using the deterministic `extract_skills` normalizer on the job descriptions.
"""
import os
import sys
from pathlib import Path
import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.catalog_normalizer import extract_skills

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in .env")


def main():
    print("Connecting to Supabase PostgreSQL...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    with conn.cursor() as cur:
        # 1. Fetch jobs needing skill extraction
        cur.execute(
            """
            SELECT id, title, description
            FROM public.jobs
            WHERE skills = '{}' OR skills IS NULL;
            """
        )
        rows = cur.fetchall()
        print(f"Discovered {len(rows)} jobs with empty skills.")

        if not rows:
            print("No jobs need skill backfill. Catalog is 100% complete!")
            conn.close()
            return

        # 2. Extract skills from description
        updates = []
        newly_tagged = 0
        for job_id, title, description in rows:
            # Combine title and description for maximum keyword capture
            combined_text = f"{title}\n{description or ''}"
            skills = extract_skills(combined_text)
            if skills:
                newly_tagged += 1
            updates.append((skills, job_id))

        print(f"Extracted recognizable tech skills for {newly_tagged} / {len(rows)} jobs.")

        # 3. Batch update public.jobs
        print("Executing bulk database updates...")
        update_sql = """
        UPDATE public.jobs
        SET skills = %s
        WHERE id = %s;
        """
        execute_batch(cur, update_sql, updates, page_size=500)
        conn.commit()
        print(f"Successfully committed updates for {len(updates)} jobs.")

        # 4. Verify post-migration count
        cur.execute(
            """
            SELECT 
                COUNT(*) FILTER (WHERE array_length(skills, 1) > 0),
                COUNT(*) FILTER (WHERE skills = '{}' OR skills IS NULL)
            FROM public.jobs;
            """
        )
        has_skills, no_skills = cur.fetchone()
        print("\nPost-Backfill Verification:")
        print(f"  Jobs with tagged skills: {has_skills}")
        print(f"  Jobs with empty skills:  {no_skills}")

    conn.close()
    print("\nBackfill script finished successfully!")


if __name__ == "__main__":
    main()
