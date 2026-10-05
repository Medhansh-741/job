"""Offline unit tests for the funnel/Groq logic (no network, no DB writes). Run from apps/api:

    python -m unittest discover -s tests -v
"""
import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/db")  # never connected to in these tests
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")          # required at import; never called here

from app.services.catalog_normalizer import canonicalize_skill, clean_html_text, strip_html_and_truncate
from app.services.groq_gateway import GroqGateway, LLMTruncated, LLMUnavailable, parse_duration
from app.services.jd_parser import parse_job_description
from app.services import llm_reranker as rr
from app.services.matching_engine import should_trigger_live_fallback


def run(coro):
    return asyncio.run(coro)


def groq_ok(content: dict, total_tokens: int = 1000, finish: str = "stop"):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(content)}, "finish_reason": finish}],
        "usage": {"total_tokens": total_tokens},
    })


def make_gateway(handler, keys=(("k1", "key-1"), ("k2", "key-2")), **kw):
    return GroqGateway(list(keys), transport=httpx.MockTransport(handler), **kw)


def job(i, skills=("python",), score=80):
    return {"id": f"j:{i}", "title": f"Engineer {i}", "company": f"Co{i}", "description": "Build APIs. Work with Python.",
            "skills": list(skills), "match_score": score, "matched_skills": ["python"], "missing_skills": [], "date_posted": "2026-01-01"}


def evaluation(k):
    return {"k": str(k), "verdict": "Your RailMind project shows strong fit.", "strengths": ["python"], "gaps": [],
            "deductions": [], "capability_fit": 80, "tooling_fit": 80, "seniority_fit": 80}


PROFILE = {"headline": "Dev", "skills": ["python"], "experience_years": 0.0, "raw_json": {"is_fresher": True}}


class GatewayTests(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(parse_duration("7.66s"), 7.66)
        self.assertAlmostEqual(parse_duration("2m59.56s"), 179.56)
        self.assertEqual(parse_duration("120"), 120.0)
        self.assertIsNone(parse_duration(None))

    def test_429_naming_org_cools_down_keys_in_that_org(self):
        calls = []

        def handler(req):
            calls.append(req.headers["authorization"])
            return httpx.Response(429, headers={"retry-after": "90"},
                                  json={"error": {"message": "limit in organization `org_abc` on tokens per day"}})

        gw = make_gateway(handler)

        async def go():
            with self.assertRaises(LLMUnavailable) as ctx:
                await gw.chat_json([{"role": "user", "content": "x"}], max_tokens=50)
            first_round = len(calls)
            with self.assertRaises(LLMUnavailable):          # org now known: both keys already cooling
                await gw.chat_json([{"role": "user", "content": "x"}], max_tokens=50, max_wait=5)
            self.assertEqual(len(calls), first_round, "no request may be wasted on a cooling org")
            self.assertGreaterEqual(ctx.exception.retry_after, 60)
            await gw.aclose()

        run(go())

    def test_truncation_and_invalid_json_raise_truncated(self):
        async def go(response):
            gw = make_gateway(lambda req: response)
            try:
                with self.assertRaises(LLMTruncated):
                    await gw.chat_json([{"role": "user", "content": "x"}], max_tokens=50)
            finally:
                await gw.aclose()

        run(go(groq_ok({"evaluations": []}, finish="length")))
        run(go(httpx.Response(200, json={"choices": [{"message": {"content": "{not json"}, "finish_reason": "stop"}]})))

    def test_reasoning_params_dropped_if_model_rejects_them(self):
        seen = []

        def handler(req):
            body = json.loads(req.content)
            seen.append("reasoning_effort" in body)
            if "reasoning_effort" in body:
                return httpx.Response(400, json={"error": {"message": "reasoning_effort is not supported"}})
            return groq_ok({"ok": True})

        gw = make_gateway(handler)

        async def go():
            res = await gw.chat_json([{"role": "user", "content": "x"}], max_tokens=50)
            self.assertEqual(res.data, {"ok": True})
            await gw.aclose()

        run(go())
        self.assertEqual(seen, [True, False])


class RerankTests(unittest.TestCase):
    def test_ordinal_keys_map_back_and_invalid_items_are_ignored(self):
        def handler(req):
            return groq_ok({"evaluations": [evaluation(1), {"k": "2", "verdict": "x"}, evaluation(3)]})

        gw = make_gateway(handler)
        jobs = [job(1, score=90), job(2, score=85), job(3, score=80)]
        out = run(rr.rerank_finalists_with_llm(PROFILE, jobs, target=3, initial=3, gateway=gw,
                                               cache_get=lambda *a: asyncio.sleep(0, {}), cache_put=lambda *a: asyncio.sleep(0)))
        self.assertEqual({m["id"] for m in out.explained}, {"j:1", "j:3"})      # invalid item for job 2 dropped
        self.assertEqual([p["id"] for p in out.pending], ["j:2"])               # hidden until explained
        self.assertTrue(out.pending[0]["score_breakdown"]["llm_pending"])
        self.assertIsNotNone(out.retry_after)                                   # worker must retry the gap
        run(gw.aclose())

    def test_topup_fills_to_target_from_next_ranked(self):
        calls = []

        def handler(req):
            n = len(json.loads(req.content)["messages"][1]["content"].split('"k":')) - 1
            calls.append(n)
            # first call explains only 2 of 3 jobs; the top-up call explains every job it is given
            keys = [1, 2] if len(calls) == 1 else list(range(1, n + 1))
            return groq_ok({"evaluations": [evaluation(k) for k in keys]})

        gw = make_gateway(handler)
        jobs = [job(i, score=90 - i) for i in range(1, 6)]
        out = run(rr.rerank_finalists_with_llm(PROFILE, jobs, target=3, initial=3, gateway=gw,
                                               cache_get=lambda *a: asyncio.sleep(0, {}), cache_put=lambda *a: asyncio.sleep(0)))
        self.assertEqual(len(out.explained), 3)
        self.assertEqual(len(calls), 2, "one initial call + exactly one top-up")
        self.assertIsNone(out.retry_after)
        run(gw.aclose())

    def test_unavailable_groq_returns_pending_and_never_raises(self):
        gw = make_gateway(lambda req: httpx.Response(429, headers={"retry-after": "30"}, json={}))
        out = run(rr.rerank_finalists_with_llm(PROFILE, [job(1)], target=1, initial=1, gateway=gw,
                                               cache_get=lambda *a: asyncio.sleep(0, {}), cache_put=lambda *a: asyncio.sleep(0)))
        self.assertEqual(out.explained, [])
        self.assertEqual(len(out.pending), 1)
        self.assertGreaterEqual(out.retry_after, 1)
        run(gw.aclose())

    def test_cached_evaluations_cost_zero_groq_calls(self):
        calls = []
        gw = make_gateway(lambda req: calls.append(1) or groq_ok({"evaluations": []}))
        jobs = [job(1), job(2)]
        cached = {j["id"]: (rr.job_signature(j), evaluation(0)) for j in jobs}

        async def cache_get(*_a):
            return cached

        out = run(rr.rerank_finalists_with_llm(PROFILE, jobs, target=2, initial=2, gateway=gw, user_id="u", content_hash="h",
                                               cache_get=cache_get, cache_put=lambda *a: asyncio.sleep(0)))
        self.assertEqual(len(out.explained), 2)
        self.assertEqual(calls, [], "fully cached run must not call Groq")
        run(gw.aclose())

    def test_stale_cache_is_ignored_when_job_changed(self):
        calls = []
        gw = make_gateway(lambda req: calls.append(1) or groq_ok({"evaluations": [evaluation(1)]}))
        j = job(1)
        cached = {j["id"]: ("stale-signature", evaluation(0))}

        async def cache_get(*_a):
            return cached

        out = run(rr.rerank_finalists_with_llm(PROFILE, [j], target=1, initial=1, gateway=gw, user_id="u", content_hash="h",
                                               cache_get=cache_get, cache_put=lambda *a: asyncio.sleep(0)))
        self.assertEqual(len(calls), 1, "changed job signature must trigger a fresh evaluation")
        self.assertEqual(len(out.explained), 1)
        run(gw.aclose())

    def test_blank_skill_job_flagged_and_only_preferred_skills_become_required(self):
        blank = rr.compress_job_card({**job(1), "skills": [], "description": "Build things."}, ["python"])
        _, user_prompt, _ = rr.build_rerank_prompt({"skills": ["python"]}, [blank])
        self.assertIn('"skills_unknown":true', user_prompt)

        only_pref = rr.compress_job_card(
            {**job(2), "skills": ["react"], "description": "Preferred Skills: React Criteria: build UIs."}, [])
        self.assertEqual(only_pref["required_skills"], ["react"])
        self.assertEqual(only_pref["preferred_skills"], [])


class ParsingTests(unittest.TestCase):
    def test_jd_parser_does_not_split_hyphenated_words(self):
        text = ("Responsibilities: Build end-to-end features for our hands-on customers. "
                "Write and maintain production-level Python code. Requirements: Python, FastAPI.")
        parsed = parse_job_description(text, tagged_skills=["python", "fastapi"])
        joined = " ".join(parsed["responsibilities"])
        self.assertIn("end-to-end", joined)
        self.assertIn("production-level", joined)

    def test_clean_html_text_vs_truncate(self):
        raw = "<p>" + "Python " * 600 + "</p>"
        self.assertGreater(len(clean_html_text(raw)), 1500)
        self.assertEqual(len(strip_html_and_truncate(raw)), 1500)

    def test_canonicalize_skill(self):
        self.assertEqual(canonicalize_skill("PostgreSQL"), "postgresql")
        self.assertEqual(canonicalize_skill("k8s"), "kubernetes")
        self.assertIsNone(canonicalize_skill("underwater basket weaving"))


class FunnelRuleTests(unittest.TestCase):
    def test_live_fallback_only_when_catalog_has_fewer_than_10_rows(self):
        self.assertTrue(should_trigger_live_fallback(9, ["ML Engineer"]))
        self.assertFalse(should_trigger_live_fallback(10, ["ML Engineer"]))
        self.assertFalse(should_trigger_live_fallback(100, ["ML Engineer"]))
        self.assertFalse(should_trigger_live_fallback(0, []))

    def test_region_filter_is_read_only_view(self):
        from app.main import filter_matches_by_region
        ms = [{"region": "india"}, {"region": "remote"}, {"region": "us"}]
        self.assertEqual(len(filter_matches_by_region(ms, "india")), 2)
        self.assertEqual(len(filter_matches_by_region(ms, "us")), 2)
        self.assertEqual(len(filter_matches_by_region(ms, "all")), 3)
        self.assertEqual(filter_matches_by_region([{"region": "us"}], "india"), [])   # miss -> empty, never a rerun


if __name__ == "__main__":
    unittest.main()
