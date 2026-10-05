"""Systematic Candidate Profile Understanding & Role Inference via Groq.

Extracts holistic professional headline, primary engineering domain, and target roles
from candidate resume markdown and verified skills. Runs only for new/changed resumes
(the upload flow reuses the stored result when the resume text is unchanged).
All traffic goes through the shared Groq gateway (key pool + rate limiter).
"""
import logging
from typing import List, Dict, Any

from app.services.groq_gateway import GroqError, get_gateway

logger = logging.getLogger("profile_enricher")

PROMPT_TEMPLATE = """Analyze this candidate's resume markdown and verified skills to determine their professional identity and target engineering roles.
Return ONLY a valid JSON object matching this schema:
{{
  "headline": "Concise professional headline (e.g. 'Frontend & Full-Stack Engineer (AI/ML & UI/UX)')",
  "primary_domain": "One of: 'software_engineering', 'frontend', 'fullstack', 'backend', 'ai_ml', 'data_engineering', 'ui_ux_design'",
  "preferred_roles": ["Role 1", "Role 2", "Role 3", "Role 4"]
}}

Candidate Resume:
{markdown}

Verified Technical Skills:
{skills}"""

DEFAULT_PROFILE = {
    "headline": "Software Engineer",
    "primary_domain": "software_engineering",
    "preferred_roles": ["Software Engineer", "Full-Stack Developer"],
}


def _default() -> Dict[str, Any]:
    return {**DEFAULT_PROFILE, "preferred_roles": list(DEFAULT_PROFILE["preferred_roles"]), "source": "default"}


async def enrich_candidate_profile(markdown: str, skills: List[str]) -> Dict[str, Any]:
    """Infers headline, primary domain, and preferred roles using Groq.

    The result carries `source`: "llm" when Groq produced it, "default" for the generic fallback,
    so callers never cache a fallback as if it were a real inference.
    """
    gw = get_gateway()
    if not gw.has_keys or not markdown:
        return _default()

    prompt = PROMPT_TEMPLATE.format(markdown=markdown[:3000], skills=", ".join(skills))

    try:
        result = await gw.chat_json(
            [{"role": "user", "content": prompt}],
            max_tokens=400,
            purpose="enrich_profile",
            max_wait=5.0,
        )
    except GroqError as exc:
        logger.warning("profile enrichment skipped: %s", exc)
        return _default()

    parsed = result.data
    headline = parsed.get("headline")
    roles = [r.strip() for r in (parsed.get("preferred_roles") or []) if isinstance(r, str) and r.strip()]
    if not isinstance(headline, str) or not headline.strip() or not roles:
        return _default()
    return {
        "headline": headline.strip(),
        "primary_domain": (parsed.get("primary_domain") or "software_engineering").strip(),
        "preferred_roles": roles,
        "source": "llm",
    }
