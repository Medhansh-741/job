"""Deterministic Resume Parser & Candidate Profile Structuring Service.

Extracts structured headings via font weight/size analysis (PDF) and styles (DOCX),
converts to clean Markdown, extracts deduplicated skills, parses work history date
ranges to compute experience years, and generates dynamic JSON section hierarchies.
Zero LLM calls: 100% deterministic, instant, reproducible, and private.
"""
import io
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter

import pdfplumber
from docx import Document

from app.services.catalog_normalizer import extract_skills

# Common section synonyms mapped to canonical slugs
SECTION_MAP = {
    "summary": "summary",
    "professional summary": "summary",
    "profile": "summary",
    "objective": "summary",
    "about me": "summary",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment history": "experience",
    "work history": "experience",
    "internships": "experience",
    "technical skills": "skills",
    "skills": "skills",
    "skills & competencies": "skills",
    "core competencies": "skills",
    "technologies": "skills",
    "projects": "projects",
    "key projects": "projects",
    "personal projects": "projects",
    "academic projects": "projects",
    "education": "education",
    "academic background": "education",
    "qualifications": "education",
    "certifications": "certifications",
    "licenses & certifications": "certifications",
    "certificates": "certifications",
    "achievements": "achievements",
    "honors & awards": "achievements",
    "awards": "achievements",
    "publications": "publications",
    "coursework": "coursework",
}

MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "sept": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

MONTH_REGEX_STR = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

# Matches date ranges: "18 May 2026 - 20 July 2026", "Aug 2022 - Present", "Dec. 2025  Apr. 2026", "2021 - 2023"
DATE_RANGE_PATTERN = re.compile(
    rf"(?:(?:\d{{1,2}}\s+)?({MONTH_REGEX_STR}\.?\s*20\d\d)|\d{{1,2}}/\d{{4}}|(20\d\d))\s*(?:-|–|—|to||\s+)\s*(present|current|now|(?:\d{{1,2}}\s+)?({MONTH_REGEX_STR}\.?\s*20\d\d)|\d{{1,2}}/\d{{4}}|(20\d\d))",
    re.IGNORECASE,
)


INTERN_FREELANCE_RE = re.compile(
    r"\b(intern|internship|trainee|apprentice|fellow|freelance|contract|contractor|project|student)\b",
    re.IGNORECASE,
)
FULL_TIME_RE = re.compile(
    r"\b(full[-\s]?time|fte|permanent)\b",
    re.IGNORECASE,
)


@dataclass
class ParsedResumeProfile:
    headline: Optional[str]
    skills: List[str]
    experience_years: float            # Maps to full_time_experience_years for matching
    full_time_experience_years: float
    internship_months: int
    is_fresher: bool                   # True if full_time_experience_years < 1.0
    preferred_roles: List[str]
    sections: Dict[str, Dict[str, str]]
    detected_headings: List[str]
    markdown: str
    raw_text: str


def _parse_month_year(date_str: str) -> Optional[Tuple[int, int]]:
    """Converts a string like '18 May 2026', 'Aug 2022', '2022', or '08/2022' into (year, month)."""
    date_str = date_str.strip().lower()
    if date_str in ("present", "current", "now"):
        now = datetime.now(timezone.utc)
        return now.year, now.month

    # Strip optional leading day number (e.g. '18 may 2026' -> 'may 2026')
    date_str = re.sub(r"^\d{1,2}\s+", "", date_str)

    # Check for Month Year (e.g. Aug 2022 or Dec. 2025)
    m = re.search(rf"({MONTH_REGEX_STR})\.?\s*(20\d\d)", date_str)
    if m:
        month_name = m.group(1).rstrip(".")
        month = MONTH_MAP.get(month_name, 1)
        year = int(m.group(2))
        return year, month

    # Check for MM/YYYY
    m = re.search(r"(\d{1,2})/(\d{4})", date_str)
    if m:
        month = max(1, min(12, int(m.group(1))))
        year = int(m.group(2))
        return year, month

    # Check for Year only (e.g. 2022)
    m = re.search(r"(20\d\d)", date_str)
    if m:
        return int(m.group(1)), 1

    return None


def calculate_experience_breakdown(experience_text: str) -> Tuple[float, int, bool]:
    """Calculates full-time work experience (years), internship duration (months),
    and whether the candidate is strictly a fresher/entry-level.
    
    Fresher-First Invariant:
    A candidate role is strictly treated as internship / project experience (Fresher) UNLESS
    it explicitly indicates full-time corporate employment ('full-time', 'full time', 'fte', 'permanent').
    """
    if not experience_text:
        return 0.0, 0, True

    date_regex = re.compile(
        rf"((?:\d{{1,2}}\s+)?{MONTH_REGEX_STR}\.?\s*20\d\d|\d{{1,2}}/\d{{4}}|20\d\d)\s*(?:-|–|—|to||\s{{2,}})\s*(present|current|now|(?:\d{{1,2}}\s+)?{MONTH_REGEX_STR}\.?\s*20\d\d|\d{{1,2}}/\d{{4}}|20\d\d)",
        re.IGNORECASE,
    )

    lines = experience_text.splitlines()
    intern_intervals: List[Tuple[int, int]] = []
    full_time_intervals: List[Tuple[int, int]] = []

    for idx, line in enumerate(lines):
        for m in date_regex.finditer(line):
            start_str, end_str = m.group(1), m.group(2)
            if not start_str or not end_str:
                continue

            start_dt = _parse_month_year(start_str)
            end_dt = _parse_month_year(end_str)

            if start_dt and end_dt:
                start_m = start_dt[0] * 12 + start_dt[1]
                end_m = end_dt[0] * 12 + end_dt[1]
                if end_m >= start_m:
                    context_window = " ".join(lines[max(0, idx - 2): idx + 1])
                    # Strictly require explicit full-time indicator; otherwise count as practical intern/project experience
                    if FULL_TIME_RE.search(context_window) and not INTERN_FREELANCE_RE.search(context_window):
                        full_time_intervals.append((start_m, end_m))
                    else:
                        intern_intervals.append((start_m, end_m))

    def _merge_and_sum(intervals: List[Tuple[int, int]]) -> int:
        if not intervals:
            return 0
        intervals.sort(key=lambda x: x[0])
        merged: List[Tuple[int, int]] = []
        for start, end in intervals:
            if not merged:
                merged.append((start, end))
            else:
                prev_start, prev_end = merged[-1]
                if start <= prev_end:
                    merged[-1] = (prev_start, max(prev_end, end))
                else:
                    merged.append((start, end))
        return sum((end - start) for start, end in merged)

    internship_total_months = _merge_and_sum(intern_intervals)
    full_time_total_months = _merge_and_sum(full_time_intervals)

    full_time_years = min(25.0, round(full_time_total_months / 12.0, 1))
    is_fresher = full_time_years < 1.0

    return full_time_years, internship_total_months, is_fresher


def calculate_experience_years(experience_text: str) -> float:
    """Calculates non-overlapping full-time work experience in years.
    Defaults to 0.0 if no dates are found.
    """
    full_time_years, _, _ = calculate_experience_breakdown(experience_text)
    return full_time_years


def _extract_pdf_lines_with_meta(content: bytes) -> List[Dict[str, Any]]:
    """Extracts lines from PDF with character size and font weight attributes using extract_text_lines."""
    lines_meta: List[Dict[str, Any]] = []

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        all_sizes: List[float] = []

        for page_num, page in enumerate(pdf.pages):
            page_lines = page.extract_text_lines()
            if not page_lines:
                continue

            for l in page_lines:
                chars = l.get("chars", [])
                for c in chars:
                    all_sizes.append(round(c.get("size", 9.0), 1))

            for l in page_lines:
                text = l.get("text", "").strip()
                if not text:
                    continue

                chars = l.get("chars", [])
                avg_size = (sum(c["size"] for c in chars) / len(chars)) if chars else 9.0
                is_bold = any(
                    any(b in c.get("fontname", "").lower() for b in ["bold", "cmbx", "heavy", "black"])
                    for c in chars
                )

                lines_meta.append({
                    "text": text,
                    "size": round(avg_size, 1),
                    "is_bold": is_bold,
                    "page": page_num,
                })

    dominant_size = Counter(all_sizes).most_common(1)[0][0] if all_sizes else 9.0

    for idx, line in enumerate(lines_meta):
        line["is_heading"] = _is_heading_line(line["text"], line["size"], line["is_bold"], dominant_size, line_idx=idx)

    return lines_meta


def _is_heading_line(text: str, size: float, is_bold: bool, dominant_size: float, line_idx: int = 0) -> bool:
    """Deterministic rule to decide if a line is a section heading."""
    clean = text.strip()
    if not clean or len(clean) > 40:
        return False
    # Exclude bullet lines or contact lines
    if clean.startswith(("-", "•", "*", "1.", "2.", "3.", "http", "@")):
        return False
    if "@" in clean or "linkedin.com" in clean.lower() or "github.com" in clean.lower():
        return False

    clean_lower = clean.lower()
    matches_known = clean_lower in SECTION_MAP

    if matches_known:
        return True

    # The candidate's name at the top of the resume (line 0 or 1) is a title/header, not a section heading
    if line_idx <= 1 and not matches_known:
        return False

    # Check for short, bold or uppercase titles (e.g. "ACHIEVEMENTS", "PUBLICATIONS")
    if clean.isupper() and len(clean.split()) <= 4 and (is_bold or size >= dominant_size):
        return True

    if is_bold and size >= dominant_size + 1.5 and len(clean.split()) <= 4:
        return True

    return False


def _extract_docx_lines_with_meta(content: bytes) -> List[Dict[str, Any]]:
    """Extracts lines and headings from a DOCX document."""
    doc = Document(io.BytesIO(content))
    lines_meta = []

    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue

        style_name = p.style.name.lower() if p.style else ""
        is_bold = any(r.bold for r in p.runs)
        is_heading_style = "heading" in style_name

        is_heading = False
        if len(text) <= 40 and not text.startswith(("-", "•", "*")):
            if is_heading_style or (is_bold and (text.lower() in SECTION_MAP or text.isupper())):
                is_heading = True

        lines_meta.append({
            "text": text,
            "size": 12.0 if is_heading else 10.0,
            "is_bold": is_bold,
            "is_heading": is_heading,
        })

    return lines_meta


def parse_resume(content: bytes, mime_type: str, filename: str) -> ParsedResumeProfile:
    """Parses a resume file deterministically into structured sections and matching signals."""
    is_docx = (
        mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or filename.lower().endswith(".docx")
    )

    if is_docx:
        lines_meta = _extract_docx_lines_with_meta(content)
    else:
        lines_meta = _extract_pdf_lines_with_meta(content)

    # Segment into sections
    sections: Dict[str, Dict[str, str]] = {}
    detected_headings: List[str] = []
    markdown_lines: List[str] = []

    current_slug: Optional[str] = None
    current_heading: Optional[str] = None
    current_content: List[str] = []

    header_lines: List[str] = []
    found_first_heading = False

    for item in lines_meta:
        text = item["text"]
        if item["is_heading"]:
            found_first_heading = True
            # Save previous section if exists
            if current_slug and current_heading:
                sections[current_slug] = {
                    "raw_heading": current_heading,
                    "content": "\n".join(current_content).strip(),
                }

            raw_title = text
            slug = SECTION_MAP.get(raw_title.lower(), re.sub(r"[^a-z0-9]", "_", raw_title.lower()).strip("_"))
            current_slug = slug
            current_heading = raw_title
            current_content = []
            detected_headings.append(raw_title)
            markdown_lines.append(f"\n## {raw_title}")
        else:
            if not found_first_heading:
                header_lines.append(text)
            else:
                current_content.append(text)
            markdown_lines.append(text)

    # Save the final section
    if current_slug and current_heading:
        sections[current_slug] = {
            "raw_heading": current_heading,
            "content": "\n".join(current_content).strip(),
        }

    full_text = "\n".join(item["text"] for item in lines_meta)
    full_markdown = "\n".join(markdown_lines).strip()

    # 1. Headline Extraction
    headline: Optional[str] = None
    if len(header_lines) >= 2:
        candidate_line = header_lines[1].strip()
        if len(candidate_line) <= 60 and not any(c in candidate_line for c in ["@", "linkedin", "github", "http", "+91"]):
            headline = candidate_line

    if not headline and "summary" in sections:
        summary_text = sections["summary"]["content"]
        first_sentence = summary_text.split(".")[0].strip()
        if len(first_sentence) <= 90:
            headline = first_sentence

    # 2. Unified Skills Extraction across entire document
    skills = extract_skills(full_text)

    # 3. Experience Breakdown Calculation (Full-time vs Internships)
    experience_text = ""
    if "experience" in sections:
        experience_text = sections["experience"]["content"]
    full_time_years, internship_months, is_fresher = calculate_experience_breakdown(experience_text)

    # 4. Preferred Roles
    preferred_roles: List[str] = []
    if headline:
        # Split on pipe or slash or comma if multiple roles are listed (e.g. AI/ML Engineer | Full-Stack Developer)
        parts = re.split(r"[|/]", headline)
        for p in parts:
            clean_role = p.strip()
            if 3 <= len(clean_role) <= 45 and not any(k in clean_role.lower() for k in ["india", "usa", "http", "@", "+91"]):
                preferred_roles.append(clean_role)
        if not preferred_roles:
            preferred_roles = [headline]

    return ParsedResumeProfile(
        headline=headline,
        skills=skills,
        experience_years=full_time_years,
        full_time_experience_years=full_time_years,
        internship_months=internship_months,
        is_fresher=is_fresher,
        preferred_roles=preferred_roles,
        sections=sections,
        detected_headings=detected_headings,
        markdown=full_markdown,
        raw_text=full_text,
    )
