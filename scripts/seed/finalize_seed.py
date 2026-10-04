"""Trim companies.json (verified candidates) into the final seed list: seed.json.

Keep a company if it clears any relevance bar chosen from the data distribution:
  - >= 3 India engineering jobs        (~top 8% of companies)
  - >= 2 fresher-tagged jobs           (~top 5%)
  - >= 20 engineering jobs             (~top 7%, i.e. actively hiring at scale)
plus every verified hand-researched India slug.  Recruiters / gig-work boards are
denied by name.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent

# Recruiters, aggregators and freelance/AI-trainer gig boards (not real employer boards).
DENY = {
    "agency", "jobgether", "ziprecruiter", "mthreerecruitingportal", "onhires",
    "mercor", "people-culture-talent", "careerteam", "morganmorganjobsapplynow",
}


def relevant(r):
    return (r["by_region"]["india"] >= 3 or r["fresher_jobs"] >= 2 or r["eng_jobs"] >= 20)


def main():
    candidates = json.loads((HERE / "companies.json").read_text(encoding="utf-8"))
    india_seed = set()
    for line in (HERE / "india_seed.txt").read_text(encoding="utf-8").splitlines():
        if ":" in line and not line.startswith("#"):
            a, s = line.strip().split(":", 1)
            india_seed.add((a, s))

    seed = [r for r in candidates
            if r["slug"] not in DENY
            and (relevant(r) or (r["ats"], r["slug"]) in india_seed)]
    seed.sort(key=lambda r: (-r["by_region"]["india"], -r["fresher_jobs"], -r["eng_jobs"]))

    out = [{"ats": r["ats"], "slug": r["slug"]} for r in seed]
    (HERE / "seed.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    by_ats = {a: sum(1 for r in seed if r["ats"] == a) for a in ("greenhouse", "lever", "ashby")}
    print(f"{len(seed)} companies {by_ats}")
    print(f"eng jobs: {sum(r['eng_jobs'] for r in seed)}, "
          f"india: {sum(r['by_region']['india'] for r in seed)}, "
          f"fresher-tagged: {sum(r['fresher_jobs'] for r in seed)}")


if __name__ == "__main__":
    main()
