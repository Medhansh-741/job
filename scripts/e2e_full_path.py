"""End-to-end latency/logic run of the real FastAPI app (in-process) for one real account + resume.

Phases (each timed like the UI experiences it):
  1. GET /matches baseline            (dashboard first paint)
  2. POST /resumes/upload             (new content hash -> worker runs the funnel -> ONE real Groq call)
  3. poll /matches/status @0.8s       (what the upload dialog does) + event-loop responsiveness
  4. GET /matches content checks      (logic: explained, sorted, de-duplicated, region, sizes)
  5. POST upload again                (identical resume -> cache hit, 0 Groq calls)
  6. matches deleted + upload again   (funnel re-runs entirely from the evaluation cache, 0 Groq calls)

Usage: python scripts/e2e_full_path.py <user_id> <email> <resume.pdf> [--fresh]
WRITES to the given account (replaces its resume record/matches/cache), as that account's normal upload would.
"""
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "apps" / "api" / ".env")
sys.path.insert(0, str(ROOT / "apps" / "api"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.auth import AuthenticatedUser, get_current_user  # noqa: E402
from app.core.db import clear_user_matches, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import groq_gateway, matching_engine  # noqa: E402

STAGES: dict = {}
GROQ_CALLS: list = []


def timed(name, fn):
    if asyncio.iscoroutinefunction(fn):
        async def wrapper(*a, **k):
            t = time.perf_counter()
            try:
                return await fn(*a, **k)
            finally:
                STAGES[name] = STAGES.get(name, 0.0) + (time.perf_counter() - t)
    else:
        def wrapper(*a, **k):
            t = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                STAGES[name] = STAGES.get(name, 0.0) + (time.perf_counter() - t)
    return wrapper


for _n in ("_fetch_catalog_rows", "_persist_matches"):
    setattr(matching_engine, _n, timed(_n, getattr(matching_engine, _n)))
matching_engine.rerank_finalists_with_llm = timed("rerank_total", matching_engine.rerank_finalists_with_llm)
matching_engine.get_candidate_profile = timed("get_profile", matching_engine.get_candidate_profile)
matching_engine.execute_live_fallback_search = timed("live_fallback", matching_engine.execute_live_fallback_search)

_orig_chat = groq_gateway.GroqGateway.chat_json


async def counting_chat(self, messages, **kw):
    t = time.perf_counter()
    res = await _orig_chat(self, messages, **kw)
    GROQ_CALLS.append({"purpose": kw.get("purpose"), "tokens": res.total_tokens, "key": res.key_label,
                       "seconds": round(time.perf_counter() - t, 2)})
    return res


groq_gateway.GroqGateway.chat_json = counting_chat


def poll_until_done(client, label, timeout=240):
    """Polls /matches/status every 0.8s like the upload dialog; returns timeline + max poll latency."""
    start = time.perf_counter()
    lats, seen = [], []
    while time.perf_counter() - start < timeout:
        t = time.perf_counter()
        s = client.get("/matches/status").json()
        lats.append(time.perf_counter() - t)
        if not seen or seen[-1][1] != s["step_label"]:
            seen.append((round(time.perf_counter() - start, 1), s["step_label"], s["status"]))
        if s["status"] in ("completed", "failed") and not (s["status"] == "completed" and False):
            break
        time.sleep(0.8)
    total = time.perf_counter() - start
    print(f"  [{label}] status flow: " + " -> ".join(f"{t}s '{l}'[{st}]" for t, l, st in seen))
    print(f"  [{label}] done after {total:.1f}s | status polls={len(lats)} max={max(lats)*1000:.0f}ms "
          f"median={statistics.median(lats)*1000:.0f}ms | final={s['status']} pending={s.get('analysis_pending')}")
    return total, s


def get_matches(client, label):
    t = time.perf_counter()
    r = client.get("/matches?region=india&limit=10")
    dt = time.perf_counter() - t
    j = r.json()
    print(f"  [{label}] GET /matches {dt*1000:.0f}ms -> HTTP {r.status_code}, {len(j['matches'])} matches, "
          f"status={j['status']}, analysis_pending={j['analysis_pending']}, payload={len(r.content)/1024:.1f}KB")
    return j, dt


def check_logic(matches):
    problems = []
    scores = [m["match_score"] for m in matches]
    if scores != sorted(scores, reverse=True):
        problems.append("matches not sorted by score desc")
    seen = set()
    for m in matches:
        key = ((m.get("company") or "").lower(), (m.get("title") or "").lower())
        if key in seen:
            problems.append(f"duplicate company/title: {key}")
        seen.add(key)
        if not (m.get("explanation") or "").strip():
            problems.append(f"missing explanation: {m['title']}")
        if (m.get("score_breakdown") or {}).get("llm_pending"):
            problems.append(f"pending row leaked: {m['title']}")
        bd = m.get("score_breakdown") or {}
        if bd.get("weights", {}).get("llm") != 0.7:
            problems.append(f"not LLM-blended: {m['title']}")
        if m.get("required_years") and m["required_years"] > 1:
            problems.append(f"requires {m['required_years']}y for a fresher: {m['title']}")
    comp = {}
    for m in matches:
        comp[m["company"]] = comp.get(m["company"], 0) + 1
    if any(c > 2 for c in comp.values()):
        problems.append(f"more than 2 jobs from one company: {comp}")
    print("  logic:", "OK" if not problems else problems)
    for m in matches:
        print(f"    {m['match_score']:>3} (math {m['score_breakdown'].get('math_score')})  {m['company'][:22]:22} {m['title'][:46]}")
    return problems


def delete_matches(user_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.matches WHERE user_id = %s;", (user_id,))
        conn.commit()


def main(user_id, email, resume_path, fresh=False):
    data = Path(resume_path).read_bytes()
    if fresh:
        clear_user_matches(user_id)   # wipes matches + cached evaluations so the funnel must call Groq
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(id=user_id, email=email, role="authenticated")
    t_boot = time.perf_counter()
    with TestClient(app) as client:
        print(f"app startup (lifespan): {time.perf_counter() - t_boot:.2f}s")
        client.get("/health")

        print("\n== 1. dashboard first paint (read-only /matches), 3 runs ==")
        for i in range(3):
            get_matches(client, f"baseline {i+1}")

        def upload(label):
            STAGES.clear(); GROQ_CALLS.clear()
            t = time.perf_counter()
            r = client.post("/resumes/upload", files={"file": (Path(resume_path).name, data, "application/pdf")})
            dt = time.perf_counter() - t
            j = r.json()
            print(f"  [{label}] POST /resumes/upload {dt:.2f}s -> HTTP {r.status_code}, is_cache_hit={j.get('profile', {}).get('is_cache_hit')}, "
                  f"skills={len(j.get('profile', {}).get('skills', []))}")
            return dt

        print("\n== 2+3. upload (new content hash) -> funnel -> poll like the UI ==")
        up = upload("fresh")
        total, status = poll_until_done(client, "fresh")
        print(f"  UI wait after upload returns: {total:.1f}s (upload request itself {up:.2f}s) => user waits ~{up + total:.1f}s")
        print("  funnel stages (s):", {k: round(v, 2) for k, v in STAGES.items()})
        print("  Groq calls:", GROQ_CALLS, "| total tokens:", sum(c['tokens'] for c in GROQ_CALLS))

        print("\n== 4. result logic ==")
        j, _ = get_matches(client, "after funnel")
        problems = check_logic(j["matches"])

        print("\n== 5. identical re-upload (expect cache-hit bypass, 0 Groq calls) ==")
        up = upload("identical")
        total, status = poll_until_done(client, "identical")
        print(f"  user waits ~{up + total:.1f}s | Groq calls: {len(GROQ_CALLS)}")

        print("\n== 6. matches deleted, upload again (funnel entirely from evaluation cache) ==")
        delete_matches(user_id)
        up = upload("cached-funnel")
        total, status = poll_until_done(client, "cached-funnel")
        print(f"  user waits ~{up + total:.1f}s")
        print("  stages:", {k: round(v, 2) for k, v in STAGES.items()}, "| Groq calls:", len(GROQ_CALLS))
        j2, _ = get_matches(client, "after cached funnel")
        same = [m["id"] for m in j["matches"]] == [m["id"] for m in j2["matches"]]
        print("  identical top-10 as the fresh run:", same)
        print("\nSUMMARY: logic problems:", problems or "none")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], fresh="--fresh" in sys.argv[4:])
