"""
Tool implementations + the dispatcher.

A "tool" is a plain Python function plus a JSON-schema description of its arguments. The
LLM never executes anything — it only ever REQUESTS a tool by name with arguments, and
this module decides whether to run it. "The model requests, your code decides" is the
core idea behind agent security (docs/AGENTIC_AI.md).

Least privilege in practice: each agent is handed only the tool SCHEMAS it needs (those
live next to each agent), while the implementations live here. The email agent physically
cannot write a resume, because it was never given that tool.
"""
from __future__ import annotations

import json
import os

import httpx

JOBS_SERVICE_URL = os.getenv("JOBS_SERVICE_URL", "http://jobs-service:8000")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000")

_TIMEOUT = 20.0


# --------------------------------------------------------------------- job/profile data
def search_jobs(
    q: str | None = None,
    skill: str | None = None,
    seniority: str | None = None,
    remote_only: bool = False,
    min_salary: int | None = None,
    limit: int = 10,
) -> str:
    """Search real postings from the warehouse."""
    params = {k: v for k, v in locals().items() if v not in (None, False)}
    params["limit"] = min(limit, 25)
    resp = httpx.get(f"{JOBS_SERVICE_URL}/jobs/search", params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return json.dumps(resp.json())


def get_job(posting_id: str) -> str:
    """Fetch one posting including its required skills."""
    resp = httpx.get(f"{JOBS_SERVICE_URL}/jobs/{posting_id}", timeout=_TIMEOUT)
    resp.raise_for_status()
    return json.dumps(resp.json())


def get_market_analytics(metric: str = "top-skills") -> str:
    """Read aggregate market data: overview | top-skills | salary-by-seniority |
    salary-by-region | postings-by-month | skill-premium."""
    allowed = {
        "overview",
        "top-skills",
        "salary-by-seniority",
        "salary-by-region",
        "postings-by-month",
        "skill-premium",
    }
    # Allow-list, not free-form URL building: without this an LLM could construct a path
    # that hits an unintended endpoint. Validating tool arguments in code — never trusting
    # what the model passed — is the practical half of "your code decides".
    if metric not in allowed:
        return json.dumps({"error": f"unknown metric; choose one of {sorted(allowed)}"})

    resp = httpx.get(f"{JOBS_SERVICE_URL}/analytics/{metric}", timeout=_TIMEOUT)
    resp.raise_for_status()
    return json.dumps(resp.json())


def get_profile(user_id: str) -> str:
    """The user's profile: skills, target roles, resume text, preferences."""
    resp = httpx.get(
        f"{AUTH_SERVICE_URL}/profile",
        headers={"X-User-Id": user_id, "X-Internal-Call": "agent-service"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps(resp.json())


def get_resume(user_id: str) -> str:
    """Just the resume portion of the profile."""
    profile = json.loads(get_profile(user_id))
    return json.dumps(
        {
            "resume_text": profile.get("resume_text"),
            "resume_latex_present": bool(profile.get("resume_latex")),
            "skills": profile.get("skills"),
            "headline": profile.get("headline"),
        }
    )


def save_tailored_resume(user_id: str, resume_text: str) -> str:
    """Persist a rewritten resume back to the user's profile."""
    resp = httpx.patch(
        f"{AUTH_SERVICE_URL}/profile",
        json={"resume_text": resume_text},
        headers={"X-User-Id": user_id, "X-Internal-Call": "agent-service"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return json.dumps({"saved": True, "characters": len(resume_text)})


# ------------------------------------------------------------------------------ dispatch
TOOL_IMPLEMENTATIONS = {
    "search_jobs": search_jobs,
    "get_job": get_job,
    "get_market_analytics": get_market_analytics,
    "get_profile": get_profile,
    "get_resume": get_resume,
    "save_tailored_resume": save_tailored_resume,
}


def dispatch_tool_call(name: str, arguments: dict, allowed_tools: set[str] | None = None) -> str:
    """Run a tool the model asked for.

    `allowed_tools` enforces least privilege at execution time as well as at prompt time.
    Restricting the schemas an agent SEES is a soft boundary (a model can hallucinate a
    name it was never given); checking again here is the hard one.
    """
    if allowed_tools is not None and name not in allowed_tools:
        return json.dumps({"error": f"Tool '{name}' is not permitted for this agent."})

    fn = TOOL_IMPLEMENTATIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        return fn(**arguments)
    except TypeError as exc:
        # Wrong/missing arguments — hand the error back so the model can correct itself.
        return json.dumps({"error": f"Bad arguments for {name}: {exc}"})
    except httpx.HTTPError as exc:
        return json.dumps({"error": f"Upstream service call failed: {exc}"})
    except Exception as exc:  # noqa: BLE001 — never let a tool crash the whole request
        return json.dumps({"error": str(exc)})
