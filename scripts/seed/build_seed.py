"""Build a verified seed list of ATS company slugs.

Candidate slugs come from big_<ats>.json (public Common Crawl-derived pool) and
india_seed.txt (hand-researched, one `ats:slug` per line).  Each slug is called
once; companies with at least one engineering job in India / US / Remote are kept.
Fresher fit is tagged per company (counted), not used as a hard filter.

Usage:  python build_seed.py [--limit N]
Output: companies.json
"""
import argparse
import asyncio
import json
import re
from pathlib import Path

import httpx

HERE = Path(__file__).parent

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}

TECH = re.compile(
    r"\b(software|swe|sde|developer|engineer(ing)?|backend|back-end|frontend|front-end|"
    r"full[- ]?stack|data (scientist|engineer|analyst)|machine learning|ml|ai|devops|sre|"
    r"qa|sdet|mobile|android|ios|programmer)\b", re.I)
NON_TECH = re.compile(
    r"\b(sales|account|solutions? (engineer|consultant)|customer|support|recruit|marketing|"
    r"finance|legal|hr|people|electrical|mechanical|civil|field|manufacturing|hardware|"
    r"technician|operations|designer|content)\b", re.I)
FRESHER = re.compile(
    r"\b(intern|internship|new[- ]?grad|graduate|entry[- ]level|junior|early career|"
    r"university|campus|fresher|engineer i|sde[- ]?1|sde i|associate software)\b", re.I)
SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|manager|director|head|vp)\b", re.I)
INDIA = re.compile(r"\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|gurgaon|gurugram|"
                   r"noida|chennai)\b", re.I)
US = re.compile(r"\b(united states|usa|u\.s\.|us|new york|san francisco|seattle|austin|"
                r"boston|chicago|los angeles|bay area|california|nyc|texas)\b", re.I)
REMOTE = re.compile(r"\bremote\b", re.I)


def extract_jobs(ats, data):
    """Return [(title, location)] for a board response."""
    if ats == "greenhouse":
        return [(j.get("title", ""), (j.get("location") or {}).get("name", "") or "")
                for j in data.get("jobs", [])]
    if ats == "lever":
        return [(j.get("text", ""), (j.get("categories") or {}).get("location", "") or "")
                for j in data] if isinstance(data, list) else []
    if ats == "ashby":
        return [(j.get("title", ""), j.get("location", "") or "")
                for j in data.get("jobs", [])]
    return []


def classify(title, location):
    """Return (is_eng, region|None, is_fresher)."""
    if not TECH.search(title) or NON_TECH.search(title):
        return False, None, False
    region = ("india" if INDIA.search(location) else
              "us" if US.search(location) else
              "remote" if REMOTE.search(location) else None)
    fresher = bool(FRESHER.search(title)) or not SENIOR.search(title) and bool(
        re.search(r"\b(i|1)\b$", title.strip(), re.I))
    return True, region, fresher


async def check(client, sem, ats, slug):
    url = ENDPOINTS[ats].format(slug=slug)
    async with sem:
        try:
            r = await client.get(url)
        except httpx.HTTPError:
            return None
    if r.status_code != 200:
        return None
    try:
        jobs = extract_jobs(ats, r.json())
    except ValueError:
        return None
    eng = {"india": 0, "us": 0, "remote": 0}
    fresher = 0
    for title, loc in jobs:
        is_eng, region, is_fresher = classify(title, loc)
        if is_eng and region:
            eng[region] += 1
            fresher += is_fresher
    total_eng = sum(eng.values())
    if not total_eng:
        return None
    return {"ats": ats, "slug": slug, "total_jobs": len(jobs), "eng_jobs": total_eng,
            "by_region": eng, "fresher_jobs": fresher}


def load_candidates():
    cands = set()
    for ats in ENDPOINTS:
        f = HERE / f"big_{ats}.json"
        if f.exists():
            cands |= {(ats, s) for s in json.loads(f.read_text(encoding="utf-8"))}
    india = HERE / "india_seed.txt"
    if india.exists():
        for line in india.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and ":" in line:
                ats, slug = line.split(":", 1)
                cands.add((ats.strip(), slug.strip()))
    return sorted(cands)


async def main(limit):
    cands = load_candidates()[:limit]
    print(f"{len(cands)} candidate slugs")
    sem = asyncio.Semaphore(20)
    async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                 headers={"User-Agent": "job-matcher-seed/0.1"}) as client:
        results = [r for r in await asyncio.gather(
            *(check(client, sem, a, s) for a, s in cands)) if r]
    results.sort(key=lambda r: -r["eng_jobs"])
    (HERE / "companies.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"{len(results)} companies with eng jobs in India/US/Remote")
    print(f"eng jobs: {sum(r['eng_jobs'] for r in results)}, "
          f"fresher-tagged: {sum(r['fresher_jobs'] for r in results)}, "
          f"india: {sum(r['by_region']['india'] for r in results)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    asyncio.run(main(ap.parse_args().limit))
