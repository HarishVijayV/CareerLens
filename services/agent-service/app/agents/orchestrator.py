"""
Three ways to get from a question to an answer, in increasing order of power and cost.

  1. route_explicit()   the caller names the agent. Deterministic, zero routing cost.
                        Right when the UI already knows the intent — a "Tailor my resume"
                        button is not ambiguous, and spending an LLM call to classify it
                        would be pure waste.

  2. route_with_llm()   a planner reads the question and picks ONE specialist. This is
                        ROUTING. Cheap (one extra call) and predictable, but it can only
                        ever produce what a single agent can produce.

  3. orchestrate()      the orchestrator can call SEVERAL sub-agents — each as a tool —
                        and then write an answer from their combined results. This is
                        ORCHESTRATION, and it's what a question like "match jobs to my
                        resume AND suggest the top 3" actually needs: one agent knows the
                        job market, another knows the resume, and neither alone can answer.

The distinction matters and is worth being able to state: routing PICKS a worker,
orchestration COMBINES workers. Most systems described as "multi-agent" are only routing.

Cost is the reason all three exist rather than just the last one. Each sub-agent call is
its own full tool-calling loop, so orchestration multiplies LLM calls — a 3-delegation
answer can be 10+ calls where routing would be 4. Use the cheapest mode that can answer
the question.
"""
from __future__ import annotations

import json

from app.agents.base import Agent, AgentRun
from app.agents.definitions import AGENTS
from app.llm.provider import get_llm_provider

# Sub-agents the orchestrator is allowed to delegate to. skill_extractor is excluded on
# purpose: it works on a job description handed to it directly, so it has nothing useful
# to contribute to a free-form user question.
DELEGATABLE = ["job_matcher", "resume_tailor", "market_analyst"]

# Hard ceiling on delegations per request. Without it a confused orchestrator can loop
# through every agent repeatedly, and each delegation is a full nested LLM loop.
MAX_DELEGATIONS = 4

_ROUTER_PROMPT = """You route a user's request to exactly one specialist agent.

Available agents:
{catalog}

Respond with ONLY a JSON object: {{"agent": "<name>", "reason": "<short reason>"}}
Pick the single best fit. If nothing fits well, choose "market_analyst"."""

_ORCHESTRATOR_PROMPT = """You are the orchestrator for a job-search assistant.

You do NOT answer from your own knowledge and you have no data of your own. You answer by
DELEGATING to specialists and combining what they return.

Specialists available to you:
{catalog}

How to work:
1. Decide which specialist(s) the question needs. Many questions need more than one — for
   example "how do I match this job and what should I change?" needs both the job matcher
   AND the resume tailor.
2. Call them. You may call several, and you may use one's output to inform the next.
3. Write ONE combined answer for the user. Do not simply concatenate their replies —
   synthesise them into a single coherent response.

Rules:
- Never invent facts. Everything you state must come from a specialist's response.
- Delegate at most {max_delegations} times.
- If one specialist is clearly enough, use only that one. Delegation costs real time and
  money, so don't call agents you don't need."""


def build_agent(name: str) -> Agent:
    config = AGENTS[name]
    return Agent(name=name, system_prompt=config["system_prompt"], tools=config["tools"])


# ---------------------------------------------------------------- 1. explicit
def route_explicit(agent_name: str, user_message: str) -> AgentRun:
    if agent_name not in AGENTS:
        raise KeyError(f"Unknown agent '{agent_name}'. Available: {sorted(AGENTS)}")
    return build_agent(agent_name).run(user_message)


# ---------------------------------------------------------------- 2. routing
def choose_agent(user_message: str) -> dict:
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

    # Routing must never hard-fail a request — a sensible default beats a 500.
    return {"agent": "market_analyst", "reason": "router fallback (unparseable response)"}


def route_with_llm(user_message: str) -> dict:
    choice = choose_agent(user_message)
    run = route_explicit(choice["agent"], user_message)
    return {
        "mode": "routed",
        "agent": choice["agent"],
        "routing_reason": choice.get("reason"),
        "answer": run.final_answer,
        "tool_calls": run.tool_calls,
        "iterations": run.iterations,
        "stopped_early": run.stopped_early,
    }


# ---------------------------------------------------------------- 3. orchestration
def _delegation_tools() -> list[dict]:
    """Expose each sub-agent as a TOOL the orchestrator can call.

    This is the whole trick, and it's why no new machinery was needed: an agent that can
    call tools can call other agents, because from its point of view a sub-agent IS just a
    tool that happens to be expensive and intelligent. The same loop in agents/base.py
    drives both levels.
    """
    return [
        {
            "name": f"ask_{name}",
            "description": f"Delegate to the {name} specialist. {AGENTS[name]['description']}",
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "A complete, self-contained question for this "
                        "specialist. It cannot see the user's original wording or what "
                        "other specialists returned, so include everything it needs.",
                    }
                },
                "required": ["question"],
            },
        }
        for name in DELEGATABLE
    ]


def orchestrate(user_message: str) -> dict:
    """Delegate to one or more sub-agents, then synthesise a single answer."""
    provider = get_llm_provider()
    catalog = "\n".join(f"- {name}: {AGENTS[name]['description']}" for name in DELEGATABLE)

    tools = _delegation_tools()
    messages = [
        {
            "role": "system",
            "content": _ORCHESTRATOR_PROMPT.format(
                catalog=catalog, max_delegations=MAX_DELEGATIONS
            ),
        },
        {"role": "user", "content": user_message},
    ]

    delegations: list[dict] = []
    all_tool_calls: list[dict] = []

    for _ in range(MAX_DELEGATIONS + 1):
        response = provider.chat(messages, tools=tools)

        if not response.tool_calls:
            return {
                "mode": "orchestrated",
                "agent": "orchestrator",
                "routing_reason": (
                    f"delegated to {len(delegations)} specialist"
                    f"{'' if len(delegations) == 1 else 's'}: "
                    + ", ".join(d["agent"] for d in delegations)
                    if delegations
                    else "answered without delegating"
                ),
                "answer": response.content or "",
                "delegations": delegations,
                "tool_calls": all_tool_calls,
                "iterations": len(delegations),
                "stopped_early": False,
            }

        messages.append(provider.assistant_tool_call_message(response))

        for call in response.tool_calls:
            agent_name = call.name.removeprefix("ask_")
            question = call.arguments.get("question", user_message)

            if agent_name not in DELEGATABLE:
                messages.append(
                    provider.tool_result_message(
                        call, json.dumps({"error": f"Unknown specialist: {agent_name}"})
                    )
                )
                continue

            # An observed run delegated to job_matcher twice in one answer. A specialist
            # asked the same thing returns the same thing, so the repeat is pure cost —
            # and it eats the delegation budget that a DIFFERENT specialist needed.
            already = next(
                (d for d in delegations if d["agent"] == agent_name and d["question"] == question),
                None,
            )
            if already:
                messages.append(
                    provider.tool_result_message(
                        call,
                        json.dumps({
                            "note": f"Already asked {agent_name} this exact question.",
                            "answer": already["answer"],
                        }),
                    )
                )
                continue

            if len(delegations) >= MAX_DELEGATIONS:
                messages.append(
                    provider.tool_result_message(
                        call,
                        json.dumps({"error": "Delegation limit reached — answer with what you have."}),
                    )
                )
                continue

            # The nested run. Its own tool calls are surfaced too, so the UI can show the
            # full two-level trace rather than an opaque "the orchestrator did something".
            sub_run = route_explicit(agent_name, question)

            delegations.append(
                {
                    "agent": agent_name,
                    "question": question,
                    "answer": sub_run.final_answer,
                    "tools_used": [t["tool"] for t in sub_run.tool_calls],
                }
            )
            all_tool_calls.extend(sub_run.tool_calls)

            messages.append(
                provider.tool_result_message(
                    call, json.dumps({"specialist": agent_name, "answer": sub_run.final_answer})
                )
            )

    # Out of delegation budget — force a final answer with tools withheld.
    final = provider.chat(
        messages + [{"role": "user", "content": "Give your combined answer now."}]
    )
    return {
        "mode": "orchestrated",
        "agent": "orchestrator",
        "routing_reason": f"delegated to {len(delegations)} specialists (hit the limit)",
        "answer": final.content or "",
        "delegations": delegations,
        "tool_calls": all_tool_calls,
        "iterations": len(delegations),
        "stopped_early": True,
    }
