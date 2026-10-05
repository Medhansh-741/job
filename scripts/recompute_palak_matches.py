import asyncio
import os
import sys
import json
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "apps" / "api"))
load_dotenv(project_root / ".env")

from app.services.matching_engine import execute_matching_funnel

USER_ID = "13d60130-2efb-4a6b-b8b1-730e616a1785" # medhansh541@gmail.com (Palak's resume)

async def main():
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg2.connect(db_url)
    
    print(f"Purging stale matches for user {USER_ID}...")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM public.matches WHERE user_id = %s;", (USER_ID,))
        conn.commit()
    print("Stale matches deleted.")
    
    print(f"Executing full matching funnel for user {USER_ID} (region='india', limit=15)...")
    res = await execute_matching_funnel(user_id=USER_ID, target_region="india", limit=15)
    
    matches = res.get("matches", [])
    print(f"\nFunnel execution complete! Returned {len(matches)} matches.")
    
    # Query database to inspect persisted rows
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT m.job_id, j.title, j.company, m.match_score, m.score_breakdown, m.explanation
            FROM public.matches m
            JOIN public.jobs j ON m.job_id = j.id
            WHERE m.user_id = %s
            ORDER BY m.match_score DESC;
            """,
            (USER_ID,)
        )
        persisted = cur.fetchall()
    conn.close()
    
    print("\nPersisted Top Matches in public.matches:")
    print("=" * 80)
    for idx, p in enumerate(persisted, 1):
        bd = p.get("score_breakdown") or {}
        print(f"{idx}. [{p['match_score']}%] {p['title']} @ {p['company']}")
        print(f"   Verdict:    {p.get('explanation')}")
        print(f"   Strengths:  {p.get('matched_skills') or bd.get('strengths')}")
        print(f"   Gaps:       {p.get('missing_skills') or bd.get('gaps')}")
        print(f"   Deductions: {bd.get('deductions')}")
        print("-" * 80)

if __name__ == "__main__":
    asyncio.run(main())
