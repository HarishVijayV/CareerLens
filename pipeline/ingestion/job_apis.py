"""
Real job postings from free, legitimate public APIs. No scraping of sites whose terms
forbid it (LinkedIn, Indeed) — those have no free public API, and building a portfolio
project on a ToS violation is a bad story to tell in an interview.

Sources, and why these three:
  * Adzuna     — the important one: covers BOTH India (in) and USA (us) from the same
                 free key, so the project keeps working whether you're job-hunting in
                 India now or in the US after your MS. https://developer.adzuna.com/
  * Remotive   — remote-only roles, no key needed. Location-agnostic by nature, so it
                 stays relevant from anywhere.
  * Arbeitnow  — Europe/Germany-heavy, no key needed. Kept as a bonus source; it is NOT
                 a good India/USA source, so it's off by default.

Search terms come from the user's PROFILE (skills, target roles, countries) rather than
being hardcoded, so ingestion pulls relevant postings instead of everything on the
internet. See services/auth-service/app/models.py::UserProfile.

Usage:
    python ingestion/job_apis.py --out data/raw/real_postings.jsonl \
        --terms "Data Engineer,Analytics Engineer" --countries in,us
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

TIMEOUT = 30.0
ADZUNA_PAGES_PER_TERM = 2  # 50 results/page; keep small to stay inside the free quota


def _normalize(
    posting_id: str,
    title: str | None,
    company: str | None,
    location: str | None,
    region: str,
    salary,
    skills: list[str],
    description: str,
    source: str,
    url: str | None = None,
) -> dict:
    """Every source has its own field names — normalizing at the EDGE means the Spark ETL
    downstream sees one consistent shape and doesn't need per-source branching. Doing
    this here rather than later is what keeps the pipeline simple."""
    return {
        "posting_id": posting_id,
        "title": (title or "").strip() or None,
        "company": company,
        "location": location,
        "region": region,
        "seniority": "unknown",  # inferred later by the Spark ETL / skill-extractor agent
        "remote": source == "remotive",
        "salary": salary,
        "required_skills": skills,
        "description": (description or "")[:2000],
        "source": source,
        "url": url,
        "posted_month": None,
    }


def _matches_terms(title: str, tags: list[str], terms: list[str]) -> bool:
    """Client-side relevance filter.

    This exists because Remotive's `search` parameter does NOT reliably filter — asking
    it for "Data Engineer" happily returns "Sales Jedi" and "Freelance Copywriter". Never
    assume a third-party API's filter works; verify what actually comes back and filter
    again yourself. Trusting it blindly is how non-tech postings end up in a
    tech-jobs dataset and quietly poison every downstream aggregate.
    """
    if not terms:
        return True

    title_lower = title.lower()

    # Match on the TITLE, not the tags. Tags were tried first and are far too noisy —
    # a copywriting role tagged "data" sailed straight through. The title is what
    # actually defines the role, so that's what gets matched.
    if any(term.lower() in title_lower for term in terms):
        return True

    # Also accept a title containing every significant word of a term in any order, so
    # "Data Engineer" still matches "Engineer, Data Platform".
    title_words = set(title_lower.replace(",", " ").replace("/", " ").split())
    for term in terms:
        term_words = {w for w in term.lower().split() if len(w) > 2}
        if term_words and term_words.issubset(title_words):
            return True

    return False


# Remotive's category slugs relevant to a tech job hunt — narrowing at the API level
# first, then filtering by term, cuts out most of the noise before it reaches us.
REMOTIVE_CATEGORIES = ["software-dev", "data"]


def fetch_remotive(terms: list[str]) -> list[dict]:
    out = []
    for category in REMOTIVE_CATEGORIES:
        try:
            resp = httpx.get(
                "https://remotive.com/api/remote-jobs",
                params={"category": category},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"  remotive '{category}': failed ({exc})")
            continue

        jobs = [
            j
            for j in resp.json().get("jobs", [])
            if _matches_terms(j.get("title", ""), j.get("tags", []), terms)
        ]
        print(f"  remotive '{category}': {len(jobs)} (after relevance filter)")
        out.extend(
            _normalize(
                posting_id=f"remotive_{j['id']}",
                title=j.get("title"),
                company=j.get("company_name"),
                location=j.get("candidate_required_location"),
                region="Remote",
                salary=j.get("salary") or None,
                skills=j.get("tags", []),
                description=j.get("description", ""),
                source="remotive",
                url=j.get("url"),
            )
            for j in jobs
        )
        time.sleep(0.5)  # be a polite API citizen; free tiers are shared infrastructure
    return out


def fetch_adzuna(terms: list[str], countries: list[str], app_id: str, app_key: str) -> list[dict]:
    if not app_id or not app_key:
        print("  adzuna: SKIPPED (set ADZUNA_APP_ID / ADZUNA_APP_KEY to enable)")
        return []

    out = []
    for country in countries:
        for term in terms or ["data engineer"]:
            for page in range(1, ADZUNA_PAGES_PER_TERM + 1):
                try:
                    resp = httpx.get(
                        f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}",
                        params={
                            "app_id": app_id,
                            "app_key": app_key,
                            "results_per_page": 50,
                            "what": term,
                            "content-type": "application/json",
                        },
                        timeout=TIMEOUT,
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    print(f"  adzuna {country} '{term}' p{page}: failed ({exc})")
                    break

                jobs = resp.json().get("results", [])
                if not jobs:
                    break

                print(f"  adzuna {country} '{term}' p{page}: {len(jobs)}")
                out.extend(
                    _normalize(
                        posting_id=f"adzuna_{j.get('id')}",
                        title=j.get("title"),
                        company=(j.get("company") or {}).get("display_name"),
                        location=(j.get("location") or {}).get("display_name"),
                        region={"in": "India", "us": "North America"}.get(country, country.upper()),
                        salary=j.get("salary_min"),
                        skills=[],  # Adzuna has no tags field; the ETL extracts from text
                        description=j.get("description", ""),
                        source=f"adzuna_{country}",
                        url=j.get("redirect_url"),
                    )
                    for j in jobs
                )
                time.sleep(0.5)
    return out


def fetch_arbeitnow(terms: list[str]) -> list[dict]:
    try:
        resp = httpx.get("https://www.arbeitnow.com/api/job-board-api", timeout=TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  arbeitnow: failed ({exc})")
        return []

    jobs = resp.json().get("data", [])
    if terms:
        lowered = [t.lower() for t in terms]
        jobs = [j for j in jobs if any(t in (j.get("title") or "").lower() for t in lowered)]

    print(f"  arbeitnow: {len(jobs)}")
    return [
        _normalize(
            posting_id=f"arbeitnow_{j.get('slug')}",
            title=j.get("title"),
            company=j.get("company_name"),
            location=j.get("location"),
            region="Europe",
            salary=None,
            skills=j.get("tags", []),
            description=j.get("description", ""),
            source="arbeitnow",
            url=j.get("url"),
        )
        for j in jobs
    ]


def main(out_path: Path, terms: list[str], countries: list[str], include_europe: bool) -> None:
    print(f"Fetching real postings — terms={terms or '(all)'} countries={countries}")

    postings = fetch_adzuna(
        terms, countries, os.getenv("ADZUNA_APP_ID", ""), os.getenv("ADZUNA_APP_KEY", "")
    )
    postings += fetch_remotive(terms)
    if include_europe:
        postings += fetch_arbeitnow(terms)

    # Sources overlap (the same role can appear on several boards) and Adzuna paginates,
    # so dedup on the natural key before writing. Spark dedups again downstream — being
    # idempotent at more than one layer is cheap insurance in a pipeline.
    unique = {p["posting_id"]: p for p in postings if p["title"]}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for posting in unique.values():
            f.write(json.dumps(posting) + "\n")

    print(f"\nWrote {len(unique):,} unique real postings -> {out_path}")
    if not unique:
        print("No postings fetched. Without ADZUNA keys only Remotive runs — check network.")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/raw/real_postings.jsonl")
    parser.add_argument(
        "--terms",
        default="Data Engineer,Analytics Engineer,Machine Learning Engineer",
        help="comma-separated search terms (normally taken from the user's profile)",
    )
    parser.add_argument("--countries", default="in,us", help="Adzuna country codes, e.g. in,us")
    parser.add_argument("--include-europe", action="store_true", help="also query Arbeitnow")
    args = parser.parse_args()

    main(
        Path(args.out),
        [t.strip() for t in args.terms.split(",") if t.strip()],
        [c.strip() for c in args.countries.split(",") if c.strip()],
        args.include_europe,
    )
