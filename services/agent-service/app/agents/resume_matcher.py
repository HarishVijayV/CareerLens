"""
This agent DOES use tools, and only these two — it can fetch a resume and fetch a job, and
nothing else. It cannot write to the resume, cannot touch email, cannot query the
database directly. That narrow tool list is the least-privilege point made concrete:
even if this prompt were somehow hijacked, there is nothing destructive it could do.
"""
from app.llm.provider import get_llm_provider
from app.tools.registry import dispatch_tool_call

TOOLS = [
    {
        "name": "get_resume",
        "description": "Fetch the user's currently stored resume (bullets + skills).",
        "input_schema": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}},
            "required": ["user_id"],
        },
    },
    {
        "name": "get_job",
        "description": "Fetch a job posting's title and description by id.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
]

SYSTEM_PROMPT = """You score how well a user's resume matches a job posting.
Use the get_resume and get_job tools to fetch the data you need — never guess their
content. Respond with a short score out of 100, a one-sentence reason, and up to 3
concrete skill gaps."""


def match_resume_to_job(user_id: str, job_id: str) -> str:
    """This is the hand-rolled tool-calling loop from docs/AGENTIC_AI.md, made concrete:
    ask the model, run whatever tool it requests, feed the result back, repeat until it
    gives a final answer instead of another tool request."""
    provider = get_llm_provider()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Score the match between user_id={user_id} and job_id={job_id}.",
        },
    ]

    for _ in range(5):  # hard cap — never let a misbehaving loop run unbounded
        response = provider.chat(messages, tools=TOOLS)

        if not response.tool_calls:
            return response.content or ""

        # NOTE — simplified for readability: a fully spec-correct Anthropic multi-turn
        # loop needs the assistant turn to echo back the raw tool_use content blocks
        # (with their ids), not just plain text, so the tool_result can be matched to
        # them. The OpenAI/Fireworks path only needs the text. If you switch to
        # Anthropic and see mismatched tool_use_id errors, this is the line to fix —
        # store `response` (not just `.content`) and replay its raw content blocks here.
        messages.append({"role": "assistant", "content": response.content or ""})

        for tool_call in response.tool_calls:
            result = dispatch_tool_call(tool_call.name, tool_call.arguments)
            messages.append(provider.tool_result_message(tool_call, result))

    return "Could not reach a final answer within the tool-call budget."
