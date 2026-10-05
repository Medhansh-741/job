"""Deterministic Job Description (JD) Section Parser & Schema Extractor.

Parses unstructured job description text into a clean, typed ATS/Schema.org-compliant schema:
- responsibilities (core day-to-day engineering duties)
- required_skills (must-have technical tools)
- preferred_skills (nice-to-have / bonus tools)
- experience_level (seniority & scope)
- education (degree background if specified)
"""
import re
from typing import Dict, List, Any, Optional, Set
from app.services.catalog_normalizer import SKILLS_TAXONOMY, extract_skills, YEARS_PATTERN

# Section heading patterns common across Greenhouse, Lever, Ashby, and ATS boards
RESPONSIBILITIES_HEADINGS = re.compile(
    r"\b(responsibilities|what\s+you(?:'ll|\s+will)\s+do|the\s+role|key\s+responsibilities|day\s+to\s+day|what\s+you(?:'re|\s+are)\s+doing|about\s+the\s+role|core\s+duties)\b",
    re.IGNORECASE,
)

REQUIREMENTS_HEADINGS = re.compile(
    r"\b(requirements|what\s+we(?:'re|\s+are)\s+looking\s+for|qualifications|basic\s+qualifications|what\s+you\s+need|must\s+have|skills\s+(?:&|and)\s+experience|minimum\s+qualifications)\b",
    re.IGNORECASE,
)

PREFERRED_HEADINGS = re.compile(
    r"\b(preferred\s+qualifications|nice\s+to\s+have|bonus|bonus\s+points|good\s+to\s+have|plus|preferred\s+skills|what\s+sets\s+you\s+apart)\b",
    re.IGNORECASE,
)

EDUCATION_PATTERN = re.compile(
    r"\b(bachelor(?:'s)?|b\.?s\.?|b\.?tech|master(?:'s)?|m\.?s\.?|m\.?tech|computer\s+science|engineering\s+degree)\b",
    re.IGNORECASE,
)

# Common action verbs that signal engineering duties in sentences
DUTY_ACTION_VERBS = re.compile(
    r"^(build|building|develop|developing|design|designing|implement|implementing|maintain|maintaining|create|creating|collaborate|collaborating|work|working|lead|architect|optimize|optimizing|test|testing|deploy|deploying|integrate|integrating|support|supporting)\b",
    re.IGNORECASE,
)


def _split_into_lines_and_sentences(text: str) -> List[str]:
    """Splits description by newlines, bullet characters, or sentence breaks."""
    raw_lines = re.split(r"[\n\r•\-\*–—]+", text)
    cleaned = []
    for l in raw_lines:
        line_str = l.strip()
        if len(line_str) > 10:
            cleaned.append(line_str)
    return cleaned


def parse_job_description(
    description: str,
    title: str = "",
    company: str = "",
    tagged_skills: Optional[List[str]] = None,
    required_years: Optional[int] = None,
) -> Dict[str, Any]:
    """Extracts a structured schema from raw JD text in < 1ms."""
    desc = description or ""
    all_tagged_skills = set(tagged_skills or extract_skills(desc))

    responsibilities: List[str] = []
    required_text_chunks: List[str] = []
    preferred_text_chunks: List[str] = []
    education_mentions: List[str] = []

    current_section = "overview"
    lines = _split_into_lines_and_sentences(desc)

    for line in lines:
        line_lower = line.lower()

        # Check section headers
        if PREFERRED_HEADINGS.search(line_lower):
            current_section = "preferred"
            continue
        elif REQUIREMENTS_HEADINGS.search(line_lower):
            current_section = "requirements"
            continue
        elif RESPONSIBILITIES_HEADINGS.search(line_lower):
            current_section = "responsibilities"
            continue

        # Collect education mentions
        if EDUCATION_PATTERN.search(line_lower):
            if len(line) < 180 and len(education_mentions) < 2:
                education_mentions.append(line)

        # Route line by current section
        if current_section == "responsibilities":
            if len(responsibilities) < 5 and len(line) > 15:
                responsibilities.append(line[:160])
        elif current_section == "requirements":
            required_text_chunks.append(line)
        elif current_section == "preferred":
            preferred_text_chunks.append(line)
        else:
            # In overview / intro: check if line describes an explicit duty
            first_word = line.split()[0] if line.split() else ""
            if DUTY_ACTION_VERBS.match(first_word) and len(responsibilities) < 3:
                responsibilities.append(line[:160])

    # Extract skills present specifically in preferred section
    preferred_text = " ".join(preferred_text_chunks)
    preferred_skills = [s for s in extract_skills(preferred_text) if s in all_tagged_skills]
    preferred_skills_set = set(preferred_skills)

    # Required skills are all tagged skills not exclusively in preferred
    required_skills = sorted(list(all_tagged_skills - preferred_skills_set))

    # Fallback if responsibilities section was not explicitly headed
    if not responsibilities:
        # Extract the first 2-3 action-oriented sentences from the description
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", desc) if len(s.strip()) > 15]
        for s in sentences:
            first_word = s.split()[0] if s.split() else ""
            if (
                DUTY_ACTION_VERBS.match(first_word)
                or "engineer" in s.lower()
                or "developer" in s.lower()
                or "stack" in s.lower()
            ):
                responsibilities.append(s[:160])
                if len(responsibilities) >= 3:
                    break
        if not responsibilities and sentences:
            responsibilities = [s[:160] for s in sentences[:2]]

    # Determine experience level label
    if required_years is not None and required_years > 0:
        if required_years == 1:
            exp_level = "Early Career (1 year)"
        else:
            exp_level = f"Experienced ({required_years}+ years)"
    else:
        title_lower = title.lower()
        if "intern" in title_lower:
            exp_level = "Internship"
        elif "junior" in title_lower or "associate" in title_lower:
            exp_level = "Junior / Entry Level"
        elif "senior" in title_lower or "sr" in title_lower:
            exp_level = "Senior IC"
        else:
            exp_level = "Entry / Mid Level (0-2 years)"

    education_summary = (
        education_mentions[0]
        if education_mentions
        else "Bachelor's degree in Computer Science, related technical field, or equivalent practical experience."
    )

    return {
        "role_title": title,
        "company": company,
        "responsibilities": responsibilities[:4],
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "experience_level": exp_level,
        "education": education_summary,
    }
