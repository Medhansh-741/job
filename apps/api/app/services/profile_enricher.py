"""Systematic Candidate Profile Understanding & Role Inference via Groq.

Extracts holistic professional headline, primary engineering domain, and target roles
from candidate resume markdown and verified skills. Runs once at upload time (cached in DB).
"""
import os
import json
from typing import List, Dict, Any, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL = "openai/gpt-oss-20b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

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


async def enrich_candidate_profile(markdown: str, skills: List[str]) -> Dict[str, Any]:
    """Infers headline, primary domain, and preferred roles using Groq."""
    if not GROQ_API_KEY or not markdown:
        return {
            "headline": "Software Engineer",
            "primary_domain": "software_engineering",
            "preferred_roles": ["Software Engineer", "Full-Stack Developer"],
        }

    prompt = PROMPT_TEMPLATE.format(
        markdown=markdown[:3000],
        skills=", ".join(skills[:30])
    )

    try:
        from app.services.llm_reranker import get_groq_client
        client = get_groq_client()
        resp = await client.post(
            GROQ_URL,
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            timeout=10.0,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            headline = parsed.get("headline") or "Software Engineer"
            primary_domain = parsed.get("primary_domain") or "software_engineering"
            preferred_roles = parsed.get("preferred_roles") or ["Software Engineer", "Full-Stack Developer"]
            return {
                "headline": headline.strip(),
                "primary_domain": primary_domain.strip(),
                "preferred_roles": [r.strip() for r in preferred_roles if isinstance(r, str)],
            }
    except Exception as e:
        print(f"[Profile Enricher] Error inferring profile with LLM: {e}")

    return {
        "headline": "Software Engineer",
        "primary_domain": "software_engineering",
        "preferred_roles": ["Software Engineer", "Full-Stack Developer"],
    }
