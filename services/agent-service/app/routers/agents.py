from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.agents.definitions import AGENTS
from app.agents.orchestrator import orchestrate, route_explicit, route_with_llm
from app.langgraph_impl.graph import run_job_match_graph

router = APIRouter(tags=["agents"])


@router.get("/agents")
def list_agents():
    """What each agent does and what it's allowed to touch — the capability model, served
    as data so the UI (and you, in an interview) can show it without reading source."""
    return {
        name: {
            "description": cfg["description"],
            "tools": [t["name"] for t in cfg["tools"]] or ["(no tools — pure LLM)"],
        }
        for name, cfg in AGENTS.items()
    }


class AskRequest(BaseModel):
    message: str
    agent: str | None = None   # name one to skip routing entirely
    # "auto"        -> a planner picks ONE specialist (cheap, predictable)
    # "orchestrate" -> the orchestrator may call SEVERAL and synthesise (costlier, richer)
    mode: str = "auto"


@router.post("/agents/ask")
def ask(request: AskRequest, x_user_id: str | None = Header(default=None)):
    """Main entrypoint. Passing `agent` routes deterministically; omitting it uses the
    LLM router (see app/agents/orchestrator.py for why both exist)."""
    # The user id comes from the gateway's verified header, never from the request body —
    # otherwise anyone could ask for someone else's profile by typing their id.
    message = request.message
    if x_user_id:
        message = f"[user_id: {x_user_id}]\n{message}"

    try:
        if request.agent:
            run = route_explicit(request.agent, message)
            return {
                "mode": "explicit",
                "agent": request.agent,
                "answer": run.final_answer,
                "tool_calls": run.tool_calls,
                "iterations": run.iterations,
                "stopped_early": run.stopped_early,
            }
        if request.mode == "orchestrate":
            return orchestrate(message)
        return route_with_llm(message)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        # Most common cause by far: missing/invalid LLM API key. Say that plainly instead
        # of leaking a stack trace to the browser.
        raise HTTPException(
            status_code=502,
            detail=f"Agent call failed ({type(exc).__name__}): {exc}. "
            "Check LLM_PROVIDER and the matching API key in infra/.env.",
        )


class JobMatchRequest(BaseModel):
    user_id: str
    posting_id: str


@router.post("/agents/langgraph/job-match")
def langgraph_job_match(request: JobMatchRequest):
    """The same match logic expressed as a LangGraph graph. Compare with
    app/agents/orchestrator.py — that comparison is the 'from scratch vs framework'
    talking point in docs/AGENTIC_AI.md."""
    return run_job_match_graph(request.user_id, request.posting_id)
