"""Offline skills re-extraction for the job catalog (no Groq, no network besides the DB).

Re-runs the deterministic `extract_skills` over the stored job text with the widened taxonomy and
UNIONS the result with the skills already stored (never removes a skill).

DRY-RUN by default: prints how many jobs would change and how many blank jobs get fixed.
Pass --apply to write the changes.

Usage:
    python scripts/backfill_job_skills.py            # dry-run
    python scripts/backfill_job_skills.py --apply    # write
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "apps" / "api" / ".env")
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.catalog_normalizer import extract_skills, extract_required_years

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in .env")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write changes (default is dry-run)")
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, description, COALESCE(skills, '{}'), required_years FROM public.jobs WHERE is_active = true;"
        )
        rows = cur.fetchall()
        print(f"Loaded {len(rows)} active jobs.")

        updates = []
        year_updates = []   # fills required_years ONLY where it is NULL (never overwrites a stored value)
        blank_before = blank_after = thin_before = thin_after = 0
        for job_id, title, description, old, old_years in rows:
            if old_years is None:
                years = extract_required_years(description or "")
                if years is not None:
                    year_updates.append((years, job_id))
            extracted = extract_skills(f"{title}\n{description or ''}")
            new = sorted(set(old) | set(extracted))
            blank_before += len(old) == 0
            thin_before += len(old) < 2
            blank_after += len(new) == 0
            thin_after += len(new) < 2
            if new != sorted(old):
                updates.append((new, job_id))

        print(f"Jobs that would change:      {len(updates)}")
        print(f"required_years to fill (NULL -> value): {len(year_updates)}  e.g. {year_updates[:5]}")
        print(f"Blank skills (0): {blank_before} -> {blank_after}")
        print(f"Thin skills (<2): {thin_before} -> {thin_after}")

        if not args.apply:
            print("\nDRY-RUN: nothing written. Re-run with --apply to commit.")
            conn.rollback()
            conn.close()
            return

        execute_batch(cur, "UPDATE public.jobs SET skills = %s WHERE id = %s;", updates, page_size=500)
        execute_batch(cur, "UPDATE public.jobs SET required_years = %s WHERE id = %s AND required_years IS NULL;",
                      year_updates, page_size=500)
        conn.commit()
        print(f"\nCommitted skill updates for {len(updates)} jobs and required_years for {len(year_updates)} jobs.")

    conn.close()


if __name__ == "__main__":
    main()
