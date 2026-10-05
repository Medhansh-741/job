"""Live smoke test of the rerank path: ONE real Groq call (maybe one top-up), nothing written.

Builds the candidate pool for a user exactly like the funnel (read-only DB), then runs
rerank_finalists_with_llm through the real gateway with caching disabled. Prints the
estimated prompt size, the gateway log lines, the explanations and the limiter state.

Usage: python scripts/live_smoke_rerank.py <user_id> [--cache]
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "apps" / "api" / ".env")
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.db import get_candidate_profile
from app.services.groq_gateway import close_gateway, estimate_tokens, get_gateway
from app.services import llm_reranker as rr
from app.services.matching_engine import (
    CANDIDATE_POOL_MIN, DISPLAY_LIMIT, INITIAL_EVAL_EXTRA, _fetch_catalog_rows, score_job,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252


async def no_cache_get(*_a):
    return {}


async def no_cache_put(*_a):
    return None


async def main(user_id: str, use_cache: bool = False) -> None:
    profile = get_candidate_profile(user_id)
    rows = _fetch_catalog_rows(
        profile["embedding"], "india", profile.get("experience_years") or 0.0,
        (profile.get("raw_json") or {}).get("is_fresher", True),
    )
    scored = []
    for r in rows:
        audit = score_job(r["similarity"], profile["skills"], r["skills"], profile.get("preferred_roles") or [],
                          profile.get("headline"), r["title"], r.get("normalized_title") or "")
        scored.append({
            "id": r["id"], "title": r["title"], "company": r["company"],
            "normalized_company": r.get("normalized_company"), "normalized_title": r.get("normalized_title"),
            "location": r["location"], "region": r["region"], "description": r["description"],
            "source_url": r["source_url"], "date_posted": r["date_posted"].isoformat() if r.get("date_posted") else None,
            "required_years": r["required_years"], "skills": r["skills"] or [], **audit,
        })
    scored.sort(key=lambda j: (j["match_score"], j.get("date_posted") or "1970-01-01", j["id"]), reverse=True)

    counts, seen, pool = {}, set(), []
    for j in scored:
        comp = (j.get("normalized_company") or j["company"] or "unknown").lower().strip()
        role = (comp, (j.get("normalized_title") or j["title"] or "").lower().strip())
        if role in seen or counts.get(comp, 0) >= 2:
            continue
        seen.add(role)
        counts[comp] = counts.get(comp, 0) + 1
        pool.append(j)
        if len(pool) >= max(DISPLAY_LIMIT + 10, CANDIDATE_POOL_MIN):
            break

    initial = DISPLAY_LIMIT + INITIAL_EVAL_EXTRA
    candidate = rr.extract_candidate_snapshot(profile)
    cards = [rr.compress_job_card(j, candidate["skills"]) for j in pool[:initial]]
    system_prompt, user_prompt, _ = rr.build_rerank_prompt(candidate, cards)
    est = estimate_tokens([{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])
    print(f"Pool: {len(pool)} candidates; first call = {initial} jobs, ~{est} estimated input tokens (pessimistic).")

    gw = get_gateway()
    print(f"Gateway: model={gw.model} keys={len(gw.keys)} rpm={gw.rpm} tpm={gw.tpm}")
    out = await rr.rerank_finalists_with_llm(
        profile, pool, target=DISPLAY_LIMIT, initial=initial, user_id=user_id,
        content_hash=profile.get("content_hash"), gateway=gw,
        # --cache: use the real llm_evaluations table so a successful call is reused by the app (0 tokens later)
        cache_get=None if use_cache else no_cache_get, cache_put=None if use_cache else no_cache_put,
    )

    print(f"\nLLM calls: {out.llm_calls} | explained: {len(out.explained)} | pending: {len(out.pending)} "
          f"| retry_after: {out.retry_after} | error: {out.error}")
    for m in out.explained:
        print(f"  {m['match_score']:>3} (math {m['score_breakdown']['math_score']:>3})  {m['company']} - {m['title']}")
        print(f"       {m['explanation']}")
    print("\nLimiter state:", gw.snapshot())
    await close_gateway()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], use_cache="--cache" in sys.argv[2:]))
