"""
Narrowest possible agent: turns a messy job description into structured data. No tools —
pure LLM extraction — because it needs nothing except the text it's given. Keeping its
prompt tiny and its job singular is what makes it accurate; see the "why narrow sub-agents
beat one giant agent" section of docs/AGENTIC_AI.md.
"""
import json

from app.llm.provider import get_llm_provider

SYSTEM_PROMPT = """You extract structured requirements from a job posting description.
Respond with ONLY a JSON object, no prose, matching this shape:
{"title": str, "seniority": "junior"|"mid"|"senior"|"unknown",
 "required_skills": [str], "location": str|null, "remote": bool}
"""


def extract_skills(job_description: str) -> dict:
    provider = get_llm_provider()
    response = provider.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": job_description},
        ]
    )
    try:
        return json.loads(response.content or "{}")
    except json.JSONDecodeError:
        # Models occasionally wrap JSON in prose despite instructions — fail soft with a
        # clearly-marked partial result rather than a 500, so the orchestrator can decide
        # what to do next instead of the whole request crashing.
        return {"error": "could_not_parse", "raw": response.content}
