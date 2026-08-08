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
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import publish_postings_discovered  # noqa: E402


def _load_env_file() -> None:
    """Read infra/.env into os.environ for keys that aren't already set.

    Without this, running this script from the host silently found no Adzuna keys and
    printed "adzuna: SKIPPED" even though the keys were sitting in infra/.env — the file
    is only loaded automatically by docker compose, and this script usually runs outside
    a container. The failure was quiet and looked like a configuration choice rather than
    a bug, so the pipeline ran on synthetic data for weeks without anyone noticing.

    Existing environment variables win, so a real export or a compose-injected value is
    never overwritten by the file.
    """
    env_file = Path(__file__).resolve().parents[2] / "infra" / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

TIMEOUT = 30.0
ADZUNA_PAGES_PER_TERM = 5  # 50 results/page; Adzuna's free tier allows ~250 calls/day

# Adzuna reports every salary in the country's OWN currency, with no currency field and
# no unit marker — an Indian posting returns 3000000 and a US one returns 160000, both as
# a bare number. Loading those into one `salary` column made every Indian role look like a
# $3M outlier, which then skewed the MLlib training set and every salary chart.
#
# Rates are pinned, not fetched. A live FX call would make the same input produce different
# output on different days, so a pipeline re-run could no longer be compared to the previous
# one — and a rate API is one more thing that can be down. Approximate-but-stable beats
# precise-but-irreproducible here; the number is a comparison aid, not an accounting figure.
FX_TO_USD = {
    "adzuna_in": 1 / 83.0,   # INR, mid-2024
    "adzuna_gb": 1.27,       # GBP
    "adzuna_us": 1.0,
    "remotive": 1.0,
}

# Adzuna has no tags field, so skills have to come out of the description text. This
# vocabulary deliberately MIRRORS generate_synthetic_data.py::SKILL_POOL — if real and
# synthetic postings named skills differently, every skill chart would silently split into
# two populations ("Postgres" vs "PostgreSQL") and the counts would be wrong.
#
# Keyword matching, not an LLM: this runs over every posting on every ingest, so it has to
# be free and deterministic. The skill_extractor AGENT exists for the case where nuance
# actually matters (reading one job description on demand); using it here would cost a
# model call per posting to answer a question a word list answers correctly.
SKILL_PATTERNS = {
    "Python": r"\bpython\b", "SQL": r"\bsql\b", "Spark": r"\b(?:py)?spark\b",
    "Hadoop": r"\bhadoop\b", "Airflow": r"\bairflow\b", "Kafka": r"\bkafka\b",
    "dbt": r"\bdbt\b", "Snowflake": r"\bsnowflake\b",
    "AWS": r"\b(?:aws|amazon web services)\b", "Azure": r"\bazure\b",
    "GCP": r"\b(?:gcp|google cloud)\b", "Docker": r"\bdocker\b",
    "Kubernetes": r"\b(?:kubernetes|k8s)\b", "FastAPI": r"\bfastapi\b",
    "React": r"\breact(?:\.js)?\b", "PostgreSQL": r"\b(?:postgresql|postgres)\b",
    "Redis": r"\bredis\b", "Terraform": r"\bterraform\b",
    "Java": r"\bjava\b(?!script)", "Scala": r"\bscala\b",
}
_COMPILED_SKILLS = {name: re.compile(pat, re.I) for name, pat in SKILL_PATTERNS.items()}


def extract_skills(*texts: str | None) -> list[str]:
    """Pull known skills out of free text.

    `Java` excludes `JavaScript` via negative lookahead — without it every JavaScript
    posting counted as a Java posting, which is the classic substring-matching bug and
    would have quietly inflated Java demand in the charts.
    """
    blob = " ".join(t for t in texts if t)
    return [name for name, pattern in _COMPILED_SKILLS.items() if pattern.search(blob)]


# A full-time annual salary below this (USD-equivalent) is not credible for the roles we
# ingest. Observed values like $217 come from Indian postings that quote a MONTHLY figure
# in a field the API documents as annual.
#
# These are nulled, not repaired. We cannot distinguish "monthly figure" from "hourly
# rate" from "part-time role" from "typo" using the data we have, so any repair would be a
# guess — and a guessed salary is worse than a missing one, because it silently enters the
# MLlib training set and every average. Nulling loses a row's salary; guessing corrupts
# the aggregate. `salary IS NULL` is already handled everywhere downstream.
MIN_CREDIBLE_ANNUAL_USD = 5_000

_dropped_implausible = 0


def to_usd(salary, source: str):
    """Convert a source's native-currency salary to USD so one column means one thing."""
    global _dropped_implausible
    if salary is None:
        return None
    try:
        value = round(float(salary) * FX_TO_USD.get(source, 1.0), 2)
    except (TypeError, ValueError):
        return None
    if value < MIN_CREDIBLE_ANNUAL_USD:
        _dropped_implausible += 1
        return None
    return value


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
    this here rather than later is what keeps the pipeline simple.

    Three things are normalised here that used to leak downstream:

    * salary -> USD. Adzuna returns each country's native currency as a bare number with
      no currency field, so Indian roles arrived as 3000000 next to US roles at 160000.
    * skills. Adzuna has no tags field at all. A comment here once claimed "the ETL
      extracts from text" — it never did, so every Adzuna posting reached the warehouse
      with an EMPTY skill list. That silently broke job matching (nothing to match on) and
      under-counted every skill chart, while looking like a data-coverage problem rather
      than a missing implementation.
    * is_real. Downstream needs to tell a live posting from a generated one — to rank real
      ones first, to filter to them, and to keep synthetic rows out of any claim about the
      actual market.
    """
    text_skills = skills or extract_skills(title, description)
    return {
        "posting_id": posting_id,
        "title": (title or "").strip() or None,
        "company": company,
        "location": location,
        "region": region,
        "seniority": _infer_seniority(title, description),
        "remote": source == "remotive",
        "salary": to_usd(salary, source),
        "salary_currency_original": _NATIVE_CURRENCY.get(source, "USD"),
        "required_skills": text_skills,
        "description": (description or "")[:2000],
        "source": source,
        "is_real": True,
        "url": url,
        "posted_month": None,
    }


_NATIVE_CURRENCY = {"adzuna_in": "INR", "adzuna_gb": "GBP", "adzuna_us": "USD", "remotive": "USD"}

# Ordered most-specific first: "senior data engineer" must not match the junior rule via
# some later substring, and a bare title with no signal stays "mid" rather than guessing.
_SENIORITY_RULES = [
    ("senior", re.compile(r"\b(senior|sr\.?|lead|principal|staff|head of|manager|architect)\b", re.I)),
    ("junior", re.compile(r"\b(junior|jr\.?|intern|internship|graduate|entry[- ]level|trainee|associate)\b", re.I)),
]


def _infer_seniority(title: str | None, description: str | None) -> str:
    """Adzuna has no seniority field, and the ETL's downstream charts group by it.

    Title first, description only as a fallback: a description mentioning "you'll report
    to a senior engineer" describes a colleague, not the role, so trusting body text
    equally would mislabel junior roles as senior.
    """
    for label, pattern in _SENIORITY_RULES:
        if pattern.search(title or ""):
            return label
    for label, pattern in _SENIORITY_RULES:
        if pattern.search((description or "")[:400]):
            return label
    return "mid"


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

    # Report what was thrown away. A pipeline that silently discards rows is one you can't
    # trust the totals from — if skills coverage looks low or the average salary shifts,
    # this line is the difference between "the API changed" and "our filter is too strict".
    with_salary = sum(1 for p in unique.values() if p.get("salary"))
    with_skills = sum(1 for p in unique.values() if p.get("required_skills"))
    print(
        f"  salary present: {with_salary:,}/{len(unique):,} "
        f"({100 * with_salary // max(len(unique), 1)}%)  |  "
        f"skills extracted: {with_skills:,}/{len(unique):,} "
        f"({100 * with_skills // max(len(unique), 1)}%)"
    )
    if _dropped_implausible:
        print(
            f"  dropped {_dropped_implausible:,} implausible salaries "
            f"(< ${MIN_CREDIBLE_ANNUAL_USD:,} USD/yr — monthly figures in an annual field)"
        )

    # Announce each new posting so independent consumers can react immediately, without
    # ingestion needing to know they exist. See pipeline/events.py for the honest
    # justification (and the cases where Kafka would NOT be justified).
    if unique:
        sent = publish_postings_discovered(list(unique.values()))
        if sent:
            print(f"Published {sent} posting.discovered events")
        else:
            print("Kafka unavailable — events skipped (pipeline unaffected)")

    if not unique:
        # Deliberately NOT a failure. A third-party board legitimately returning nothing
        # for your search terms today is a normal outcome, and killing the whole pipeline
        # over it would throw away the synthetic data that's already generated. Warn
        # loudly, exit clean, let the ETL process whatever raw files exist.
        print(
            "  WARNING: no real postings matched.\n"
            "  Usually one of: (a) no ADZUNA keys set, so only Remotive ran; or\n"
            "  (b) your --terms are too narrow for what's listed right now.\n"
            "  The pipeline continues with synthetic data."
        )


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
