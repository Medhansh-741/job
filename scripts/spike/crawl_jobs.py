"""Crawl every board in seed.json and save engineering jobs (with descriptions) to
data/jobs.json.  Spike-only: this is a one-off local crawl, not the production crawler.

Usage:  python crawl_jobs.py
"""
import asyncio
import html
import json
import re
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "seed"))
from build_seed import classify  # noqa: E402

URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}
TAG = re.compile(r"<[^>]+>")


def strip_html(s):
    return re.sub(r"\s+", " ", TAG.sub(" ", html.unescape(html.unescape(s or "")))).strip()


def normalize(ats, slug, data):
    out = []
    if ats == "greenhouse":
        for j in data.get("jobs", []):
            out.append((j.get("title", ""), (j.get("location") or {}).get("name", "") or "",
                        j.get("absolute_url", ""), strip_html(j.get("content")),
                        j.get("company_name") or slug))
    elif ats == "lever" and isinstance(data, list):
        for j in data:
            out.append((j.get("text", ""), (j.get("categories") or {}).get("location", "") or "",
                        j.get("hostedUrl", ""), (j.get("descriptionPlain") or "").strip(), slug))
    elif ats == "ashby":
        for j in data.get("jobs", []):
            out.append((j.get("title", ""), j.get("location", "") or "", j.get("jobUrl", ""),
                        (j.get("descriptionPlain") or "").strip(), slug))
    return out


async def crawl(client, sem, ats, slug):
    async with sem:
        try:
            r = await client.get(URLS[ats].format(slug=slug))
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return []
    jobs = []
    for title, loc, url, desc, company in normalize(ats, slug, data):
        is_eng, region, fresher_title = classify(title, loc)
        if is_eng and region and url:
            jobs.append({"ats": ats, "slug": slug, "company": company, "title": title,
                         "location": loc, "region": region, "url": url,
                         "fresher_title": fresher_title, "description": desc[:4000]})
    return jobs


async def main():
    seed = json.loads((HERE.parent / "seed" / "seed.json").read_text(encoding="utf-8"))
    sem = asyncio.Semaphore(15)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "job-matcher-spike/0.1"}) as client:
        batches = await asyncio.gather(*(crawl(client, sem, s["ats"], s["slug"]) for s in seed))
    jobs = [j for b in batches for j in b]
    (HERE / "data" / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    by_region = {r: sum(1 for j in jobs if j["region"] == r) for r in ("india", "us", "remote")}
    print(f"{len(jobs)} jobs from {len(seed)} boards; by region {by_region}; "
          f"with description: {sum(1 for j in jobs if j['description'])}")


if __name__ == "__main__":
    asyncio.run(main())
