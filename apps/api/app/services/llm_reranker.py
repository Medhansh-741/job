"""Groq LLM Re-Ranking Layer (Phase 4.3 of the matching funnel).

Design:
1. The funnel hands over an ordered candidate pool (best math score first).
2. The first `initial` (12) candidates are evaluated in ONE listwise call; evaluations already cached
   for this resume version (public.llm_evaluations) are reused and never re-paid.
3. If fewer than `target` (10) candidates ended up explained, at most one small top-up call evaluates
   the next-ranked candidates. A job without an LLM verdict never surfaces to the user.
4. Truncated / invalid-JSON responses shrink the batch (split in halves) instead of switching models.
5. Rate limits / outages never raise: the outcome reports `retry_after` so the worker can retry later
   (only uncached jobs are called again). All Groq traffic goes through groq_gateway.
6. Final score is blended deterministically in Python: 30% math + 70% LLM rubric.
"""
import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Callable, Awaitable

from app.services.jd_parser import parse_job_description
from app.services.groq_gateway import (
    GroqGateway,
    GroqError,
    LLMUnavailable,
    LLMTruncated,
    LLMBadResponse,
    get_gateway,
)

logger = logging.getLogger("llm_reranker")
logger.setLevel(logging.INFO)

MAX_LLM_CALLS_PER_RUN = 4          # initial + top-up + at most two shrink splits
TOPUP_MAX_JOBS = 6
DEFAULT_RETRY_AFTER = 45.0
TOKENS_PER_JOB = 170               # output budget per evaluated job (verdict + lists + 3 scores)
TOKENS_BASE = 350


@dataclass
class RerankOutcome:
    explained: List[Dict[str, Any]] = field(default_factory=list)   # LLM-explained, sorted, <= target
    pending: List[Dict[str, Any]] = field(default_factory=list)     # math-only, hidden until explained
    retry_after: Optional[float] = None                             # seconds; None = nothing to retry
    llm_calls: int = 0
    error: Optional[str] = None                                     # configuration error (no key)


def _extract_projects_from_text(projects_content: str) -> List[Dict[str, Any]]:
    """Extracts structured project items with names and summaries from resume text."""
    if not projects_content:
        return []

    stop_headings = [
        "experience & leadership", "experience", "work experience",
        "leadership", "positions of responsibility", "extracurricular",
        "education", "skills", "achievements"
    ]
    projects = []
    lines = [l.strip() for l in projects_content.split("\n") if l.strip()]
    current_proj = None

    for line in lines:
        lower = line.lower()
        if any(lower == h or lower.startswith(h + " ") for h in stop_headings):
            break

        # Check for bullet: starts with standard bullet chars, replacement chars, or numbers
        is_bullet = (
            line[0] in ("�", "•", "*", "-", "·", "▪", "▫", "○", "●")
            or bool(re.match(r"^(\([a-zA-Z0-9]+\)|\[[0-9]+\]|[0-9]+\.)\s", line))
        )

        if not is_bullet:
            parts = re.split(r"\s+[|–—�•·]\s+|\s+-\s+", line)
            if len(parts) >= 2:
                p_name = parts[0].strip("•*-–—·▪▫○● \t�")
                p_name = re.sub(r"^(Project:?|Name:?)\s*", "", p_name, flags=re.I).strip()
                rest = " ".join(parts[1:])
                has_anchor = bool(re.search(r"(github|live|demo|20\d\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|python|react|next\.?js|fastapi|node|c\+\+|pytorch|ai|ml|typescript|javascript)", rest, re.I))
                starts_capital = bool(re.match(r"^[A-Z][a-zA-Z0-9\s]{2,}", p_name))
                if starts_capital and (has_anchor or len(p_name) <= 40) and not any(h in p_name.lower() for h in stop_headings):
                    current_proj = {"name": p_name, "summary": ""}
                    projects.append(current_proj)
                    if len(projects) >= 5:
                        break
                    continue

        if current_proj and is_bullet:
            text = line.lstrip("•*-–—·▪▫○● \t�(cid:0123456789)")
            if len(current_proj["summary"]) < 200:
                if current_proj["summary"]:
                    current_proj["summary"] += " " + text
                else:
                    current_proj["summary"] = text

    return projects


def _extract_experience_from_text(exp_content: str) -> List[Dict[str, Any]]:
    """Extracts structured work/internship items with roles and companies."""
    if not exp_content:
        return []
    experiences = []
    lines = [l.strip() for l in exp_content.split("\n") if l.strip()]
    current_exp = None
    for line in lines:
        is_bullet = (
            line[0] in ("�", "•", "*", "-", "·", "▪")
            or bool(re.match(r"^(\([a-zA-Z0-9]+\)|\[[0-9]+\]|[0-9]+\.)\s", line))
        )
        if is_bullet:
            if current_exp and len(current_exp["summary"]) < 180:
                text = line.lstrip("•*-–—·▪ \t�")
                current_exp["summary"] += (" " + text) if current_exp["summary"] else text
        elif any(sep in line for sep in ["|", "–", "—", "@", "at ", " - ", "�"]) and len(line) < 120:
            parts = re.split(r"\s+[|–—�@]\s+|\s+-\s+|\s+at\s+", line)
            title = parts[0].strip("•*-–—·▪ \t�")
            if len(title) >= 3 and len(title) <= 70:
                current_exp = {"role_and_company": title, "summary": ""}
                experiences.append(current_exp)
                if len(experiences) >= 3:
                    break
        elif current_exp and not current_exp["summary"]:
            current_exp["summary"] = line[:180]
    return experiences


def extract_candidate_snapshot(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, high-signal candidate schema (each fact appears once to keep the prompt small)."""
    raw_json = profile.get("raw_json") or {}
    sections = raw_json.get("sections") or {}

    projects_content = sections.get("projects", {}).get("content", "")
    exp_content = sections.get("experience", {}).get("content", "")

    seen = set()
    all_skills: List[str] = []
    for s in (profile.get("skills") or []):
        if isinstance(s, str) and s.strip():
            low = s.lower().strip()
            if low not in seen:
                seen.add(low)
                all_skills.append(low)

    return {
        "headline": profile.get("headline") or "Software Engineer",
        "experience_years": profile.get("experience_years") or 0.0,
        "is_fresher": raw_json.get("is_fresher", True),
        "skills": all_skills,
        "projects": _extract_projects_from_text(projects_content),
        "experience": _extract_experience_from_text(exp_content),
    }


def compress_job_card(job: Dict[str, Any], candidate_skills: Optional[List[str]] = None) -> Dict[str, Any]:
    """Extracts a strict, structured JD schema for a candidate job."""
    parsed = parse_job_description(
        description=job.get("description") or "",
        title=job.get("title") or "",
        company=job.get("company") or "",
        tagged_skills=job.get("skills") or [],
        required_years=job.get("required_years"),
    )
    req_skills = parsed["required_skills"]
    pref_skills = parsed["preferred_skills"]
    if not req_skills and pref_skills:
        # A posting whose only listed skills sit under a "Preferred skills" heading effectively requires them
        req_skills, pref_skills = pref_skills, []

    cand_set = {s.lower().strip() for s in (candidate_skills or []) if s}
    card: Dict[str, Any] = {
        "id": job["id"],
        "title": parsed["role_title"],
        "company": parsed["company"],
        "experience_level": parsed["experience_level"],
        "responsibilities": parsed["responsibilities"],
        "required_skills": req_skills,
        "preferred_skills": pref_skills,
    }
    if candidate_skills is not None:
        card["verified_candidate_matches"] = [s for s in req_skills if s.lower().strip() in cand_set]
        card["verified_candidate_gaps"] = [s for s in req_skills if s.lower().strip() not in cand_set]
    return card


SYSTEM_PROMPT = (
    "You are an objective technical hiring evaluator. Evaluate each job in `jobs` against `candidate`.\n"
    "RULES:\n"
    "1. GROUND TRUTH: `candidate.skills` is the verified skill list. Per job, `match` = required skills the candidate "
    "has and `gaps` = required skills the candidate lacks (pre-computed). NEVER say the candidate lacks a skill in "
    "`candidate.skills` or `match`. Your `gaps` and `deductions` may ONLY use items from that job's `gaps`.\n"
    "2. If a job has `skills_unknown: true`, it has no tagged skills: infer the needs from its title and `duties`, "
    "return empty `deductions`, and keep `gaps` to what the duties clearly require.\n"
    "3. CITATION: every `verdict` must cite one candidate project name (candidate.projects) or experience "
    "(candidate.experience) as evidence for fit or lack of fit.\n"
    "4. TONE: second person ('Your RailMind project shows...'). `verdict` is 1-2 sentences, max 25 words.\n"
    "5. Scores are integers 0-100: capability_fit (skills+projects vs core duties), tooling_fit (candidate tools vs "
    "required tools), seniority_fit (suitability for candidate level; use 65-85 for freshers on entry-level roles). "
    "`deductions`: at most 2 items, 2-5 points each, only for tools in that job's `gaps`.\n"
    "OUTPUT: valid JSON only, exactly one evaluation per job, `k` copied from the job:\n"
    '{"evaluations":[{"k":"1","verdict":"","strengths":[""],"gaps":[""],'
    '"deductions":[{"skill":"","points":3,"reason":""}],"capability_fit":0,"tooling_fit":0,"seniority_fit":0}]}'
)


def _prompt_job(key: str, card: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "k": key,
        "title": card["title"],
        "company": card["company"],
        "level": card["experience_level"],
    }
    duties = [d[:140] for d in (card.get("responsibilities") or [])[:3]]
    if duties:
        out["duties"] = duties
    if card.get("required_skills"):
        out["match"] = card.get("verified_candidate_matches") or []
        out["gaps"] = card.get("verified_candidate_gaps") or []
    else:
        out["skills_unknown"] = True
    if card.get("preferred_skills"):
        out["pref"] = card["preferred_skills"]
    return out


def build_rerank_prompt(candidate: Dict[str, Any], cards: List[Dict[str, Any]]) -> Tuple[str, str, Dict[str, str]]:
    """Returns (system_prompt, user_prompt, key_map) where key_map maps ordinal keys '1'..'N' -> job id.

    Ordinal keys replace long job ids in the prompt so the model can never mangle an id.
    """
    key_map: Dict[str, str] = {}
    jobs_payload = []
    for i, card in enumerate(cards, start=1):
        key = str(i)
        key_map[key] = card["id"]
        jobs_payload.append(_prompt_job(key, card))

    payload = {"candidate": candidate, "jobs": jobs_payload}
    user_prompt = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return SYSTEM_PROMPT, user_prompt, key_map


def calculate_blended_score(
    math_score: int,
    eval_item: Dict[str, Any],
    has_skills: bool = True,
    candidate_skills: Optional[List[str]] = None,
    job_skills: Optional[List[str]] = None,
) -> Tuple[int, int, Dict[str, Any]]:
    """Calculates deterministic blended score in Python to prevent LLM arithmetic errors.

    Formula:
        Score_llm_raw = 0.50 * capability_fit + 0.30 * tooling_fit + 0.20 * seniority_fit
        Score_llm = clamp(Score_llm_raw - sum(valid_deductions), 0, 100)
        Final Score = round(0.30 * Score_math + 0.70 * Score_llm)
    """
    capability_fit = float(eval_item.get("capability_fit") or eval_item.get("domain_fit") or eval_item.get("tech_stack_fit") or math_score)
    tooling_fit = float(eval_item.get("tooling_fit") or eval_item.get("tech_stack_fit") or math_score)
    seniority_fit = float(eval_item.get("seniority_fit") or math_score)

    raw_llm = 0.50 * capability_fit + 0.30 * tooling_fit + 0.20 * seniority_fit

    cand_set = {s.lower().strip() for s in (candidate_skills or []) if s}
    job_set = {s.lower().strip() for s in (job_skills or []) if s}

    deductions_list = eval_item.get("deductions") or []
    valid_deductions = []
    total_deductions = 0
    if isinstance(deductions_list, list) and has_skills:
        for d in deductions_list:
            if isinstance(d, dict) and "points" in d:
                skill_name = str(d.get("skill") or "").lower().strip()
                # Zero-Trust Guard 1: Candidate actually possesses this skill -> NEVER deduct points
                if cand_set and skill_name in cand_set:
                    continue
                # Zero-Trust Guard 2: Skill wasn't even in job requirements -> NEVER deduct points
                if job_set and skill_name and skill_name not in job_set:
                    continue
                try:
                    pts = int(d["points"])
                    total_deductions += pts
                    valid_deductions.append(d)
                except (ValueError, TypeError):
                    pass

    total_deductions = min(15, total_deductions)

    # If job has no verified skills, zero deductions are allowed
    if not has_skills:
        total_deductions = 0
        valid_deductions = []

    score_llm = max(0.0, min(100.0, raw_llm - total_deductions))
    final_score = int(round(0.30 * float(math_score) + 0.70 * score_llm))

    # Dual-Track Safeguard: If job had no verified skills, cap final score at 68
    if not has_skills:
        final_score = min(68, final_score)

    verdict = eval_item.get("verdict") or eval_item.get("reasoning") or (
        f"Candidate matched with verified stack alignment ({final_score}% overall fit)."
    )

    raw_strengths = eval_item.get("strengths") or eval_item.get("verified_strengths") or []
    raw_gaps = eval_item.get("gaps") or eval_item.get("missing_skills") or []

    # Clean gaps: Remove any skill candidate actually has
    filtered_gaps = [
        g for g in raw_gaps
        if isinstance(g, str) and (not cand_set or g.lower().strip() not in cand_set)
    ]
    filtered_strengths = [s for s in raw_strengths if isinstance(s, str)]

    breakdown = {
        "math_score": math_score,
        "llm_score": int(round(score_llm)),
        "verdict": verdict,
        "strengths": filtered_strengths,
        "gaps": filtered_gaps,
        "deductions": valid_deductions,
        "capability_fit": int(round(capability_fit)),
        "tooling_fit": int(round(tooling_fit)),
        "seniority_fit": int(round(seniority_fit)),
        "tech_stack_fit": int(round(tooling_fit)),
        "domain_fit": int(round(capability_fit)),
        "weights": {"math": 0.30, "llm": 0.70},
    }

    return final_score, int(round(score_llm)), breakdown


# --------------------------------------------------------------------------- helpers

def job_signature(job: Dict[str, Any]) -> str:
    """Fingerprint of the job facts the LLM judged; a changed signature invalidates its cached evaluation."""
    skills = "|".join(sorted(s.lower().strip() for s in (job.get("skills") or []) if s))
    raw = f"{job.get('title') or ''}#{skills}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _is_valid_evaluation(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    verdict = item.get("verdict")
    if not isinstance(verdict, str) or len(verdict.strip()) < 8:
        return False
    for field_name in ("capability_fit", "tooling_fit", "seniority_fit"):
        value = item.get(field_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if not 0 <= value <= 100:
            return False
    return True


def _sanitize_verdict(verdict: str, cand_skills: List[str]) -> str:
    """Rewrites any false claim that the candidate lacks a verified skill."""
    for s in cand_skills:
        if len(s) >= 2:
            pat = re.compile(rf"\b(?:lack|lacks|missing)\s+{re.escape(s)}\b", re.IGNORECASE)
            if pat.search(verdict):
                verdict = pat.sub(f"verified in {s}", verdict)
    return verdict


def _build_calibrated(job: Dict[str, Any], eval_item: Dict[str, Any], cand_skills: List[str], model: str) -> Dict[str, Any]:
    cand_set = {s.lower().strip() for s in cand_skills if s}
    final_score, llm_score, breakdown = calculate_blended_score(
        math_score=job["match_score"],
        eval_item=eval_item,
        has_skills=bool(job.get("skills")),
        candidate_skills=cand_skills,
        job_skills=job.get("skills") or [],
    )

    math_matched = job.get("matched_skills") or []
    eval_strengths = [
        s for s in (eval_item.get("strengths") or [])
        if isinstance(s, str) and (not cand_set or s.lower().strip() in cand_set)
    ]
    combined_strengths = sorted(set(math_matched + eval_strengths))

    eval_gaps = [
        g for g in (eval_item.get("gaps") or [])
        if isinstance(g, str) and (not cand_set or g.lower().strip() not in cand_set)
    ]
    math_missing = [
        g for g in (job.get("missing_skills") or [])
        if not cand_set or g.lower().strip() not in cand_set
    ]
    combined_gaps = sorted(set(eval_gaps or math_missing))

    verdict = _sanitize_verdict(str(eval_item.get("verdict") or breakdown.get("verdict")), cand_skills)
    breakdown["verdict"] = verdict

    return {
        **job,
        "match_score": final_score,
        "llm_score": llm_score,
        "matched_skills": combined_strengths,
        "inferred_skills": [],
        "missing_skills": combined_gaps,
        "explanation": verdict,
        "score_breakdown": breakdown,
        "calibrated_by": f"groq:{model}",
    }


def _sort_key(item: Dict[str, Any]):
    return (item["match_score"], item.get("date_posted") or "1970-01-01", item["id"])


def _as_pending(job: Dict[str, Any]) -> Dict[str, Any]:
    """Math-only row kept hidden until the LLM explains it."""
    return {
        **job,
        "llm_score": job["match_score"],
        "explanation": None,
        "score_breakdown": {"math_score": job["match_score"], "llm_pending": True},
        "calibrated_by": "pending",
    }


# ------------------------------------------------------------------------- main API

CacheGet = Callable[[str, str, List[str]], Awaitable[Dict[str, Tuple[str, Dict[str, Any]]]]]
CachePut = Callable[[str, str, Dict[str, Tuple[str, Dict[str, Any]]]], Awaitable[None]]


async def _default_cache_get(user_id: str, content_hash: str, job_ids: List[str]):
    from app.core.db import get_cached_evaluations
    return await asyncio.to_thread(get_cached_evaluations, user_id, content_hash, job_ids)


async def _default_cache_put(user_id: str, content_hash: str, items):
    from app.core.db import put_cached_evaluations
    await asyncio.to_thread(put_cached_evaluations, user_id, content_hash, items)


async def rerank_finalists_with_llm(
    candidate_profile: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    *,
    target: int = 10,
    initial: int = 12,
    user_id: Optional[str] = None,
    content_hash: Optional[str] = None,
    gateway: Optional[GroqGateway] = None,
    cache_get: Optional[CacheGet] = None,
    cache_put: Optional[CachePut] = None,
) -> RerankOutcome:
    """Explains up to `target` jobs from the ordered `candidates` pool. Never raises on Groq failures."""
    if not candidates:
        return RerankOutcome()

    gw = gateway or get_gateway()
    if not gw.has_keys:
        logger.error("No Groq API key configured; cannot explain matches.")
        return RerankOutcome(error="AI analysis is not configured (missing Groq API key).")

    cache_get = cache_get or _default_cache_get
    cache_put = cache_put or _default_cache_put

    candidate = extract_candidate_snapshot(candidate_profile)
    cand_skills = candidate.get("skills") or []
    want = min(target, len(candidates))
    first = candidates[:initial]
    reserve = candidates[initial:]

    # evaluations by job id (cached + fresh), with signature so we know what to persist
    evals: Dict[str, Dict[str, Any]] = {}
    fresh: Dict[str, Tuple[str, Dict[str, Any]]] = {}

    if user_id and content_hash:
        cached = await cache_get(user_id, content_hash, [j["id"] for j in candidates])
        by_id = {j["id"]: j for j in candidates}
        for job_id, (sig, ev) in cached.items():
            job = by_id.get(job_id)
            if job and sig == job_signature(job) and _is_valid_evaluation(ev):
                evals[job_id] = ev

    state = {"calls": 0}
    retry_after: Optional[float] = None

    async def _call(jobs: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        cards = [compress_job_card(j, cand_skills) for j in jobs]
        system_prompt, user_prompt, key_map = build_rerank_prompt(candidate, cards)
        result = await gw.chat_json(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            max_tokens=TOKENS_BASE + TOKENS_PER_JOB * len(jobs),
            purpose=f"rerank:{len(jobs)}",
        )
        out: Dict[str, Dict[str, Any]] = {}
        for item in result.data.get("evaluations") or []:
            if not isinstance(item, dict):
                continue
            job_id = key_map.get(str(item.get("k", item.get("job_id", ""))).strip())
            if job_id and job_id not in out and _is_valid_evaluation(item):
                out[job_id] = item
        missing = len(jobs) - len(out)
        if missing:
            logger.warning("rerank: %d/%d jobs came back without a valid evaluation", missing, len(jobs))
        return out

    async def _evaluate(todo: List[Dict[str, Any]], depth: int = 0) -> None:
        if not todo or state["calls"] >= MAX_LLM_CALLS_PER_RUN:
            return
        state["calls"] += 1
        try:
            got = await _call(todo)
        except LLMTruncated as exc:
            logger.warning("rerank: truncated/invalid output for %d jobs (%s)", len(todo), exc)
            if len(todo) > 1 and depth < 2:
                mid = (len(todo) + 1) // 2
                await _evaluate(todo[:mid], depth + 1)
                await _evaluate(todo[mid:], depth + 1)
            return
        except LLMBadResponse as exc:
            logger.error("rerank: unusable Groq response: %s", exc)
            return
        by_id = {j["id"]: j for j in todo}
        for job_id, ev in got.items():
            evals[job_id] = ev
            fresh[job_id] = (job_signature(by_id[job_id]), ev)

    try:
        await _evaluate([j for j in first if j["id"] not in evals])

        have = sum(1 for j in candidates if j["id"] in evals)
        if have < want and reserve:
            uncached = [j for j in reserve if j["id"] not in evals]
            n = min(len(uncached), (want - have) + 1, TOPUP_MAX_JOBS)
            await _evaluate(uncached[:n])
    except LLMUnavailable as exc:
        retry_after = exc.retry_after
        logger.warning("rerank: Groq unavailable (%s); retry in %.0fs", exc.reason, exc.retry_after)
    except GroqError as exc:
        logger.error("rerank: unexpected gateway error: %s", exc)

    if fresh and user_id and content_hash:
        try:
            await cache_put(user_id, content_hash, fresh)
        except Exception as exc:  # cache is best-effort
            logger.warning("rerank: could not persist evaluation cache: %s", exc)

    explained = [_build_calibrated(j, evals[j["id"]], cand_skills, gw.model) for j in candidates if j["id"] in evals]
    explained.sort(key=_sort_key, reverse=True)
    explained = explained[:target]

    pending: List[Dict[str, Any]] = []
    if len(explained) < want:
        pending = [_as_pending(j) for j in first if j["id"] not in evals]
        if retry_after is None:
            retry_after = DEFAULT_RETRY_AFTER

    return RerankOutcome(explained=explained, pending=pending, retry_after=retry_after, llm_calls=state["calls"])
