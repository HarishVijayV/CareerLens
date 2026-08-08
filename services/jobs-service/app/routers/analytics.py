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
        """
    )[0]
    skills = _rows("SELECT COUNT(*) AS n FROM analytics.dim_skill")[0]["n"]
    return {**stats, "total_skills": skills}


@router.get("/top-skills")
@cached("top_skills")
def top_skills(limit: int = 15):
    return _rows(
        """
        SELECT skill_name, posting_count
        FROM analytics.dim_skill
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
        WHERE salary IS NOT NULL
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
        WHERE salary IS NOT NULL
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
        WHERE posted_month IS NOT NULL
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
        WITH overall AS (
            SELECT AVG(salary) AS avg_all FROM analytics.fact_job_posting WHERE salary IS NOT NULL
        )
        SELECT s.skill_name,
               COUNT(*)                                        AS postings,
               ROUND(AVG(f.salary))::float                     AS avg_salary,
               ROUND(AVG(f.salary) - (SELECT avg_all FROM overall))::float AS premium_vs_average
        FROM analytics.bridge_posting_skill b
        JOIN analytics.dim_skill s       ON s.skill_id = b.skill_id
        JOIN analytics.fact_job_posting f ON f.posting_id = b.posting_id
        WHERE f.salary IS NOT NULL
        GROUP BY s.skill_name
        HAVING COUNT(*) > 100
        ORDER BY avg_salary DESC
        LIMIT :limit
        """,
        limit=limit,
    )
