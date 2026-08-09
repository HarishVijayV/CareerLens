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
import re

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

_ROUTER_PROMPT = """You are the planner. Decide the CHEAPEST way to answer the user.

Available specialists:
{catalog}

You have two choices:

1. Name ONE specialist, if that specialist alone can fully answer the question.
2. Answer "orchestrator", if the question needs SEVERAL specialists combined. Choose this
   whenever the question spans more than one specialist's remit — for example "match jobs
   to my resume AND tell me what to fix" needs the job matcher AND the resume tailor, and
   "which jobs suit me and is that field growing?" needs the matcher AND the analyst.

Respond with ONLY a JSON object: {{"agent": "<name or orchestrator>", "reason": "<short reason>"}}

Prefer a single specialist when one genuinely suffices — orchestration costs several times
more. But do NOT force a multi-part question into one specialist: a partial answer that
silently drops half the question is worse than the extra cost."""

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
        if choice.get("agent") in AGENTS or choice.get("agent") == "orchestrator":
            return choice
    except json.JSONDecodeError:
        pass

    # Routing must never hard-fail a request — a sensible default beats a 500.
    return {"agent": "market_analyst", "reason": "router fallback (unparseable response)"}


def route_with_llm(user_message: str) -> dict:
    """Auto mode. The planner picks a single specialist OR escalates to orchestration.

    This escalation is the point. Without it "auto" could only ever route, so a question
    like "match jobs to my resume and give me the top 3 fixes" got answered by the job
    matcher alone — it produced something plausible, which is exactly what made the gap
    hard to notice. Letting the planner choose the MODE, not just the worker, means the
    user doesn't have to know which mode their question needs.
    """
    choice = choose_agent(user_message)

    if choice["agent"] == "orchestrator":
        result = orchestrate(user_message)
        result["routing_reason"] = (
            f"planner escalated to the team: {choice.get('reason', '')} "
            f"— {result['routing_reason']}"
        )
        return result

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


def _extract_user_id(message: str) -> str | None:
    """Pull the `[user_id: ...]` line the router prepends to every request."""
    match = re.match(r"\[user_id:\s*([^\]]+)\]", message.strip())
    return match.group(1).strip() if match else None


def orchestrate(user_message: str) -> dict:
    """Delegate to one or more sub-agents, then synthesise a single answer."""
    provider = get_llm_provider()

    # The sub-agent gets whatever question the orchestrator WROTE, not the original
    # message — so the `[user_id: ...]` line the router prepended is only carried through
    # if the model happens to copy it. Sometimes it did and sometimes it didn't, which is
    # the worst kind of intermittent: "tailor my resume" reached resume_tailor with no id,
    # get_resume had nobody to look up, and the agent asked the user to paste a resume it
    # was perfectly able to fetch.
    #
    # Identity is not something to leave to a model's discretion. Re-attached to every
    # delegation below, in code.
    user_id = _extract_user_id(user_message)
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
            # Match on the AGENT, not the agent-plus-question. Matching both let the
            # orchestrator ask job_matcher twice by rewording the question slightly, and a
            # specialist asked about the same user twice returns the same thing — pure
            # cost, and it eats the delegation budget a DIFFERENT specialist needed.
            already = next((d for d in delegations if d["agent"] == agent_name), None)
            if already:
                messages.append(
                    provider.tool_result_message(
                        call,
                        json.dumps({
                            "note": f"{agent_name} has already answered in this "
                            "request; its reply is below. Use it — do not ask again.",
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
            #
            # user_id is re-attached here rather than trusted to be in `question`, so a
            # sub-agent can always identify whose data to read.
            sub_question = question
            if user_id and "[user_id:" not in sub_question:
                sub_question = f"[user_id: {user_id}]\n{sub_question}"

            sub_run = route_explicit(agent_name, sub_question)

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
