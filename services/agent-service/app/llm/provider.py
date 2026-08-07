"""
Every agent talks to `get_llm_provider().chat(...)` and NEVER imports anthropic/openai
directly. That one rule is what makes swapping providers (or A/B testing two of them) a
one-line config change instead of a rewrite — see docs/AGENTIC_AI.md.

Canonical tool spec (used everywhere in this codebase, converted per-provider below):
    {"name": str, "description": str, "input_schema": {JSON schema object}}

Canonical response:
    LLMResponse(content: str | None, tool_calls: list[ToolCall])
    ToolCall(id: str, name: str, arguments: dict)
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


class LLMProvider:
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        raise NotImplementedError

    def tool_result_message(self, tool_call: ToolCall, result: str) -> dict:
        """How a tool's output gets fed back into the conversation — format differs per
        provider, so each provider implements its own."""
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    def __init__(self):
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        kwargs = {"model": self._model, "max_tokens": 1024, "messages": messages}
        if tools:
            kwargs["tools"] = tools  # already in Anthropic's native shape

        resp = self._client.messages.create(**kwargs)

        text_parts, tool_calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        return LLMResponse(content="".join(text_parts) or None, tool_calls=tool_calls)

    def tool_result_message(self, tool_call: ToolCall, result: str) -> dict:
        return {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_call.id, "content": result}],
        }


class _OpenAICompatibleProvider(LLMProvider):
    """Shared implementation for OpenAI and Fireworks — Fireworks exposes an
    OpenAI-compatible API, so the same client class works for both with a different
    base_url/api_key/model. This is exactly the kind of reuse the abstraction is for."""

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
        resp = self._client.chat.completions.create(
            model=self._model, messages=messages, tools=self._to_openai_tools(tools)
        )
        choice = resp.choices[0].message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments))
            for tc in (choice.tool_calls or [])
        ]
        return LLMResponse(content=choice.content, tool_calls=tool_calls)

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


_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "fireworks": FireworksProvider,
    "openai": OpenAIProvider,
}

_cached_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _cached_provider
    if _cached_provider is None:
        provider_cls = _PROVIDERS[settings.llm_provider]
        _cached_provider = provider_cls()
    return _cached_provider
