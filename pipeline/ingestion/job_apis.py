"""
Real job postings from free, legit public APIs — no scraping of sites whose ToS forbids
it (LinkedIn/Indeed). This is the "real, messy data" half of the ingestion story
described in docs/DATA_ENGINEERING.md; generate_synthetic_data.py is the "scale it up"
half.

- Remotive: https://remotive.com/api/remote-jobs (no key required)
- Arbeitnow: https://www.arbeitnow.com/api/job-board-api (no key required)
- Adzuna: https://developer.adzuna.com/ (free tier, needs APP_ID + APP_KEY)

Usage:
    python job_apis.py --out data/raw/real_postings.jsonl
"""
import argparse
import json
import os
from pathlib import Path

import httpx


def fetch_remotive() -> list[dict]:
    resp = httpx.get("https://remotive.com/api/remote-jobs", timeout=30.0)
    resp.raise_for_status()
    jobs = resp.json().get("jobs", [])
    return [
        {
            "posting_id": f"remotive_{j['id']}",
            "title": j.get("title"),
            "company": j.get("company_name"),
            "location": j.get("candidate_required_location"),
            "region": "Remote",
            "seniority": "unknown",
            "remote": True,
            "salary": j.get("salary") or None,
            "required_skills": j.get("tags", []),
            "description": j.get("description", "")[:2000],
            "source": "remotive",
        }
        for j in jobs
    ]


def fetch_arbeitnow() -> list[dict]:
    resp = httpx.get("https://www.arbeitnow.com/api/job-board-api", timeout=30.0)
    resp.raise_for_status()
    jobs = resp.json().get("data", [])
    return [
        {
            "posting_id": f"arbeitnow_{j.get('slug')}",
            "title": j.get("title"),
            "company": j.get("company_name"),
            "location": j.get("location"),
            "region": "Europe",
            "seniority": "unknown",
            "remote": j.get("remote", False),
            "salary": None,
            "required_skills": j.get("tags", []),
            "description": j.get("description", "")[:2000],
            "source": "arbeitnow",
        }
        for j in jobs
    ]


def fetch_adzuna(app_id: str, app_key: str, country: str = "us", results_per_page: int = 50) -> list[dict]:
    if not app_id or not app_key:
        print("Skipping Adzuna — set ADZUNA_APP_ID / ADZUNA_APP_KEY to enable it.")
        return []

    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    resp = httpx.get(
        url,
        params={"app_id": app_id, "app_key": app_key, "results_per_page": results_per_page},
        timeout=30.0,
    )
    resp.raise_for_status()
    jobs = resp.json().get("results", [])
    return [
        {
            "posting_id": f"adzuna_{j.get('id')}",
            "title": j.get("title"),
            "company": (j.get("company") or {}).get("display_name"),
            "location": (j.get("location") or {}).get("display_name"),
            "region": country.upper(),
            "seniority": "unknown",
            "remote": False,
            "salary": j.get("salary_min"),
            "required_skills": [],
            "description": j.get("description", "")[:2000],
            "source": "adzuna",
        }
        for j in jobs
    ]


def main(out_path: Path) -> None:
    postings: list[dict] = []
    for fetch_fn, name in [(fetch_remotive, "remotive"), (fetch_arbeitnow, "arbeitnow")]:
        try:
            batch = fetch_fn()
            print(f"{name}: fetched {len(batch)} postings")
            postings.extend(batch)
        except httpx.HTTPError as exc:
            print(f"{name}: failed ({exc}) — continuing with other sources")

    postings.extend(
        fetch_adzuna(os.getenv("ADZUNA_APP_ID", ""), os.getenv("ADZUNA_APP_KEY", ""))
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for posting in postings:
            f.write(json.dumps(posting) + "\n")

    print(f"Wrote {len(postings)} real postings -> {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=str, default="data/raw/real_postings.jsonl")
    args = parser.parse_args()
    main(Path(args.out))
