import os
import re
import json
import asyncio
import httpx
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = "openai/gpt-oss-20b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SEMAPHORE = asyncio.Semaphore(12)

PROMPT_TEMPLATE = """Extract all technical skills, programming languages, libraries, frameworks, cloud tools, databases, and engineering methodologies mentioned or implied in this job description.
Return ONLY a valid JSON object matching this schema:
{{"skills": ["skill1", "skill2"]}}
All skills must be lowercase canonical names (e.g., 'python', 'react', 'fastapi', 'postgresql', 'docker', 'rest', 'oop', 'sql', 'git', 'c++', 'testing', 'linux').
If no technical skills are mentioned, return {{"skills": []}}.

Job Title: {title}
Company: {company}
Description:
{description}"""


async def extract_skills_for_job(client: httpx.AsyncClient, job: dict) -> tuple:
    job_id = job["id"]
    title = job["title"] or ""
    company = job["company"] or ""
    desc = (job["description"] or "")[:1200]

    prompt = PROMPT_TEMPLATE.format(title=title, company=company, description=desc)

    for attempt in range(3):
        async with SEMAPHORE:
            try:
                resp = await client.post(
                    GROQ_URL,
                    json={
                        "model": MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=15.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    skills = parsed.get("skills", [])
                    # Clean and deduplicate skills
                    cleaned = sorted(list(set(
                        s.lower().strip() for s in skills 
                        if isinstance(s, str) and 1 <= len(s.strip()) <= 35
                    )))
                    return job_id, cleaned
                elif resp.status_code == 429:
                    await asyncio.sleep(2.0 * (attempt + 1))
                else:
                    await asyncio.sleep(1.0)
            except Exception as e:
                await asyncio.sleep(1.0)

    return job_id, []


async def main():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, company, description
        FROM public.jobs
        WHERE is_active = true
          AND region IN ('india', 'remote')
          AND (skills IS NULL OR cardinality(skills) = 0)
        ORDER BY created_at DESC;
    """)
    rows = cur.fetchall()
    jobs = [{"id": r[0], "title": r[1], "company": r[2], "description": r[3]} for r in rows]
    total = len(jobs)
    print(f"Found {total} India/Remote jobs with empty skills to enrich.")

    if total == 0:
        conn.close()
        return

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(http2=True, headers=headers, timeout=20.0) as client:
        batch_size = 25
        enriched_count = 0
        
        for i in range(0, total, batch_size):
            chunk = jobs[i:i + batch_size]
            tasks = [extract_skills_for_job(client, j) for j in chunk]
            results = await asyncio.gather(*tasks)

            # Update DB with enriched skills
            update_data = [(skills, job_id) for job_id, skills in results if skills]
            if update_data:
                with conn.cursor() as update_cur:
                    execute_values(
                        update_cur,
                        """
                        UPDATE public.jobs AS j
                        SET skills = v.skills
                        FROM (VALUES %s) AS v(skills, id)
                        WHERE j.id = v.id;
                        """,
                        update_data,
                        template="(%s::text[], %s)",
                    )
                enriched_count += len(update_data)

            processed = min(i + batch_size, total)
            print(f"Progress: {processed}/{total} jobs processed. Enriched: {enriched_count}", flush=True)

    conn.close()
    print(f"Backfill complete! Successfully enriched {enriched_count}/{total} jobs.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
