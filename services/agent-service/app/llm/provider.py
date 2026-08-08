"""
Provider abstraction. Every agent calls `get_llm_provider().chat(...)` and never imports
anthropic/openai directly. That one rule makes swapping providers — or A/B testing two —
a config change instead of a rewrite, which is exactly why real teams build this layer
(vendor lock-in is a business risk, not just an engineering one).

It also lets you route by cost: a cheap open model for high-volume mechanical work (email
classification), a stronger one for reasoning (resume tailoring), same agent code.

Canonical tool spec used everywhere in this codebase (converted per-provider below):
    {"name": str, "description": str, "input_schema": {...JSON schema...}}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.core.config import settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_content: object = None  # provider-native blocks, needed to replay Anthropic turns


class LLMProvider:
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        raise NotImplementedError

    def assistant_tool_call_message(self, response: LLMResponse) -> dict:
        """The assistant turn to append before tool results."""
        raise NotImplementedError

    def tool_result_message(self, tool_call: ToolCall, result: str) -> dict:
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    def __init__(self):
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        # Anthropic takes the system prompt as a top-level argument, not as a message
        # with role="system" — one of the few real shape differences between the APIs,
        # and precisely the kind of detail this abstraction exists to absorb.
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [m for m in messages if m["role"] != "system"]

        kwargs = {"model": self._model, "max_tokens": 2048, "messages": convo}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools  # already Anthropic-native shape

        resp = self._client.messages.create(**kwargs)

        text_parts, tool_calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        return LLMResponse(
            content="".join(text_parts) or None, tool_calls=tool_calls, raw_content=resp.content
        )

    def assistant_tool_call_message(self, response: LLMResponse) -> dict:
        # Replay the ORIGINAL content blocks, not just the text: each tool_result must
        # reference the tool_use id it answers, and those ids only exist in the raw
        # blocks. Flattening to text here is a subtle bug that shows up as
        # "tool_use_id not found" errors.
        return {"role": "assistant", "content": response.raw_content}

    def tool_result_message(self, tool_call: ToolCall, result: str) -> dict:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_call.id, "content": result}
            ],
        }


class _OpenAICompatibleProvider(LLMProvider):
    """Shared by OpenAI and Fireworks — Fireworks serves an OpenAI-compatible API, so one
    implementation covers both with a different base_url/key/model."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    @staticmethod
    def _to_openai_tools(tools: list[dict] | None) -> list[dict] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        kwargs = {"model": self._model, "messages": messages}

        # Only include `tools` when there ARE tools. Passing tools=None explicitly is not
        # the same as omitting the field: OpenAI tolerates the null, but Fireworks rejects
        # it with "Input should be a valid list, field: 'tools', value: None". That broke
        # every tool-less agent (email_classifier, skill_extractor) while tool-using agents
        # worked fine — a confusing split until you notice what they have in common.
        openai_tools = self._to_openai_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools

        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message

        tool_calls = []
        for tc in choice.tool_calls or []:
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                # Smaller models occasionally emit malformed JSON arguments. Surfacing it
                # as an empty dict lets the tool layer reply with a clear error the model
                # can recover from, instead of raising here and killing the request.
                arguments = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=arguments))

        return LLMResponse(content=choice.content, tool_calls=tool_calls, raw_content=choice)

    def assistant_tool_call_message(self, response: LLMResponse) -> dict:
        return {
            "role": "assistant",
            "content": response.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in response.tool_calls
            ],
        }

    def tool_result_message(self, tool_call: ToolCall, result: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call.id, "content": result}


class FireworksProvider(_OpenAICompatibleProvider):
    def __init__(self):
        super().__init__(
            api_key=settings.fireworks_api_key,
            model=settings.fireworks_model,
            base_url="https://api.fireworks.ai/inference/v1",
        )


class OpenAIProvider(_OpenAICompatibleProvider):
    def __init__(self):
        super().__init__(api_key=settings.openai_api_key, model=settings.openai_model)


class GeminiProvider(_OpenAICompatibleProvider):
    """Google Gemini via its OpenAI-compatible endpoint. Included because it has a real
    permanent free tier (rate-limited) rather than trial credits — the practical choice
    when a project needs to keep working for years without a bill."""

    def __init__(self):
        super().__init__(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )


_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "fireworks": FireworksProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}

_cached_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _cached_provider
    if _cached_provider is None:
        provider_cls = _PROVIDERS.get(settings.llm_provider)
        if provider_cls is None:
            raise ValueError(
                f"Unknown LLM_PROVIDER '{settings.llm_provider}'. "
                f"Choose one of: {sorted(_PROVIDERS)}"
            )
        _cached_provider = provider_cls()
    return _cached_provider
