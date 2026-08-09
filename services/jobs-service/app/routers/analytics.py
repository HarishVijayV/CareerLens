"""
The data-analytics endpoints — what the dashboard charts read. Each one is a plain SQL
aggregation over the dbt star schema, cached in Redis because the underlying data only
changes when the pipeline runs.
"""
from fastapi import APIRouter

from app.routers.jobs import _rows, cached

# NOTE on the ::float casts below.
# Postgres ROUND() on a numeric returns `numeric`, which psycopg maps to Python's Decimal.
# Decimal isn't JSON-serializable, so it gets stringified — the API then returns
# "avg_salary": "118322" instead of 118322, and the frontend's .toLocaleString() silently
# does nothing to a string (no thousands separators, and any arithmetic relies on JS
# coercion). Casting in SQL fixes it once, at the source, rather than in every consumer.

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
@cached("overview")
def overview():
    """Headline numbers for the top of the dashboard."""
    stats = _rows(
        """
        SELECT COUNT(*)                                   AS total_postings,
               COUNT(DISTINCT company_id)                 AS total_companies,
               ROUND(AVG(salary))::float                  AS avg_salary,
               ROUND(AVG(CASE WHEN remote THEN 1 ELSE 0 END) * 100, 1)::float AS remote_percent
        FROM analytics.fact_job_posting
        WHERE is_real
        """
    )[0]
    # Skills actually SEEN on a real posting, not every skill the vocabulary knows about.
    # dim_skill counts the whole vocabulary including skills that only appear on generated
    # rows, so it reported 107 while the real postings mention far fewer.
    skills = _rows(
        """
        SELECT COUNT(DISTINCT b.skill_id) AS n
        FROM analytics.bridge_posting_skill b
        JOIN analytics.fact_job_posting f ON f.posting_id = b.posting_id
        WHERE f.is_real
        """
    )[0]["n"]
    return {**stats, "total_skills": skills}


@router.get("/top-skills")
@cached("top_skills")
def top_skills(limit: int = 15):
    return _rows(
        """
        SELECT s.skill_name, COUNT(*) AS posting_count
        FROM analytics.bridge_posting_skill b
        JOIN analytics.dim_skill s        ON s.skill_id = b.skill_id
        JOIN analytics.fact_job_posting f ON f.posting_id = b.posting_id
        WHERE f.is_real
        GROUP BY s.skill_name
        ORDER BY posting_count DESC
        LIMIT :limit
        """,
        limit=limit,
    )


@router.get("/salary-by-seniority")
@cached("salary_by_seniority")
def salary_by_seniority():
    return _rows(
        """
        SELECT seniority,
               ROUND(AVG(salary))::float AS avg_salary,
               COUNT(*)             AS postings
        FROM analytics.fact_job_posting
        WHERE salary IS NOT NULL AND is_real
        GROUP BY seniority
        ORDER BY avg_salary
        """
    )


@router.get("/salary-by-region")
@cached("salary_by_region")
def salary_by_region():
    return _rows(
        """
        SELECT region,
               ROUND(AVG(salary))::float AS avg_salary,
               COUNT(*)             AS postings
        FROM analytics.fact_job_posting
        WHERE salary IS NOT NULL AND is_real
        GROUP BY region
        ORDER BY avg_salary DESC
        """
    )


@router.get("/postings-by-month")
@cached("postings_by_month")
def postings_by_month():
    """Hiring seasonality — the shape the synthetic generator deliberately encodes, so
    you can point at a chart and explain both the pattern AND where it came from."""
    return _rows(
        """
        SELECT posted_month, COUNT(*) AS postings
        FROM analytics.fact_job_posting
        WHERE posted_month IS NOT NULL AND is_real
        GROUP BY posted_month
        ORDER BY posted_month
        """
    )


@router.get("/skill-premium")
@cached("skill_premium")
def skill_premium(limit: int = 15):
    """Average salary of postings that require each skill, versus the overall average.

    This is the most genuinely interesting query in the project: it answers "which skills
    are actually worth money", and it needs the bridge table to express at all — a good
    concrete example of why the many-to-many was modeled properly.
    """
    return _rows(
        """
        -- The baseline is postings that HAVE a skill recorded, not all postings.
        --
        -- Comparing against the average of everything made every single skill look
        -- underpaid — Java at -$13,700, Python at -$25,187, all fifteen negative, which is
        -- arithmetically impossible for a real premium and was the tell that the baseline
        -- was wrong. Skills are only extracted from postings whose description survived
        -- Adzuna's truncation, and those skew toward Indian listings, while the overall
        -- average is dominated by US salaries with no skills recorded. The query was
        -- comparing two different populations and calling the gap a premium.
        --
        -- Scoping the baseline to the same population makes it a like-for-like comparison,
        -- and the numbers become meaningful: Java +$7,825, PostgreSQL -$51,230.
        WITH scoped AS (
            SELECT DISTINCT f.posting_id, f.salary
            FROM analytics.fact_job_posting f
            JOIN analytics.bridge_posting_skill b ON b.posting_id = f.posting_id
            WHERE f.salary IS NOT NULL AND f.is_real
        ),
        overall AS (SELECT AVG(salary) AS avg_all FROM scoped)
        SELECT s.skill_name,
               COUNT(*)                                        AS postings,
               ROUND(AVG(f.salary))::float                     AS avg_salary,
               ROUND(AVG(f.salary) - (SELECT avg_all FROM overall))::float AS premium_vs_average
        FROM analytics.bridge_posting_skill b
        JOIN analytics.dim_skill s       ON s.skill_id = b.skill_id
        JOIN analytics.fact_job_posting f ON f.posting_id = b.posting_id
        WHERE f.salary IS NOT NULL AND f.is_real
        GROUP BY s.skill_name
        -- 15 real postings is the floor for an average worth showing. The old threshold of
        -- 100 was sized for the synthetic set and would return nothing at all here.
        HAVING COUNT(*) >= 15
        ORDER BY avg_salary DESC
        LIMIT :limit
        """,
        limit=limit,
    )
