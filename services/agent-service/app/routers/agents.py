from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.orchestrator import handle_request
from app.langgraph_impl.graph import run_job_match

router = APIRouter(tags=["agents"])


class OrchestratorRequest(BaseModel):
    intent: str  # "extract_skills" | "match_resume" | ...
    payload: dict


@router.post("/orchestrator")
def orchestrator(request: OrchestratorRequest):
    """The hand-rolled path — see app/agents/orchestrator.py."""
    return handle_request(request.intent, request.payload)


class JobMatchRequest(BaseModel):
    user_id: str
    job_id: str


@router.post("/langgraph/job-match")
def langgraph_job_match(request: JobMatchRequest):
    """The LangGraph path — same underlying agents, graph-based wiring. Compare this
    endpoint's implementation to /orchestrator's for the "from scratch vs framework"
    story described in docs/AGENTIC_AI.md."""
    return {"result": run_job_match(request.user_id, request.job_id)}
