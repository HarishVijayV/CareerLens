"""
THE AGENT LOOP — the single most important file in the AI layer.

Strip away the vocabulary and an "agent" is this:

    1. Send the LLM the conversation so far + the tools it's allowed to call
    2. It replies with either a final answer OR a request to call a tool
    3. If it's a tool request: run the real Python function, get a real result
    4. Feed that result back into the conversation, go to 1
    5. Stop when it answers instead of calling another tool

That's it. Multi-agent systems, planners, sub-agents — all of it is this loop composed
with itself. Every agent in this service is an instance of the class below, which is why
"how does your agent decide what to call?" has a concrete answer: it doesn't decide in
our code, the model chooses from the tools we gave it, and we validate and execute.

Written from scratch on purpose. app/langgraph_impl/ has the same thing via LangGraph —
compare them to see exactly what a framework adds and what it hides.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.llm.provider import LLMResponse, get_llm_provider
from app.tools.registry import dispatch_tool_call

MAX_TOOL_ITERATIONS = 6


@dataclass
class AgentRun:
    """Full trace of one agent run. Returning the trace (not just the answer) is what
    makes an agent debuggable — you can see exactly which tools fired, with what
    arguments, and what came back. Also what the UI shows to prove it isn't faking."""

    final_answer: str
    tool_calls: list[dict] = field(default_factory=list)
    iterations: int = 0
    stopped_early: bool = False
    duplicate_calls: int = 0   # repeats served from cache instead of re-executed


class Agent:
    """One narrow job, one small tool list, one focused prompt."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: list[dict] | None = None,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.max_iterations = max_iterations
        # Hard execution-time boundary, independent of what the model was shown.
        self.allowed_tools = {tool["name"] for tool in self.tools}

    def run(self, user_message: str) -> AgentRun:
        provider = get_llm_provider()
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]

        trace = AgentRun(final_answer="")

        # Cache of (tool, arguments) -> result for THIS run.
        #
        # Models genuinely do re-request the same call: an observed run issued search_jobs
        # 13 times with identical arguments while "thinking". Each repeat is a real HTTP
        # round trip and pushes the loop toward its iteration cap without adding
        # information. Serving the cached result — and telling the model it's cached —
        # both cuts cost and nudges it to move on.
        seen_calls: dict[str, str] = {}

        for iteration in range(1, self.max_iterations + 1):
            trace.iterations = iteration
            response: LLMResponse = provider.chat(messages, tools=self.tools or None)

            if not response.tool_calls:
                trace.final_answer = response.content or ""
                return trace

            # The assistant's tool-request turn must be echoed back before the results,
            # so the model can match each result to the call that produced it. The
            # provider builds the right shape for its own API.
            messages.append(provider.assistant_tool_call_message(response))

            for tool_call in response.tool_calls:
                signature = f"{tool_call.name}:{json.dumps(tool_call.arguments, sort_keys=True)}"

                if signature in seen_calls:
                    cached = seen_calls[signature]
                    # Say explicitly that it's a repeat. A silently identical result invites
                    # the model to ask again; naming it usually stops the loop.
                    result = json.dumps(
                        {
                            "note": "Identical call already made in this conversation — "
                            "cached result below. Use it and move on.",
                            "result": cached,
                        }
                    )
                    trace.duplicate_calls += 1
                else:
                    result = dispatch_tool_call(
                        tool_call.name, tool_call.arguments, allowed_tools=self.allowed_tools
                    )
                    seen_calls[signature] = result
                    trace.tool_calls.append(
                        {
                            "tool": tool_call.name,
                            "arguments": tool_call.arguments,
                            "result_preview": result[:400],
                        }
                    )

                messages.append(provider.tool_result_message(tool_call, result))

        # Ran out of iterations. Ask once more with tools withheld, which forces a text
        # answer instead of yet another tool call — better than returning nothing.
        trace.stopped_early = True
        final = provider.chat(
            messages + [{"role": "user", "content": "Answer now using what you have."}]
        )
        trace.final_answer = final.content or "Could not complete within the tool-call budget."
        return trace
