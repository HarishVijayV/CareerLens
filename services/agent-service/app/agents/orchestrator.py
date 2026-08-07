"""
The planner. Its only job is: read what the user wants, decide which sub-agent(s) handle
it, call them, and combine the results. It has NO tools of its own — delegation only.
This mirrors a real engineering-manager pattern: the planner doesn't do the work, it
routes it to the specialist who can.

Only two intents are wired end-to-end right now (extract_skills, match_resume) — the rest
(tailor_resume, classify_email, funnel_insight) are documented in docs/AGENTIC_AI.md and
scheduled in docs/ROADMAP.md Phase 5-6, once their supporting infra (resume storage,
Gmail OAuth) exists. Wiring a new intent here is always the same three lines: import the
sub-agent, add a branch, done — that's the payoff of the narrow-agent design.
"""
from app.agents.resume_matcher import match_resume_to_job
from app.agents.skill_extractor import extract_skills


def handle_request(intent: str, payload: dict) -> dict:
    if intent == "extract_skills":
        return {"result": extract_skills(payload["job_description"])}

    if intent == "match_resume":
        return {"result": match_resume_to_job(payload["user_id"], payload["job_id"])}

    return {"error": f"Unknown or not-yet-implemented intent: {intent}"}
