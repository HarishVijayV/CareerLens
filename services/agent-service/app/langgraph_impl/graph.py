"""
The same job-matching flow as the hand-rolled agents, expressed as a LangGraph graph — so
you can answer "have you used LangGraph, and what does it actually buy you?" by pointing
at both implementations.

Read this next to app/agents/base.py. That comparison IS the interview answer:

  Hand-rolled (base.py)     one while-loop; the MODEL decides the path at runtime by
                            choosing tools. Maximum flexibility, you own every detail.
  LangGraph (this file)     an explicit graph; YOU decide the path, the model fills in
                            each node. Predictable, inspectable, easy to visualize.

Which is right depends on the job. Open-ended requests ("find me something") want the
model steering. A fixed business process ("fetch job -> fetch profile -> compare ->
report") wants the graph, because you WANT the same steps every time and you want to see
them on a diagram.

What LangGraph adds: typed shared state, built-in visualization
(build_graph().get_graph().draw_mermaid()), and a standard place to add
checkpointing/retries later without touching agent logic.
"""
from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agents.base import Agent
from app.agents.definitions import AGENTS
from app.tools.registry import get_job, get_profile


class JobMatchState(TypedDict, total=False):
    user_id: str
    posting_id: str
    job: dict
    profile: dict
    extracted: dict
    matched_skills: list[str]
    missing_skills: list[str]
    match_score: int
    report: str


def _fetch_job_node(state: JobMatchState) -> dict:
    return {"job": json.loads(get_job(state["posting_id"]))}


def _fetch_profile_node(state: JobMatchState) -> dict:
    return {"profile": json.loads(get_profile(state["user_id"]))}


def _extract_requirements_node(state: JobMatchState) -> dict:
    """The one node that actually calls an LLM — reusing the SAME skill_extractor
    definition the hand-rolled path uses, so the two implementations can't drift apart."""
    job = state["job"]
    config = AGENTS["skill_extractor"]
    agent = Agent("skill_extractor", config["system_prompt"], config["tools"])

    description = f"{job.get('title', '')}\nRequired skills: {job.get('required_skills', [])}"
    run = agent.run(description)

    try:
        return {"extracted": json.loads(run.final_answer.strip().strip("`"))}
    except json.JSONDecodeError:
        # Fall back to the structured skills we already have from the warehouse — the
        # graph should degrade, not collapse, when the model returns unparseable text.
        return {"extracted": {"required_skills": job.get("required_skills", [])}}


def _compare_node(state: JobMatchState) -> dict:
    """Deterministic comparison in plain Python — no LLM. Set arithmetic is exact and
    free; asking a model to do it would be slower, cost money, and occasionally get it
    wrong. Use the LLM for language, use code for logic."""
    required = {s.lower() for s in state["extracted"].get("required_skills", [])}
    have = {s.strip().lower() for s in (state["profile"].get("skills") or "").split(",") if s.strip()}

    matched = sorted(required & have)
    missing = sorted(required - have)
    score = round(len(matched) / len(required) * 100) if required else 0

    return {"matched_skills": matched, "missing_skills": missing, "match_score": score}


def _report_node(state: JobMatchState) -> dict:
    job = state["job"]
    return {
        "report": (
            f"Match score: {state['match_score']}% for '{job.get('title')}' "
            f"at {job.get('company_name')}.\n"
            f"You have: {', '.join(state['matched_skills']) or 'none of the listed skills'}.\n"
            f"Gaps: {', '.join(state['missing_skills']) or 'none — strong match'}."
        )
    }


def build_graph():
    graph = StateGraph(JobMatchState)
    graph.add_node("fetch_job", _fetch_job_node)
    graph.add_node("fetch_profile", _fetch_profile_node)
    graph.add_node("extract_requirements", _extract_requirements_node)
    graph.add_node("compare", _compare_node)
    graph.add_node("report", _report_node)

    graph.set_entry_point("fetch_job")
    graph.add_edge("fetch_job", "fetch_profile")
    graph.add_edge("fetch_profile", "extract_requirements")
    graph.add_edge("extract_requirements", "compare")
    graph.add_edge("compare", "report")
    graph.add_edge("report", END)

    return graph.compile()


def run_job_match_graph(user_id: str, posting_id: str) -> dict:
    result = build_graph().invoke({"user_id": user_id, "posting_id": posting_id})
    return {
        "match_score": result.get("match_score"),
        "matched_skills": result.get("matched_skills"),
        "missing_skills": result.get("missing_skills"),
        "report": result.get("report"),
        "implementation": "langgraph",
    }


def render_mermaid() -> str:
    """Renders the graph as a Mermaid diagram — paste into docs or a README and the
    architecture picture stays in sync with the code, because it IS the code."""
    return build_graph().get_graph().draw_mermaid()
