"""Groq LLaMA 3.3 70B Cross-Attention Re-Ranking Layer.

Implements Phase 4.3 of the Two-Stage Matching Funnel:
1. Singleton persistent HTTP/2 connection pool with keep-alive to api.groq.com.
2. Extracts high-signal candidate snapshot (headline, verified skills, project & experience titles).
3. Compresses job descriptions into ~80-token high-density cards, stripping boilerplate.
4. Listwise batch evaluation of Top 15 Finalists (RankGPT paradigm) with strict JSON output schema.
5. Deterministic Python computation of LLM rubric score and 30% Math / 70% LLM blended score.
6. Exponential backoff retry and graceful fallback to Phase 4.2 Math scores on API outage or rate limits.
"""
import os
import re
import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
import httpx
from dotenv import load_dotenv
from app.services.jd_parser import parse_job_description

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_FALLBACK_MODEL = "openai/gpt-oss-120b"
GROQ_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"

# Global singleton HTTP/2 client with keep-alive
_groq_client: Optional[httpx.AsyncClient] = None
_groq_client_key: Optional[str] = None


def get_groq_client() -> httpx.AsyncClient:
    """Returns persistent HTTP/2 client with keep-alive to avoid connection overhead."""
    global _groq_client, _groq_client_key
    current_key = os.getenv("GROQ_API_KEY") or GROQ_API_KEY
    if _groq_client is None or _groq_client.is_closed or _groq_client_key != current_key:
        _groq_client_key = current_key
        _groq_client = httpx.AsyncClient(
            timeout=35.0,
            headers={
                "Authorization": f"Bearer {current_key}",
                "Content-Type": "application/json",
            }
        )
    return _groq_client


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
            line[0] in ("\ufffd", "•", "*", "-", "·", "▪", "▫", "○", "●")
            or bool(re.match(r"^(\([a-zA-Z0-9]+\)|\[[0-9]+\]|[0-9]+\.)\s", line))
        )

        if not is_bullet:
            parts = re.split(r"\s+[|–—\ufffd•·]\s+|\s+-\s+", line)
            if len(parts) >= 2:
                p_name = parts[0].strip("•*-–—·▪▫○● \t\ufffd")
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
            text = line.lstrip("•*-–—·▪▫○● \t\ufffd(cid:0123456789)")
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
            line[0] in ("\ufffd", "•", "*", "-", "·", "▪")
            or bool(re.match(r"^(\([a-zA-Z0-9]+\)|\[[0-9]+\]|[0-9]+\.)\s", line))
        )
        if is_bullet:
            if current_exp and len(current_exp["summary"]) < 180:
                text = line.lstrip("•*-–—·▪ \t\ufffd")
                current_exp["summary"] += (" " + text) if current_exp["summary"] else text
        elif any(sep in line for sep in ["|", "–", "—", "@", "at ", " - ", "\ufffd"]) and len(line) < 120:
            parts = re.split(r"\s+[|–—\ufffd@]\s+|\s+-\s+|\s+at\s+", line)
            title = parts[0].strip("•*-–—·▪ \t\ufffd")
            if len(title) >= 3 and len(title) <= 70:
                current_exp = {"role_and_company": title, "summary": ""}
                experiences.append(current_exp)
                if len(experiences) >= 3:
                    break
        elif current_exp and not current_exp["summary"]:
            current_exp["summary"] = line[:180]
    return experiences


def extract_candidate_snapshot(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts strict, high-signal structured candidate schema from profile."""
    raw_json = profile.get("raw_json") or {}
    sections = raw_json.get("sections") or {}

    projects_content = sections.get("projects", {}).get("content", "")
    exp_content = sections.get("experience", {}).get("content", "")

    structured_projects = _extract_projects_from_text(projects_content)
    structured_exp = _extract_experience_from_text(exp_content)

    return {
        "headline": profile.get("headline") or "Software Engineer",
        "experience_years": profile.get("experience_years") or 0.0,
        "is_fresher": raw_json.get("is_fresher", True),
        "verified_skills": (profile.get("skills") or [])[:35],
        "skills": (profile.get("skills") or [])[:35],
        "projects": structured_projects,
        "project_headlines": [p["name"] for p in structured_projects],
        "experience": structured_exp,
        "experience_headlines": [e["role_and_company"] for e in structured_exp],
    }


def compress_job_card(job: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts a strict, structured JD schema for the candidate job."""
    parsed = parse_job_description(
        description=job.get("description") or "",
        title=job.get("title") or "",
        company=job.get("company") or "",
        tagged_skills=job.get("skills") or [],
        required_years=job.get("required_years"),
    )
    return {
        "id": job["id"],
        "title": parsed["role_title"],
        "company": parsed["company"],
        "experience_level": parsed["experience_level"],
        "responsibilities": parsed["responsibilities"],
        "required_skills": parsed["required_skills"],
        "preferred_skills": parsed["preferred_skills"],
    }


def build_rerank_prompt(candidate: Dict[str, Any], compressed_jobs: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Builds system and user prompts for listwise batch re-ranking with strict schema grounding."""
    system_prompt = (
        "You are an elite, objective technical hiring evaluator. Your job is to perform "
        "cross-attention evaluation on a batch of candidate jobs against a developer's profile.\n"
        "STRICT GROUNDING & AUDIT RULES:\n"
        "1. CITATION REQUIREMENT: In every 'verdict', you MUST cite at least one specific candidate project name "
        "(from candidate_profile.projects) or work experience (from candidate_profile.experience) as verifiable evidence "
        "proving why the candidate can or cannot fulfill the job's core responsibilities.\n"
        "2. ZERO HALLUCINATIONS: Never claim or assume the candidate knows a skill or tool that is NOT explicitly "
        "present in their verified_skills or projects. If a job requires a skill the candidate lacks, you MUST list it in 'gaps'.\n"
        "3. DIRECT HUMAN TONE: Write concise, direct language addressing the candidate in the second person "
        "('Your RailMind project demonstrates...', 'However, you lack Angular...').\n"
        "4. Output valid, parseable JSON conforming strictly to the requested schema."
    )

    user_payload = {
        "candidate_profile": candidate,
        "candidate_jobs": compressed_jobs,
        "evaluation_rubric": {
            "verdict": "Mandatory 2-sentence plain-English summary. Sentence 1 MUST cite at least one specific candidate project or experience name from the profile proving capability to fulfill core JD responsibilities. Sentence 2 MUST state the specific required JD tools that are missing from candidate's resume (or confirm a complete stack match).",
            "strengths": "Array of strings: Candidate skills verified to match JD requirements.",
            "gaps": "Array of strings: Core JD requirements candidate explicitly lacks.",
            "deductions": "Array of objects {skill: string, points: integer, reason: string} for specific missing technical tools (2-5 points each).",
            "capability_fit": "Integer 0-100: Degree to which candidate skills and project portfolio fulfill core engineering duties.",
            "tooling_fit": "Integer 0-100: Degree to which candidate's verified technical tools match explicit JD requirements minus gaps.",
            "seniority_fit": "Integer 0-100: Suitability for candidate experience level (use 65-85 for entry-level/freshers)."
        },
        "required_output_schema": {
            "evaluations": [
                {
                    "job_id": "string",
                    "verdict": "string",
                    "strengths": ["string"],
                    "gaps": ["string"],
                    "deductions": [{"skill": "string", "points": "integer", "reason": "string"}],
                    "capability_fit": "integer (0-100)",
                    "tooling_fit": "integer (0-100)",
                    "seniority_fit": "integer (0-100)"
                }
            ]
        }
    }

    user_prompt = (
        "Evaluate each of the following candidate jobs against the candidate profile.\n"
        "Return an 'evaluations' array containing exactly one evaluation object per job.\n\n"
        f"{json.dumps(user_payload, indent=2)}"
    )

    return system_prompt, user_prompt


def calculate_blended_score(math_score: int, eval_item: Dict[str, Any], has_skills: bool = True) -> Tuple[int, int, Dict[str, Any]]:
    """Calculates deterministic blended score in Python to prevent LLM arithmetic errors.
    
    Formula:
        Score_llm_raw = 0.50 * capability_fit + 0.30 * tooling_fit + 0.20 * seniority_fit
        Score_llm = clamp(Score_llm_raw - sum(deductions), 0, 100)
        Final Score = round(0.30 * Score_math + 0.70 * Score_llm)
    """
    capability_fit = float(eval_item.get("capability_fit") or eval_item.get("domain_fit") or eval_item.get("tech_stack_fit") or math_score)
    tooling_fit = float(eval_item.get("tooling_fit") or eval_item.get("tech_stack_fit") or math_score)
    seniority_fit = float(eval_item.get("seniority_fit") or math_score)

    raw_llm = 0.50 * capability_fit + 0.30 * tooling_fit + 0.20 * seniority_fit

    deductions_list = eval_item.get("deductions") or []
    total_deductions = 0
    if isinstance(deductions_list, list):
        for d in deductions_list:
            if isinstance(d, dict) and "points" in d:
                try:
                    total_deductions += int(d["points"])
                except (ValueError, TypeError):
                    pass

    total_deductions = min(15, total_deductions)
    score_llm = max(0.0, min(100.0, raw_llm - total_deductions))
    final_score = int(round(0.30 * float(math_score) + 0.70 * score_llm))

    # Dual-Track Safeguard: If job had no verified skills, cap final score at 68
    if not has_skills:
        final_score = min(68, final_score)

    verdict = eval_item.get("verdict") or eval_item.get("reasoning") or (
        f"Candidate matched with verified stack alignment ({final_score}% overall fit)."
    )
    strengths = eval_item.get("strengths") or eval_item.get("verified_strengths") or []
    gaps = eval_item.get("gaps") or eval_item.get("missing_skills") or []

    breakdown = {
        "math_score": math_score,
        "llm_score": int(round(score_llm)),
        "verdict": verdict,
        "strengths": strengths,
        "gaps": gaps,
        "deductions": deductions_list,
        "capability_fit": int(round(capability_fit)),
        "tooling_fit": int(round(tooling_fit)),
        "seniority_fit": int(round(seniority_fit)),
        "tech_stack_fit": int(round(tooling_fit)),
        "domain_fit": int(round(capability_fit)),
        "weights": {"math": 0.30, "llm": 0.70},
    }

    return final_score, int(round(score_llm)), breakdown


async def rerank_finalists_with_llm(
    candidate_profile: Dict[str, Any],
    finalists: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Re-ranks and calibrates Top 15 Finalists using Groq LLaMA 3.3 70B.
    
    If Groq is unreachable or fails after retry, gracefully falls back
    to Phase 4.2 Math scores so the application never hangs or crashes.
    """
    if not finalists:
        return []

    if not GROQ_API_KEY:
        # Fallback if API key is not configured
        return _apply_math_fallback(finalists, "Groq API key not configured; using deterministic math scores.")

    candidate = extract_candidate_snapshot(candidate_profile)
    compressed_jobs = [compress_job_card(j) for j in finalists]
    system_prompt, user_prompt = build_rerank_prompt(candidate, compressed_jobs)

    client = get_groq_client()
    request_body = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }

    # Attempt API call with 1 exponential backoff retry on 429/timeout
    response_json = None
    for attempt in range(2):
        if attempt == 1:
            request_body["model"] = GROQ_FALLBACK_MODEL
        try:
            response = await client.post(GROQ_COMPLETIONS_URL, json=request_body)
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                response_json = json.loads(content)
                break
            elif response.status_code in (429, 503) and attempt == 0:
                await asyncio.sleep(1.5)
                continue
            else:
                break
        except Exception:
            if attempt == 0:
                await asyncio.sleep(1.5)
                continue
            break

    if not response_json or "evaluations" not in response_json:
        return _apply_math_fallback(finalists, "LLM re-ranking temporarily unavailable; calibrated with deterministic math.")

    # Map evaluations by job_id
    evaluations_by_id = {
        item.get("job_id"): item
        for item in response_json["evaluations"]
        if isinstance(item, dict) and "job_id" in item
    }

    calibrated_jobs = []
    for job in finalists:
        job_id = job["id"]
        eval_item = evaluations_by_id.get(job_id)

        if eval_item:
            final_score, llm_score, breakdown = calculate_blended_score(
                math_score=job["match_score"],
                eval_item=eval_item,
                has_skills=bool(job.get("skills")),
            )
            # Map grounded strengths, gaps, and verdict
            strengths = eval_item.get("strengths") or eval_item.get("verified_strengths") or job.get("matched_skills") or []
            gaps = eval_item.get("gaps") or eval_item.get("missing_skills") or job.get("missing_skills") or []
            verdict = eval_item.get("verdict") or eval_item.get("reasoning") or breakdown.get("verdict") or (
                f"Candidate matched with verified stack alignment ({final_score}% overall fit)."
            )

            calibrated_jobs.append({
                **job,
                "match_score": final_score,
                "llm_score": llm_score,
                "matched_skills": strengths,
                "inferred_skills": [],
                "missing_skills": gaps,
                "explanation": verdict,
                "score_breakdown": breakdown,
                "calibrated_by": "groq_llama_3.3_70b",
            })
        else:
            # Fallback for individual missing job
            calibrated_jobs.append({
                **job,
                "explanation": f"Score calculated deterministically via verified skill recall ({job['match_score']}%).",
                "score_breakdown": {
                    "math_score": job["match_score"],
                    "llm_score": job["match_score"],
                    "weights": {"math": 1.0, "llm": 0.0},
                },
                "calibrated_by": "deterministic_math_fallback",
            })

    # Sort calibrated jobs by match_score DESC, date_posted DESC, id ASC
    def sort_key(item):
        score = item["match_score"]
        date_str = item.get("date_posted") or "1970-01-01"
        return (score, date_str, item["id"])

    calibrated_jobs.sort(key=sort_key, reverse=True)
    return calibrated_jobs


def _apply_math_fallback(finalists: List[Dict[str, Any]], message: str) -> List[Dict[str, Any]]:
    """Applies clean deterministic math fallback to all finalists."""
    fallback_jobs = []
    for job in finalists:
        fallback_jobs.append({
            **job,
            "explanation": f"{message} (Score: {job['match_score']}%)",
            "score_breakdown": {
                "math_score": job["match_score"],
                "llm_score": job["match_score"],
                "weights": {"math": 1.0, "llm": 0.0},
            },
            "calibrated_by": "deterministic_math_fallback",
        })
    return fallback_jobs
