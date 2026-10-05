"""One-time batched Groq backfill for jobs that STILL have no skills after deterministic extraction.

Run it yourself when your Groq limits are fresh. Every call goes through the shared gateway
(key pool + RPM/TPM limiter + cooldowns), batches ~15 jobs per call, and writes each batch to the DB
as soon as it returns, so the script is safe to stop and re-run (it only selects still-blank jobs).
LLM output is mapped onto the shared skills taxonomy; unknown tokens are dropped so job and
candidate skills stay in one vocabulary.

DRY-RUN by default (prints job count and estimated Groq calls/tokens, makes NO Groq call).
Pass --apply to call Groq and write results.

Usage:
    python scripts/backfill_job_skills_llm.py                 # dry-run estimate
    python scripts/backfill_job_skills_llm.py --apply         # run it
    python scripts/backfill_job_skills_llm.py --apply --limit 150 --batch-size 12
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "apps" / "api" / ".env")
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.catalog_normalizer import canonicalize_skill
from app.services.groq_gateway import (
    GroqError,
    LLMBadResponse,
    LLMTruncated,
    LLMUnavailable,
    close_gateway,
    estimate_tokens,
    get_gateway,
)

DATABASE_URL = os.getenv("DATABASE_URL")
DESCRIPTION_CHARS = 900

SYSTEM_PROMPT = (
    "Extract the technical skills (languages, frameworks, libraries, databases, cloud/devops tools, ML/AI "
    "techniques, engineering practices) required or clearly implied by each job. Use short lowercase "
    "canonical names such as 'python', 'react', 'postgresql', 'docker', 'rest', 'machine learning'. "
    "Use [] when a job names no technical skills.\n"
    'Return JSON only: {"results":[{"k":"1","skills":["python"]}]} with one entry per job, `k` copied from the job.'
)


def build_messages(batch):
    jobs = [
        {"k": str(i), "title": j["title"] or "", "description": (j["description"] or "")[:DESCRIPTION_CHARS]}
        for i, j in enumerate(batch, start=1)
    ]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"jobs": jobs}, separators=(",", ":"), ensure_ascii=False)},
    ]


def parse_results(data, batch):
    key_to_id = {str(i): j["id"] for i, j in enumerate(batch, start=1)}
    out = {}
    for item in data.get("results") or []:
        job_id = key_to_id.get(str(item.get("k", "")).strip())
        if not job_id or not isinstance(item.get("skills"), list):
            continue
        canon = {canonicalize_skill(s) for s in item["skills"] if isinstance(s, str)}
        canon.discard(None)
        out[job_id] = sorted(canon)
    return out


async def run(args) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, description FROM public.jobs
        WHERE is_active = true
          AND region IN ('india', 'remote')
          AND (skills IS NULL OR cardinality(skills) = 0)
        ORDER BY region, id;
        """
    )
    jobs = [{"id": r[0], "title": r[1], "description": r[2]} for r in cur.fetchall()]
    if args.limit:
        jobs = jobs[: args.limit]
    batches = [jobs[i:i + args.batch_size] for i in range(0, len(jobs), args.batch_size)]
    sample_tokens = estimate_tokens(build_messages(jobs[: args.batch_size])) if jobs else 0
    print(f"{len(jobs)} blank-skill jobs -> {len(batches)} Groq calls (~{sample_tokens} input tokens each).")

    if not args.apply:
        print("DRY-RUN: no Groq call made. Re-run with --apply.")
        conn.close()
        return

    gw = get_gateway()
    if not gw.has_keys:
        print("No Groq API key configured.")
        conn.close()
        return

    tagged = 0
    for n, batch in enumerate(batches, start=1):
        try:
            result = await gw.chat_json(
                build_messages(batch),
                max_tokens=60 * len(batch) + 200,
                purpose="skills_backfill",
                max_wait=120.0,   # offline script: happily wait for the limiter
            )
        except LLMUnavailable as exc:
            print(f"Stopped: Groq unavailable ({exc.reason}); retry in ~{exc.retry_after:.0f}s. Re-run to continue.")
            break
        except (LLMTruncated, LLMBadResponse, GroqError) as exc:
            print(f"Batch {n}/{len(batches)} skipped: {exc}")
            continue

        found = {job_id: skills for job_id, skills in parse_results(result.data, batch).items() if skills}
        for job_id, skills in found.items():
            cur.execute(
                "UPDATE public.jobs SET skills = %s WHERE id = %s AND (skills IS NULL OR cardinality(skills) = 0);",
                (skills, job_id),
            )
        tagged += len(found)
        print(f"Batch {n}/{len(batches)}: tagged {len(found)}/{len(batch)} (total {tagged})", flush=True)

    conn.close()
    await close_gateway()
    print(f"Done. Tagged {tagged} jobs.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="call Groq and write (default is dry-run)")
    parser.add_argument("--limit", type=int, default=0, help="max jobs to process (0 = all)")
    parser.add_argument("--batch-size", type=int, default=15)
    args = parser.parse_args()
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL not set in .env")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
