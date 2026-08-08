"""
MCP server — exposes CareerLens's JOB-MARKET data to any MCP client (Claude Desktop,
Cursor, or any other), so the dataset this pipeline produces is usable outside this app.

═══════════════════════════════════════════════════════════════════════════════
PRIVACY BOUNDARY — the most important design decision in this file
═══════════════════════════════════════════════════════════════════════════════

This server exposes ONLY aggregate, non-personal job-market data:

    EXPOSED          search_jobs, job_details, market_overview, top_skills,
                     skill_premium, salary_by_seniority
    NEVER EXPOSED    email, resume, applications, profile, user accounts

That separation is enforced STRUCTURALLY, not by convention. This container runs on an
isolated Docker network (`mcp-net`) shared with jobs-service and NOTHING else —
auth-service, gateway, postgres and redis do not even resolve from here. It also holds no
database credentials.

That network isolation is load-bearing, not decorative. auth-service trusts the
`X-User-Id` header as proven identity (safe, because only the gateway can set it), so
anything sharing its network could forge that header and read any user's resume or
inbox. Docker Compose puts every service on one network by default, which quietly made
this server a viable path to exactly that — until the networks were split. Verified by
attempting the connection: auth-service now fails with ConnectError.

The alternative — one server exposing everything, with a flag deciding what's personal —
is one bad conditional away from leaking an inbox. Two services with different reach
can't have that bug.

Why an MCP server at all: the internal agents already call these tools directly, in
process. MCP earns its place by making the SAME data available to clients that aren't
part of this codebase — that's a genuinely different capability, not a re-wrapping.
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

JOBS_SERVICE_URL = os.getenv("JOBS_SERVICE_URL", "http://jobs-service:8000")
TIMEOUT = 20.0

mcp = FastMCP(
    "careerlens-jobs",
    instructions=(
        "Job-market intelligence built from a Spark/dbt pipeline over ~200k job postings. "
        "Provides skill demand, salary benchmarks by seniority and region, which skills "
        "carry a pay premium, and full-text job search. Contains no personal data."
    ),
)


def _get(path: str, **params) -> dict | list:
    clean = {k: v for k, v in params.items() if v is not None}
    response = httpx.get(f"{JOBS_SERVICE_URL}{path}", params=clean, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


@mcp.tool()
def search_jobs(
    title: str | None = None,
    skill: str | None = None,
    seniority: str | None = None,
    region: str | None = None,
    min_salary: int | None = None,
    remote_only: bool = False,
    pay_band: str | None = None,
    limit: int = 10,
) -> dict:
    """Search job postings in the CareerLens warehouse.

    Args:
        title: free-text match on job title, e.g. "Data Engineer"
        skill: require this exact skill, e.g. "Spark"
        seniority: junior | mid | senior
        region: e.g. "North America", "Europe", "India", "Remote"
        min_salary: minimum annual salary
        remote_only: only remote roles
        pay_band: above_market | at_market | below_market (from the ML salary model)
        limit: max results, capped at 25
    """
    return _get(
        "/jobs/search",
        q=title,
        skill=skill,
        seniority=seniority,
        region=region,
        min_salary=min_salary,
        remote_only=remote_only or None,
        pay_band=pay_band,
        limit=min(limit, 25),
    )


@mcp.tool()
def job_details(posting_id: str) -> dict:
    """Fetch one job posting in full, including its complete required-skills list."""
    return _get(f"/jobs/{posting_id}")


@mcp.tool()
def market_overview() -> dict:
    """Headline job-market statistics: total postings, companies, average salary,
    remote share, and how many distinct skills are tracked."""
    return _get("/analytics/overview")


@mcp.tool()
def top_skills(limit: int = 15) -> list:
    """The most in-demand skills, ranked by how many postings require each one."""
    return _get("/analytics/top-skills", limit=limit)


@mcp.tool()
def skill_premium(limit: int = 15) -> list:
    """Which skills actually pay above average.

    Returns each skill's average salary and its premium versus the overall average —
    the most useful query here for deciding what to learn next.
    """
    return _get("/analytics/skill-premium", limit=limit)


@mcp.tool()
def salary_by_seniority() -> list:
    """Average salary and posting count for each seniority level."""
    return _get("/analytics/salary-by-seniority")


@mcp.tool()
def salary_by_region() -> list:
    """Average salary and posting count for each region."""
    return _get("/analytics/salary-by-region")


@mcp.tool()
def hiring_seasonality() -> list:
    """Postings per month across the year — shows when hiring peaks and dips."""
    return _get("/analytics/postings-by-month")


if __name__ == "__main__":
    # streamable-http (not stdio) because this runs as a container alongside the rest of
    # the stack. stdio suits a server the client launches as a subprocess; a long-lived
    # networked service needs an HTTP transport.
    mcp.settings.host = "0.0.0.0"   # bind all interfaces, or the port mapping is useless
    mcp.settings.port = 8005
    mcp.run(transport="streamable-http")
