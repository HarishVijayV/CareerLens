"""
Scales a job-postings dataset up to millions of rows so the Spark/MapReduce/MLlib pieces
downstream have something real to chew on — this is the direct stand-in for the "15M+
records" scale in the original resume bullet (see docs/DATA_ENGINEERING.md).

Deliberately NOT clean data: ~2% duplicate postings and a handful of malformed salary
strings are injected on purpose, so the Spark ETL step (pipeline/spark_jobs/etl_clean_jobs.py)
has real deduplication/cleaning work to do and isn't just passing data through untouched.

Usage:
    python generate_synthetic_data.py --rows 1000000 --out data/raw/postings.jsonl
"""
import argparse
import json
import random
from pathlib import Path

from faker import Faker

fake = Faker()

TITLES = [
    "Data Engineer", "Senior Data Engineer", "Data Analyst", "Machine Learning Engineer",
    "Backend Engineer", "Full Stack Developer", "DevOps Engineer", "Data Scientist",
    "Platform Engineer", "Analytics Engineer",
]
SKILL_POOL = [
    "Python", "SQL", "Spark", "Hadoop", "Airflow", "Kafka", "dbt", "Snowflake",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "FastAPI", "React", "PostgreSQL",
    "Redis", "Terraform", "Java", "Scala",
]
SENIORITIES = ["junior", "mid", "senior"]
REGIONS = ["North America", "Europe", "Asia Pacific", "Remote"]

# Seasonality: hiring is heavier in Q1/Q3, lighter around December — gives the MLlib
# model and dashboards a real, explainable pattern to detect instead of pure noise.
MONTH_WEIGHTS = {1: 1.3, 2: 1.2, 3: 1.2, 4: 1.0, 5: 1.0, 6: 0.9, 7: 1.1, 8: 1.1,
                 9: 1.2, 10: 1.0, 11: 0.9, 12: 0.6}


def _random_posting(posting_id: int) -> dict:
    seniority = random.choice(SENIORITIES)
    base_salary = {"junior": 70_000, "mid": 110_000, "senior": 160_000}[seniority]
    salary = base_salary + random.randint(-15_000, 25_000)

    skills = random.sample(SKILL_POOL, k=random.randint(3, 7))
    month = random.choices(list(MONTH_WEIGHTS), weights=list(MONTH_WEIGHTS.values()))[0]

    posting = {
        "posting_id": f"P{posting_id:09d}",
        "title": random.choice(TITLES),
        "company": fake.company(),
        "location": fake.city(),
        "region": random.choice(REGIONS),
        "seniority": seniority,
        "remote": random.random() < 0.35,
        "salary": salary,
        "posted_month": month,
        "required_skills": skills,
        "description": (
            f"We are looking for a {seniority} professional experienced in "
            f"{', '.join(skills)}. Based in {fake.city()}."
        ),
    }

    # --- deliberately injected messiness, for the ETL step to clean up ---
    if random.random() < 0.03:
        posting["salary"] = f"${salary:,}/yr"  # malformed: string instead of int
    if random.random() < 0.01:
        posting["salary"] = None  # missing entirely
    return posting


def generate(rows: int, out_path: Path, duplicate_rate: float = 0.02, seed: int | None = None) -> None:
    if seed is not None:
        random.seed(seed)
        Faker.seed(seed)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    last_posting = None

    with out_path.open("w", encoding="utf-8") as f:
        for i in range(rows):
            if last_posting is not None and random.random() < duplicate_rate:
                posting = dict(last_posting)  # exact duplicate, on purpose
            else:
                posting = _random_posting(i)
                last_posting = posting
            f.write(json.dumps(posting) + "\n")

            if (i + 1) % 100_000 == 0:
                print(f"  ...{i + 1:,} / {rows:,} rows written")

    print(f"Done: {rows:,} rows -> {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--out", type=str, default="data/raw/postings.jsonl")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    generate(args.rows, Path(args.out), seed=args.seed)
