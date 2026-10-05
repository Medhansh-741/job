import sys
from pathlib import Path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "apps" / "api"))

import asyncio
from app.services.matching_engine import execute_matching_funnel

async def run():
    uid = '13d60130-2efb-4a6b-b8b1-730e616a1785'
    res = await execute_matching_funnel(uid, target_region='india', limit=25)
    print('Matches computed:', len(res['matches']))
    print('Strong matches:', res['strong_matches_count'])
    for m in res['matches'][:5]:
        print(f"[{m['match_score']}%] {m['title']} @ {m['company']} ({m['region']})")
        print("   Matched:", m['matched_skills'])
        print("   Missing:", m['missing_skills'][:3])

asyncio.run(run())
