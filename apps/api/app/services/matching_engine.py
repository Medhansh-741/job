"""Deterministic Hybrid Matching Engine & Ranking Service.

Implements Step 4 specifications:
1. Stage 1: Hard filtering (Seniority, Fresher <= 1 yr or NULL, Region expansion).
2. Stage 2: Dense HNSW vector retrieval (Top 100 via match_jobs, ef_search = 150).
3. Stage 3: Hybrid mathematical scoring:
   - S_norm = Min-Max scaled semantic similarity [0.30, 0.75] -> [0.0, 1.0]
   - C_skill = Job Skill Recall (|Candidate ∩ Job| / |Job|)
   - B_title = +5% Title Alignment Boost
   - Base Score = 0.40 * S_norm + 0.60 * C_skill + B_title
   - D_skill = Non-Linear Reality Dampener (0.35x knockout penalty for 0% skill overlap)
   - Final Score = round(clamp(Base Score * D_skill * 100, 0, 100))
4. Stage 4: Automated Adzuna/Jooble live fallback trigger when high-confidence matches < 10.
5. Stage 5: Top 25 sorting and atomic public.matches database persistence.
"""
import os
import re
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Set
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from dotenv import load_dotenv

from app.core.db import get_candidate_profile, get_db
from app.core.task_tracker import task_tracker
from app.services.live_fallback import execute_live_fallback_search
from app.services.llm_reranker import rerank_finalists_with_llm

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in .env")

# Recognized title tokens for title alignment boost
ROLE_TOKENS = [
    "frontend", "front-end", "front end", "backend", "back-end", "back end",
    "fullstack", "full-stack", "full stack", "ai", "ml", "machine learning",
    "deep learning", "nlp", "computer vision", "devops", "sre", "cloud",
    "data engineer", "data scientist", "data analyst", "mobile", "ios", "android",
    "qa", "sdet", "test engineer", "security", "systems", "platform"
]


def normalize_semantic_similarity(raw_sim: float) -> float:
    """Clamps and normalizes raw cosine similarity from [0.30, 0.75] to [0.0, 1.0]."""
    clamped = max(0.30, min(0.75, raw_sim))
    return (clamped - 0.30) / (0.75 - 0.30)


def calculate_skill_coverage(
    candidate_skills: List[str],
    job_skills: Optional[List[str]],
) -> Tuple[Optional[float], List[str], List[str]]:
    """Calculates Job Skill Coverage using a Bayesian Denominator Floor.
    
    Formula:
        C_skill = |Candidate Skills ∩ Job Skills| / max(|Job Skills|, 3)
        
    Guarantees that a terse JD with only 1 extracted skill cannot yield
    100% recall and artificially inflate a candidate's match score.
    If job has no tagged skills, returns None to trigger dynamic semantic fallback.
    """
    if not job_skills:
        return None, [], []

    c_set = {s.lower().strip() for s in candidate_skills}
    j_set = {s.lower().strip() for s in job_skills}

    if not j_set:
        return None, [], []

    matched = sorted(list(c_set & j_set))
    missing = sorted(list(j_set - c_set))
    
    # Bayesian Denominator Floor: minimum expectation of 3 skills for technical roles
    denominator = max(len(j_set), 3)
    coverage = len(matched) / denominator
    return coverage, matched, missing


def calculate_title_boost(
    preferred_roles: List[str],
    headline: Optional[str],
    job_title: str,
    normalized_title: str,
) -> float:
    """Returns +0.05 (+5%) bonus if candidate role tokens match job title."""
    title_text = f"{job_title.lower()} {normalized_title.lower()}"
    roles = [r.lower() for r in preferred_roles]
    if headline:
        roles.append(headline.lower())

    for r in roles:
        for token in ROLE_TOKENS:
            if token in r and token in title_text:
                return 0.05
    return 0.0


def calculate_reality_dampener(
    coverage: Optional[float],
    job_skills_count: int,
) -> float:
    """Implements non-linear reality dampener to prevent semantic illusions."""
    if coverage is None or job_skills_count <= 1:
        return 1.0

    if coverage >= 0.50:
        return 1.0
    elif coverage >= 0.25:
        return 0.85
    elif coverage > 0.0:
        return 0.60
    else:
        # Hard Knockout Penalty: Candidate possesses 0 of the required technologies
        return 0.35


def score_job(
    raw_sim: float,
    candidate_skills: List[str],
    job_skills: Optional[List[str]],
    preferred_roles: List[str],
    headline: Optional[str],
    job_title: str,
    normalized_title: str,
) -> Dict[str, Any]:
    """Computes Phase 4.2 deterministic math score with Bayesian Denominator Floor."""
    s_norm = normalize_semantic_similarity(raw_sim)
    cov, matched, missing = calculate_skill_coverage(candidate_skills, job_skills)
    job_skills_len = len(job_skills) if job_skills else 0
    title_boost = calculate_title_boost(preferred_roles, headline, job_title, normalized_title)

    if cov is None or job_skills_len == 0:
        # Dual-Track Safeguard: Job has 0 tagged skills.
        # Score based purely on semantic similarity + title boost, capped at 65 max.
        base_score = 0.70 * s_norm + title_boost
        dampener = 1.0
        final_score = int(round(min(65.0, max(0.0, base_score * 100.0))))
        effective_cov = 0.0
    else:
        # Standard Track: Job has explicit technical skills.
        effective_cov = cov
        base_score = 0.40 * s_norm + 0.60 * effective_cov + title_boost
        dampener = calculate_reality_dampener(cov, job_skills_len)
        final_score = int(round(min(100.0, max(0.0, base_score * dampener * 100.0))))

    return {
        "match_score": final_score,
        "matched_skills": matched,
        "missing_skills": missing,
        "raw_similarity": round(raw_sim, 4),
        "normalized_semantic": round(s_norm, 4),
        "skill_coverage": round(effective_cov, 4),
        "title_boost": round(title_boost, 4),
        "reality_dampener": dampener,
        "denominator_floor_applied": (job_skills_len < 3 and job_skills_len > 0),
    }


async def execute_matching_funnel(
    user_id: str,
    target_region: str = "india",
    limit: int = 15,
) -> Dict[str, Any]:
    """Orchestrates the entire 5-stage matching funnel for a candidate."""
    # 1. Fetch candidate profile
    profile = get_candidate_profile(user_id)
    if not profile:
        return {
            "matches": [],
            "total_evaluated": 0,
            "live_fallback_triggered": False,
            "message": "Candidate profile not found. Please upload a resume first.",
        }

    candidate_skills = profile.get("skills") or []
    if not candidate_skills:
        return {
            "matches": [],
            "total_evaluated": 0,
            "live_fallback_triggered": False,
            "message": "No technical skills detected in profile. Please add skills or upload a technical resume.",
        }

    embedding = profile.get("embedding")
    if not embedding:
        return {
            "matches": [],
            "total_evaluated": 0,
            "live_fallback_triggered": False,
            "message": "Resume embedding is being generated. Please retry in a few seconds.",
        }

    raw_json = profile.get("raw_json") or {}
    is_fresher = raw_json.get("is_fresher", True)
    full_time_years = profile.get("experience_years") or 0.0
    preferred_roles = profile.get("preferred_roles") or []
    headline = profile.get("headline")

    task_tracker.set_progress(
        user_id,
        status="processing",
        progress=55,
        step_label="Scanning 1,000+ jobs via vector search & regional filters...",
    )

    # 2. Stage 1 & Stage 2: Query PostgreSQL match_jobs stored procedure (K = 100)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, title, company, normalized_company, normalized_title,
                       location, region, description, source_url, date_posted,
                       required_years, skills, similarity
                FROM match_jobs(
                    query_embedding := %s::vector,
                    match_threshold := 0.20,
                    match_count := 100,
                    filter_region := %s,
                    filter_max_years := %s,
                    is_fresher_candidate := %s
                );
                """,
                (
                    str(embedding),
                    target_region,
                    int(full_time_years) if full_time_years else None,
                    is_fresher,
                )
            )
            catalog_rows = cur.fetchall()

    # 3. Stage 3: Deterministic Hybrid Scoring & Reality Dampening
    task_tracker.set_progress(
        user_id,
        status="processing",
        progress=70,
        step_label="Evaluating skill coverage & applying seniority filters...",
    )
    scored_jobs = []
    for r in catalog_rows:
        audit = score_job(
            raw_sim=r["similarity"],
            candidate_skills=candidate_skills,
            job_skills=r["skills"],
            preferred_roles=preferred_roles,
            headline=headline,
            job_title=r["title"],
            normalized_title=r.get("normalized_title") or "",
        )
        scored_jobs.append({
            "id": r["id"],
            "title": r["title"],
            "company": r["company"],
            "location": r["location"],
            "region": r["region"],
            "description": r["description"],
            "source_url": r["source_url"],
            "date_posted": r["date_posted"].isoformat() if r.get("date_posted") else None,
            "required_years": r["required_years"],
            "skills": r["skills"] or [],
            **audit,
        })

    # 4. Stage 4: Live Fallback Check (Adzuna / Jooble)
    strong_matches_count = sum(1 for j in scored_jobs if j["match_score"] >= 60)
    live_fallback_triggered = False

    if strong_matches_count < 10 and preferred_roles:
        live_fallback_triggered = True
        role_to_query = preferred_roles[0]
        live_jobs = await execute_live_fallback_search(role_to_query, region=target_region)

        # Score net-new live jobs
        for lj in live_jobs:
            # Avoid duplicate ids
            if any(existing["id"] == lj["id"] for existing in scored_jobs):
                continue

            audit = score_job(
                raw_sim=lj.get("similarity", 0.65),
                candidate_skills=candidate_skills,
                job_skills=lj["skills"],
                preferred_roles=preferred_roles,
                headline=headline,
                job_title=lj["title"],
                normalized_title=lj.get("normalized_title") or "",
            )
            scored_jobs.append({
                "id": lj["id"],
                "title": lj["title"],
                "company": lj["company"],
                "location": lj["location"],
                "region": lj["region"],
                "description": lj["description"],
                "source_url": lj["source_url"],
                "date_posted": lj.get("date_posted"),
                "required_years": lj["required_years"],
                "skills": lj["skills"] or [],
                **audit,
            })

    # 5. Stage 5: Deterministic Sort & Diversity-Constrained Truncation (Top 15 Finalists)
    # Sort order: match_score DESC, date_posted DESC, id ASC
    def sort_key(item):
        score = item["match_score"]
        date_str = item.get("date_posted") or "1970-01-01"
        return (score, date_str, item["id"])

    scored_jobs.sort(key=sort_key, reverse=True)

    # Diversity & Role-Dedup Invariant:
    # 1. At most 2 postings per company to prevent feed cannibalization.
    # 2. Strict (company, normalized_title) uniqueness so duplicate aggregator postings are skipped.
    company_counts: Dict[str, int] = {}
    seen_roles: Set[Tuple[str, str]] = set()
    top_finalists: List[Dict[str, Any]] = []

    for job in scored_jobs:
        comp_key = (job.get("normalized_company") or job.get("company") or "unknown").lower().strip()
        title_key = (job.get("normalized_title") or job.get("title") or "").lower().strip()
        role_key = (comp_key, title_key)

        if role_key in seen_roles:
            continue

        current_count = company_counts.get(comp_key, 0)
        if current_count >= 2:
            continue

        seen_roles.add(role_key)
        company_counts[comp_key] = current_count + 1
        top_finalists.append(job)
        if len(top_finalists) >= limit:
            break

    # 6. Stage 4.3: Groq LLM Cross-Attention Re-Ranking & Calibration
    task_tracker.set_progress(
        user_id,
        status="processing",
        progress=82,
        step_label="Cross-attention LLM evaluating top 15 finalists...",
    )
    calibrated_matches = await rerank_finalists_with_llm(
        candidate_profile=profile,
        finalists=top_finalists,
    )

    # 7. Database Persistence to public.matches (Atomic Replace)
    task_tracker.set_progress(
        user_id,
        status="processing",
        progress=95,
        step_label="Calibrating scores and saving matches...",
    )
    if calibrated_matches:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Atomically purge old matches for this user before saving calibrated finalists
                cur.execute("DELETE FROM public.matches WHERE user_id = %s;", (user_id,))
                insert_rows = [
                    (
                        user_id,
                        m["id"],
                        m["match_score"],
                        m["matched_skills"],
                        m["missing_skills"],
                        m.get("explanation"),
                        json.dumps(m.get("score_breakdown") or {}),
                    )
                    for m in calibrated_matches
                ]
                insert_sql = """
                INSERT INTO public.matches (
                    user_id, job_id, match_score, matched_skills, missing_skills, explanation, score_breakdown
                ) VALUES %s
                ON CONFLICT (user_id, job_id) DO UPDATE SET
                    match_score = EXCLUDED.match_score,
                    matched_skills = EXCLUDED.matched_skills,
                    missing_skills = EXCLUDED.missing_skills,
                    explanation = EXCLUDED.explanation,
                    score_breakdown = EXCLUDED.score_breakdown,
                    created_at = now();
                """
                execute_values(cur, insert_sql, insert_rows)
            conn.commit()

    task_tracker.mark_completed(user_id, count=len(calibrated_matches))

    return {
        "matches": calibrated_matches,
        "total_evaluated": len(scored_jobs),
        "live_fallback_triggered": live_fallback_triggered,
        "strong_matches_count": sum(1 for m in calibrated_matches if m["match_score"] >= 60),
    }


def get_persisted_matches(user_id: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Fast-path retrieval of persisted matches directly from public.matches with public.jobs metadata (sub-2ms)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT j.id, j.title, j.company, j.location, j.region, j.description,
                       j.source_url, j.date_posted, j.required_years, j.skills,
                       m.match_score, m.matched_skills, m.missing_skills,
                       m.explanation, m.score_breakdown
                FROM public.matches m
                JOIN public.jobs j ON m.job_id = j.id
                WHERE m.user_id = %s
                ORDER BY m.match_score DESC
                LIMIT %s;
                """,
                (user_id, limit)
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "company": r["company"],
            "location": r["location"],
            "region": r["region"],
            "description": r["description"],
            "source_url": r["source_url"],
            "date_posted": r["date_posted"].isoformat() if r.get("date_posted") else None,
            "required_years": r["required_years"],
            "skills": r["skills"] or [],
            "match_score": r["match_score"],
            "matched_skills": r["matched_skills"] or [],
            "inferred_skills": (r.get("score_breakdown") or {}).get("inferred_skills") or [],
            "missing_skills": r["missing_skills"] or [],
            "explanation": r.get("explanation"),
            "score_breakdown": r.get("score_breakdown") or {},
        }
        for r in rows
    ]

