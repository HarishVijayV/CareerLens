"""
The SAME two agents from app/agents/, re-implemented as a LangGraph graph, so you have a
real answer ready for "have you used LangGraph / what does it buy you over rolling your
own." Compare this file to app/agents/orchestrator.py + resume_matcher.py side by side —
that comparison IS the interview answer.

What LangGraph gives you here that the hand-rolled version doesn't bother with:
- a typed, shared `state` object every node reads/writes (no manually threading dicts)
- built-in graph visualization (`graph.get_graph().draw_mermaid()`) — great for docs
- a standard place to bolt on retries/checkpointing/persistence later without rewriting
  the agents themselves, only the wiring around them

What it costs: another dependency and another mental model to hold — worth it once a
graph gets past a handful of nodes, overkill for two.
"""
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.agents.skill_extractor import extract_skills
from app.tools.registry import get_job, get_resume


class JobMatchState(TypedDict):
    job_id: str
    user_id: str
    job_description: str
    extracted_skills: dict
    resume_summary: str
    final_report: str


def _fetch_job_node(state: JobMatchState) -> dict:
    import json

    job = json.loads(get_job(state["job_id"]))
    return {"job_description": job["description"]}


def _extract_skills_node(state: JobMatchState) -> dict:
    return {"extracted_skills": extract_skills(state["job_description"])}


def _fetch_resume_node(state: JobMatchState) -> dict:
    import json

    resume = json.loads(get_resume(state["user_id"]))
    return {"resume_summary": ", ".join(resume["skills"])}


def _combine_node(state: JobMatchState) -> dict:
    required = set(state["extracted_skills"].get("required_skills", []))
    have = {s.strip() for s in state["resume_summary"].split(",")}
    missing = sorted(required - have)
    report = (
        f"Required skills: {sorted(required)}. Your skills: {sorted(have)}. "
        f"Gaps to address: {missing or 'none — good match!'}"
    )
    return {"final_report": report}


def build_graph():
    graph = StateGraph(JobMatchState)
    graph.add_node("fetch_job", _fetch_job_node)
    graph.add_node("extract_skills", _extract_skills_node)
    graph.add_node("fetch_resume", _fetch_resume_node)
    graph.add_node("combine", _combine_node)

    graph.set_entry_point("fetch_job")
    graph.add_edge("fetch_job", "extract_skills")
    graph.add_edge("extract_skills", "fetch_resume")
    graph.add_edge("fetch_resume", "combine")
    graph.add_edge("combine", END)

    return graph.compile()


def run_job_match(user_id: str, job_id: str) -> str:
    app_graph = build_graph()
    result = app_graph.invoke({"user_id": user_id, "job_id": job_id})
    return result["final_report"]
