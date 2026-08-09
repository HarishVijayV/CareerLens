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
    include_sample_postings: bool = False,
) -> str:
    """Search LIVE job-board postings from the warehouse.

    Real postings only by default, and this is a correctness fix rather than a preference.

    The docstring here used to claim "real postings" while the call passed no provenance
    filter at all, so the agent searched the synthetic rows too. Because the warehouse
    orders real-first, that stayed invisible until a filter matched fewer than `limit` real
    rows — then the agent quietly padded its recommendations with generated ones. An
    observed run advised applying to "Johnson, Cooper and Reilly" and "Klein PLC", both
    Faker output, with confident reasoning attached.

    That is the worst failure mode this system has: not a wrong answer, but a plausible
    one that wastes someone's actual job search. Market-wide questions ("what pays most
    across the market?") legitimately want the full sample, which is what the escape hatch
    is for — but recommending a job to apply to must never return something unapplyable.
    """
    params = {k: v for k, v in locals().items() if v not in (None, False)}
    params.pop("include_sample_postings", None)
    if not include_sample_postings:
        params["source_type"] = "real"
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


def get_resume_latex(user_id: str) -> str:
    """Fetch the LaTeX source of the active resume, if there is one."""
    resp = httpx.get(
        f"{AUTH_SERVICE_URL}/resume/active",
        headers={"X-User-Id": user_id, "X-Internal-Call": "agent-service"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    active = resp.json()

    if not active.get("content_latex"):
        return json.dumps(
            {
                "has_latex": False,
                "note": "No LaTeX source. Editing plain text only; a .tex upload (or a "
                "convert-to-LaTeX step) is needed before a compilable document exists.",
            }
        )
    return json.dumps({"has_latex": True, "latex": active["content_latex"]})


def save_tailored_resume(
    user_id: str,
    resume_text: str,
    label: str | None = None,
    resume_latex: str | None = None,
    change_summary: str | None = None,
    tailored_for_posting_id: str | None = None,
) -> str:
    """Save a rewritten resume as a NEW version.

    Never an in-place overwrite: the previous version stays intact and restorable, which
    is what makes letting a model edit your resume a safe thing to do at all.
    """
    resp = httpx.post(
        f"{AUTH_SERVICE_URL}/resume/agent-save",
        json={
            "content_text": resume_text,
            "content_latex": resume_latex,
            "label": label,
            "change_summary": change_summary,
            "tailored_for_posting_id": tailored_for_posting_id,
        },
        headers={"X-User-Id": user_id, "X-Internal-Call": "agent-service"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    saved = resp.json()
    return json.dumps(
        {
            "saved": True,
            "version_id": saved.get("id"),
            "label": saved.get("label"),
            "characters": len(resume_text),
        }
    )


# ------------------------------------------------------------------------------ dispatch
TOOL_IMPLEMENTATIONS = {
    "search_jobs": search_jobs,
    "get_job": get_job,
    "get_market_analytics": get_market_analytics,
    "get_profile": get_profile,
    "get_resume": get_resume,
    "get_resume_latex": get_resume_latex,
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
