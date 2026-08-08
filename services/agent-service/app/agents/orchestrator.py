"""
The planner. Its only job: work out which specialist should handle a request, hand off,
and return the result. It has no tools of its own — delegation only.

Two routing modes, and the difference is worth understanding:

  * route_explicit()  — the caller names the agent. Deterministic, free, instant. Use it
                        when the UI already knows the intent (a "Tailor my resume" button
                        is not ambiguous).
  * route_with_llm()  — an LLM reads free-form text and picks the agent. Needed for a
                        chat box where the user could ask anything.

Real systems use both. Spending an LLM call to classify something the button already told
you is waste; the interesting engineering is knowing which situation you're in.
"""
from __future__ import annotations

import json

from app.agents.base import Agent, AgentRun
from app.agents.definitions import AGENTS
from app.llm.provider import get_llm_provider

_ROUTER_PROMPT = """You route a user's request to exactly one specialist agent.

Available agents:
{catalog}

Respond with ONLY a JSON object: {{"agent": "<name>", "reason": "<short reason>"}}
Pick the single best fit. If nothing fits well, choose "market_analyst"."""


def build_agent(name: str) -> Agent:
    config = AGENTS[name]
    return Agent(name=name, system_prompt=config["system_prompt"], tools=config["tools"])


def route_explicit(agent_name: str, user_message: str) -> AgentRun:
    if agent_name not in AGENTS:
        raise KeyError(f"Unknown agent '{agent_name}'. Available: {sorted(AGENTS)}")
    return build_agent(agent_name).run(user_message)


def choose_agent(user_message: str) -> dict:
    """LLM-based routing — the 'planner' step of a multi-agent system."""
    catalog = "\n".join(f"- {name}: {cfg['description']}" for name, cfg in AGENTS.items())
    provider = get_llm_provider()

    response = provider.chat(
        [
            {"role": "system", "content": _ROUTER_PROMPT.format(catalog=catalog)},
            {"role": "user", "content": user_message},
        ]
    )

    try:
        choice = json.loads((response.content or "").strip().strip("`"))
        if choice.get("agent") in AGENTS:
            return choice
    except json.JSONDecodeError:
        pass

    # Routing must never hard-fail the request — a sensible default beats a 500.
    return {"agent": "market_analyst", "reason": "router fallback (unparseable response)"}


def route_with_llm(user_message: str) -> dict:
    choice = choose_agent(user_message)
    run = route_explicit(choice["agent"], user_message)
    return {
        "agent": choice["agent"],
        "routing_reason": choice.get("reason"),
        "answer": run.final_answer,
        "tool_calls": run.tool_calls,
        "iterations": run.iterations,
        "stopped_early": run.stopped_early,
    }
