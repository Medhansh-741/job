"""Matching spike: run each resume in resumes/ through the funnel against data/jobs.json.

Funnel: catalog -> hard filters (not senior, low required years) -> top-K by semantic
similarity -> hybrid score (0.6 semantic + 0.4 skill coverage) -> ranked list.
Prints stats at every stage so thresholds can be chosen from the data.

Usage:  python run_spike.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pdfplumber

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "seed"))
from build_seed import SENIOR  # noqa: E402
from fastembed import TextEmbedding  # noqa: E402
from skills import extract_skills  # noqa: E402

K = 200
YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs)", re.I)


def required_years(text):
    ys = [int(m.group(1)) for m in YEARS.finditer(text) if int(m.group(1)) <= 20]
    return min(ys) if ys else None


def read_resume(path):
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def embed(model, texts, batch=64):
    return np.array(list(model.embed(texts, batch_size=batch)), dtype=np.float32)


def main():
    jobs = json.loads((HERE / "data" / "jobs.json").read_text(encoding="utf-8"))
    model = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")

    cache = HERE / "data" / "job_emb.npy"
    if cache.exists() and len(np.load(cache)) == len(jobs):
        J = np.load(cache)
    else:
        print("embedding", len(jobs), "jobs ...", flush=True)
        J = embed(model, [f"{j['title']}. {j['description'][:600]}" for j in jobs])
        np.save(cache, J)
    J = J / np.linalg.norm(J, axis=1, keepdims=True)

    job_skills = [extract_skills(j["title"] + " " + j["description"]) for j in jobs]
    req_years = [required_years(j["description"]) for j in jobs]
    senior = np.array([bool(SENIOR.search(j["title"])) for j in jobs])
    years_ok = np.array([(y is None or y <= 2) for y in req_years])
    fresher_title = np.array([j["fresher_title"] for j in jobs])
    region = np.array([j["region"] for j in jobs])
    hard = ~senior & years_ok

    print(f"\nCATALOG: {len(jobs)} jobs | senior-title: {senior.sum()} | "
          f"required years > 2: {(~years_ok).sum()} | pass hard filter: {hard.sum()} "
          f"({hard.mean():.0%}) | fresher-titled: {fresher_title.sum()} | "
          f"jobs with >=1 skill found: {sum(1 for s in job_skills if s)}")

    for path in sorted((ROOT / "resumes").glob("*.pdf")):
        text = read_resume(path)
        skills = extract_skills(text)
        body = re.sub(r"\s+", " ", text)
        vec_a = embed(model, [body[:1500]])[0]                       # resume text head
        vec_b = embed(model, ["Skills: " + ", ".join(sorted(skills))])[0]  # skills only
        vec_a /= np.linalg.norm(vec_a)
        vec_b /= np.linalg.norm(vec_b)
        sem_a, sem_b = J @ vec_a, J @ vec_b

        print("\n" + "=" * 100)
        print(f"{path.name}: {len(text)} chars, {len(skills)} skills: {sorted(skills)}")

        for name, sem in (("A: resume-text embedding", sem_a), ("B: skills-only embedding", sem_b)):
            pool = np.where(hard)[0]
            order = pool[np.argsort(-sem[pool])][:K]
            cov = np.array([len(skills & job_skills[i]) / len(job_skills[i]) if job_skills[i] else 0.0
                            for i in order])
            final = 0.6 * sem[order] + 0.4 * cov
            rank = np.argsort(-final)
            all_sem = sem[pool]
            print(f"\n  [{name}] similarity over hard-filtered pool: "
                  f"p50={np.percentile(all_sem, 50):.2f} p90={np.percentile(all_sem, 90):.2f} "
                  f"p99={np.percentile(all_sem, 99):.2f} max={all_sem.max():.2f} | "
                  f"top-{K} cutoff={sem[order[-1]]:.2f}")
            top = [order[r] for r in rank[:15]]
            print(f"  top-15 regions: {dict(zip(*np.unique(region[top], return_counts=True)))} | "
                  f"fresher-titled in top-15: {int(fresher_title[top].sum())} | "
                  f"companies: {len({jobs[i]['company'] for i in top})}")
            for r in rank[:10]:
                i = order[r]
                j = jobs[i]
                print(f"   {final[r]:.2f} (sem {sem[i]:.2f}, cov {cov[r]:.2f}) "
                      f"{j['title'][:55]:55} | {j['company'][:18]:18} | {j['location'][:22]:22} "
                      f"| yrs={req_years[i]}")


if __name__ == "__main__":
    main()
