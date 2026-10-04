"""Test suite for deterministic resume parser across local test resumes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.services.resume_parser import parse_resume

RESUMES_DIR = ROOT / "resumes"


def main():
    pdf_files = sorted(RESUMES_DIR.glob("*.pdf"))
    if not pdf_files:
        print("No PDF resumes found in resumes/.")
        return

    print(f"Testing resume parser across {len(pdf_files)} candidate resumes:\n")

    for pdf_path in pdf_files:
        content = pdf_path.read_bytes()
        profile = parse_resume(content, "application/pdf", pdf_path.name)

        print("=" * 80)
        print(f"FILE: {pdf_path.name}")
        print(f"HEADLINE: {profile.headline}")
        print(f"EXPERIENCE YEARS: {profile.experience_years} yrs")
        print(f"SKILLS ({len(profile.skills)}): {profile.skills}")
        print(f"DETECTED HEADINGS: {profile.detected_headings}")
        print(f"PARSED SECTIONS: {list(profile.sections.keys())}")
        for slug, data in profile.sections.items():
            first_line = data["content"].split("\n")[0][:80] if data["content"] else "(empty)"
            print(f"  - [{data['raw_heading']}] -> {first_line}...")
        print()


if __name__ == "__main__":
    main()
