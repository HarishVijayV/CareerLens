"""
Serves the warehouse to the app. Every query here hits the dbt-built `analytics.*` star
schema — never the raw Spark output, and never the pipeline itself. That separation is
deliberate: the app reads data that has already been cleaned AND passed dbt's tests, so
a bad upstream run can't surface as garbage in the UI.

Caching: analytics queries scan ~200k rows and the underlying data only changes when the
pipeline runs (daily). Recomputing that per page-load would be wasteful, so results are
cached in Redis with a TTL — the classic cache-aside pattern (check cache -> miss -> query
-> store -> return).
"""
import functools
import json
import os

import redis
from fastapi import APIRouter, Query
from sqlalchemy import create_engine, text

router = APIRouter(prefix="/jobs", tags=["jobs"])

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://careerlens:change_me@postgres:5432/careerlens"
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
_redis = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)

CACHE_TTL_SECONDS = 300


def cached(key: str, ttl: int = CACHE_TTL_SECONDS):
    """Cache-aside decorator. Redis being down must not take the API down with it, so
    every Redis call is wrapped — a cache is an optimization, never a dependency.

    functools.wraps is load-bearing here, not cosmetic: FastAPI builds each route's
    request model by INSPECTING the handler's signature. Without @wraps, it sees the
    wrapper's `(*args, **kwargs)` and demands query parameters literally named "args"
    and "kwargs". @wraps sets __wrapped__, which inspect.signature follows back to the
    real function. Any decorator applied under a FastAPI route needs this.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            cache_key = f"jobs:{key}:{json.dumps(kwargs, sort_keys=True, default=str)}"
            try:
                hit = _redis.get(cache_key)
                if hit:
                    return json.loads(hit)
            except redis.RedisError:
                pass

            result = fn(*args, **kwargs)

            try:
                _redis.setex(cache_key, ttl, json.dumps(result, default=str))
            except redis.RedisError:
                pass
            return result

        return wrapper

    return decorator


def _rows(sql: str, **params) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        return [dict(row._mapping) for row in result]


@router.get("/filters")
@cached("filters", ttl=3600)
def filter_options():
    """The values a user can actually filter by.

    Exists so the UI offers CHOICES instead of a free-text box. Typing a skill by hand
    means "spark", "Spark" and "PySpark" all silently return nothing, and the user has no
    way to know which spelling the warehouse uses — a filter that quietly returns zero
    results is worse than no filter.

    Cached for an hour: these change only when the pipeline runs.
    """
    return {
        "skills": [r["skill_name"] for r in _rows(
            "SELECT skill_name FROM analytics.dim_skill ORDER BY posting_count DESC"
        )],
        "regions": [r["region"] for r in _rows(
            "SELECT DISTINCT region FROM analytics.fact_job_posting "
            "WHERE region IS NOT NULL ORDER BY region"
        )],
        "seniorities": [r["seniority"] for r in _rows(
            "SELECT DISTINCT seniority FROM analytics.fact_job_posting "
            "WHERE seniority IS NOT NULL ORDER BY seniority"
        )],
        "pay_bands": ["above_market", "at_market", "below_market"],
        # Counts, not just labels. "Real job-board postings" next to a number tells the
        # user what the filter will actually give them before they click it — a filter
        # that turns out to return 12 rows is worth knowing about in advance.
        "source_counts": {
            r["kind"]: r["n"]
            for r in _rows(
                "SELECT CASE WHEN is_real THEN 'real' ELSE 'synthetic' END AS kind, "
                "COUNT(*) AS n FROM analytics.fact_job_posting GROUP BY 1"
            )
        },
    }


@router.get("/search")
def search_jobs(
    q: str | None = Query(None, description="free-text match on job title"),
    skill: str | None = Query(None, description="filter to postings requiring this skill"),
    region: str | None = None,
    seniority: str | None = None,
    remote_only: bool = False,
    min_salary: int | None = None,
    pay_band: str | None = Query(None, description="above_market | at_market | below_market"),
    source_type: str | None = Query(
        None, description="real = live job-board postings only | synthetic = generated only"
    ),
    prioritize_regions: str | None = Query(
        None,
        description="comma-separated regions to rank first, e.g. 'India,Remote'. Ranks, "
        "does not filter — set `region` to exclude outright.",
    ),
    prioritize_skills: str | None = Query(
        None, description="comma-separated skills; postings needing more of them rank higher",
    ),
    limit: int = Query(25, le=100),
    offset: int = 0,
):
    """Paginated job search over the fact table.

    Note every user value goes in as a BOUND PARAMETER (:q, :skill, ...), never string
    interpolation — that is what makes SQL injection impossible here, and it is the first
    thing an interviewer will look for in a query-building endpoint.
    """
    where, params = ["1=1"], {"limit": limit, "offset": offset}

    if q:
        where.append("f.title ILIKE :q")
        params["q"] = f"%{q}%"
    if region:
        where.append("f.region = :region")
        params["region"] = region
    if seniority:
        where.append("f.seniority = :seniority")
        params["seniority"] = seniority
    if remote_only:
        where.append("f.remote = true")
    if min_salary:
        where.append("f.salary >= :min_salary")
        params["min_salary"] = min_salary
    if pay_band:
        # Surfacing the ML output as a FILTER is what makes the model a feature
        # rather than a metric in a JSON file somewhere.
        where.append("f.pay_band = :pay_band")
        params["pay_band"] = pay_band
    if skill:
        where.append(
            "EXISTS (SELECT 1 FROM analytics.bridge_posting_skill b "
            "JOIN analytics.dim_skill s ON s.skill_id = b.skill_id "
            "WHERE b.posting_id = f.posting_id AND s.skill_name = :skill)"
        )
        params["skill"] = skill
    if source_type == "real":
        where.append("f.is_real = true")
    elif source_type == "synthetic":
        where.append("f.is_real = false")

    clause = " AND ".join(where)

    # ---- profile-driven relevance -------------------------------------------------
    # RANK by the profile rather than FILTER by it. A user in India should see Indian
    # roles first — clicking a US listing and being told "not available in your region"
    # is a wasted click — but hard-filtering would hide the US roles they are moving
    # towards, and the priority has to follow the profile when it changes rather than be
    # baked in here.
    #
    # Region is a plain equality test; skills need the bridge table, and counting matches
    # (rather than requiring one) means a posting wanting 3 of your skills outranks one
    # wanting 1, without excluding anything.
    # A bare "0" cannot be used as the no-op rank: Postgres reads a plain integer in
    # ORDER BY as a COLUMN POSITION, so `ORDER BY is_real DESC, 0 DESC` fails with
    # "ORDER BY position 0 is not in select list". The ranks are therefore added to the
    # ORDER BY only when they are actually requested, and NULL::int stands in for the
    # SELECT column so the response shape stays the same either way.
    order_terms = ["f.is_real DESC"]

    region_rank = "NULL::int"
    if prioritize_regions:
        regions = [r.strip() for r in prioritize_regions.split(",") if r.strip()]
        if regions:
            params["prioritize_regions"] = regions
            region_rank = "CASE WHEN f.region = ANY(:prioritize_regions) THEN 1 ELSE 0 END"
            order_terms.append("region_match DESC")

    skill_rank = "NULL::int"
    if prioritize_skills:
        skills = [s.strip() for s in prioritize_skills.split(",") if s.strip()]
        if skills:
            params["prioritize_skills"] = skills
            skill_rank = """(
                SELECT COUNT(*) FROM analytics.bridge_posting_skill pb
                JOIN analytics.dim_skill ps ON ps.skill_id = pb.skill_id
                WHERE pb.posting_id = f.posting_id AND ps.skill_name = ANY(:prioritize_skills)
            )"""
            # ORDER BY the output alias, not a second copy of the subquery. Repeating it
            # made Postgres evaluate a correlated count TWICE for every candidate row over
            # a 151k-row table, which is what exhausted shared memory. Postgres resolves
            # bare names in ORDER BY against the select list first, so this reuses the
            # already-computed value.
            order_terms.append("skill_matches DESC")

    order_terms.append("f.salary DESC NULLS LAST")
    order_by = ", ".join(order_terms)

    jobs = _rows(
        f"""
        SELECT f.posting_id, f.title, c.company_name, f.location, f.region,
               f.seniority, f.remote, f.salary, f.posted_month,
               f.predicted_salary, f.salary_vs_market, f.pay_band,
               f.is_real, f.source, f.url,
               {region_rank} AS region_match,
               {skill_rank} AS skill_matches
        FROM analytics.fact_job_posting f
        LEFT JOIN analytics.dim_company c ON c.company_id = f.company_id
        WHERE {clause}
        -- Real postings first, ALWAYS — including when no filter is applied. A real
        -- posting has a URL you can actually apply through; a synthetic one exists to
        -- give the pipeline volume. Sorting by salary alone buried every real posting
        -- under generated rows that happened to score higher, which made the job board
        -- look impressive and be useless.
        --
        -- Then the profile: your region, then how many of your skills the role wants.
        -- Salary is the last tiebreak, so the ordering people expect still holds inside
        -- each relevance group.
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
        """,
        **params,
    )

    total = _rows(
        f"SELECT COUNT(*) AS n FROM analytics.fact_job_posting f WHERE {clause}", **params
    )[0]["n"]

    return {"total": total, "limit": limit, "offset": offset, "jobs": jobs}


@router.get("/{posting_id}")
def get_job(posting_id: str):
    job = _rows(
        """
        SELECT f.posting_id, f.title, c.company_name, f.location, f.region,
               f.seniority, f.remote, f.salary, f.posted_month,
               f.predicted_salary, f.salary_vs_market, f.pay_band,
               f.is_real, f.source, f.url
        FROM analytics.fact_job_posting f
        LEFT JOIN analytics.dim_company c ON c.company_id = f.company_id
        WHERE f.posting_id = :posting_id
        """,
        posting_id=posting_id,
    )
    if not job:
        return {"error": "not found"}

    skills = _rows(
        """
        SELECT s.skill_name
        FROM analytics.bridge_posting_skill b
        JOIN analytics.dim_skill s ON s.skill_id = b.skill_id
        WHERE b.posting_id = :posting_id
        ORDER BY s.skill_name
        """,
        posting_id=posting_id,
    )
    return {**job[0], "required_skills": [s["skill_name"] for s in skills]}
