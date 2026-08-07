"""
A "tool" here is just a plain Python function plus a JSON-schema description of its
arguments. The LLM never executes these — it only ever asks (by name + arguments) for
one to be run; OUR code decides whether that's allowed and actually runs it. That
distinction ("the model requests, your code decides") is the core idea behind agent security —
see docs/AGENTIC_AI.md.

Each sub-agent gets its OWN small tool list (least privilege) — defined next to that
agent, not here. This file only holds tool IMPLEMENTATIONS shared across agents plus the
dispatch helper.
"""
from __future__ import annotations

import json

# Phase 2+ (see docs/ROADMAP.md) wires these to real Postgres queries. For now they
# return small, obviously-fake data so the tool-calling loop can be exercised end to end
# before the data pipeline exists.


def get_resume(user_id: str) -> str:
    return json.dumps(
        {
            "user_id": user_id,
            "bullets": [
                "Designed distributed pipeline for 15M+ records using Hadoop, MapReduce, "
                "and Spark MLlib with data visualization dashboards; achieved 40% "
                "computation time reduction vs. serial baseline."
            ],
            "skills": ["Python", "Spark", "Hadoop", "SQL", "AWS"],
        }
    )


def get_job(job_id: str) -> str:
    return json.dumps(
        {
            "job_id": job_id,
            "title": "Data Engineer",
            "description": "Looking for a Data Engineer with Spark, Airflow, Kafka, and "
            "cloud experience (AWS or GCP). dbt a plus.",
        }
    )


TOOL_IMPLEMENTATIONS = {
    "get_resume": get_resume,
    "get_job": get_job,
}


def dispatch_tool_call(name: str, arguments: dict) -> str:
    fn = TOOL_IMPLEMENTATIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return fn(**arguments)
    except Exception as exc:  # noqa: BLE001 — deliberately broad: feed the error back to
        # the LLM as a tool result instead of crashing the request. The model can often
        # retry with corrected arguments once it sees the error message.
        return json.dumps({"error": str(exc)})
