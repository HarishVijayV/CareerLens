# Agentic AI Layer — Design and How to Explain It

This is the part interviewers will dig into the most, because "I called an LLM API" and "I
built a multi-agent system" are very different depths of understanding. This doc explains what
we built and, more importantly, *why* it's structured this way.

## The core idea: an agent is just a loop

Strip away the buzzwords and an "agent" is:

```
loop:
    1. Give the LLM the conversation so far + a list of tools it's allowed to call
    2. LLM replies with either a final answer, OR a request to call one of the tools
    3. If it's a tool call: run the real Python function, get a real result
    4. Feed that result back into the conversation, go to step 1
    5. Stop when the LLM gives a final answer instead of a tool call
```

That's it — that's the entire mechanism behind "agentic AI." Everything else (planning,
multi-agent, sub-agents) is this loop composed with itself.

## Two implementations, on purpose

- **`services/agent-service/app/agents/`** — hand-rolled orchestrator using the loop above
  directly against the LLM provider's function-calling API. No framework. This is what proves
  you understand the mechanism, not just how to import a library.
- **`services/agent-service/app/langgraph_impl/`** — the *same* agents re-implemented as a
  LangGraph graph (nodes = agents, edges = handoff rules, shared state object). This shows you
  can also use the production-grade framework real teams use for this (built-in state
  persistence, retries, visualizable graphs).

Being able to say "I built it from scratch first, then again in LangGraph, here's what the
framework buys you" is a strong, specific interview answer.

## The LLM provider abstraction — `services/agent-service/app/llm/provider.py`

Every agent talks to one internal interface (`LLMProvider.chat(messages, tools)`), never to
Anthropic/OpenAI/Fireworks directly. A config value picks the real backend underneath. This
means:
- You can use **Fireworks** (cheap/free, open models) for high-volume simple tasks like email
  classification.
- You can use **Anthropic or OpenAI** for the harder reasoning tasks (resume tailoring,
  planning) where quality matters more than cost.
- Swapping providers, or A/B testing two of them, is a one-line config change — this is
  exactly why real companies build this abstraction (never get locked into one vendor's API).

## The sub-agents

| Agent | Job | Tools it can call |
|---|---|---|
| **Orchestrator/Planner** | Reads the user's request, decides which sub-agent(s) to invoke and in what order | (delegates only, calls no external tools itself) |
| **Skill Extractor** | Turns a messy job description into a structured list of required skills/seniority/location | none — pure LLM extraction, validated against a schema |
| **Resume Matcher** | Scores your stored resume against a job's extracted requirements | `get_resume()`, `get_job()` |
| **Resume Tailor** | Rewrites specific bullets/keywords in your `.tex` resume for one target job | `read_resume_tex()`, `write_resume_tex()`, `compile_pdf()` |
| **Email Classifier** | Reads a batch of Gmail messages and labels each (applied / rejected / interview / offer) + extracts company/role | `gmail_search()`, `update_application_status()` |
| **Insight Agent** | Summarizes your funnel (applied → interview → offer) and flags which resume version performs better | `query_applications_db()` |

## Tool calling, concretely

A "tool" is just a normal Python function with a JSON-schema description attached, e.g.:

```python
TOOLS = [{
    "name": "get_resume",
    "description": "Fetch the user's currently stored resume text.",
    "input_schema": {"type": "object", "properties": {"user_id": {"type": "string"}}}
}]
```

The LLM never runs this function — it only ever *asks* for it to be run (by name + arguments).
Your Python code is the one that actually executes it and decides what's allowed. This
distinction ("the model requests, your code decides") is the single most important thing to be
able to explain about tool-calling/agent security — it's also why you can safely restrict what
each agent is allowed to touch (e.g. the Email Classifier can read Gmail but can never write to
your resume).

## Why no sandbox — and the one feature that would need one

A reasonable interview follow-up is *"do you sandbox the AI?"* The answer is no, and the
reason is the paragraph above rather than an oversight.

The model runs on the provider's servers. It has no filesystem, no database handle, no shell —
the only thing it can produce is text, and some of that text happens to name a tool. Our Python
receives that name, checks it against the agent's allow-list, and runs the function itself.
So there is no code of the model's to contain. `email_classifier` cannot reach your resume not
because something blocks it, but because `write_resume_tex` was never in its list. **A
capability that was never granted needs no containment.**

This flips the moment the model writes code we execute. The obvious candidate is an "ask
anything about the data" box, where the LLM generates SQL against the warehouse. Now a bad or
adversarial generation can drop a table, read another user's rows, or hang Postgres with a
runaway join — and least-privilege on tools no longer helps, because the *tool itself* is
"run arbitrary SQL". Containment has to become real:

- a **read-only Postgres role** scoped to `analytics`, so DDL and writes fail at the database
- a **statement timeout** plus a row cap, so no one query monopolises the warehouse
- **allow-list the statement type** — reject anything that isn't a `SELECT`
- if an agent ever runs generated *Python* (e.g. to plot something), give it a throwaway
  container with no network and no credentials

The generalisation worth being able to say:

> "A sandbox is what you add when you stop controlling *what* runs and can only control
> *where* it runs. Right now the model chooses from a fixed tool list, so there's nothing to
> sandbox — least privilege covers it. Text-to-SQL would change that in a single commit."

Note also that "sandbox" has a second, unrelated meaning — Stripe/PayPal *sandbox* is a
practice mode with fake data, not an isolation boundary. Worth separating the two if an
interviewer uses the word loosely. Nothing here uses that kind; there are no payments.

## Why "multi-agent" instead of one big prompt

Splitting into narrow sub-agents (each with one job, one small tool list, one focused prompt)
beats one giant do-everything agent for reasons worth stating out loud in an interview:
- **Smaller context, better accuracy** — a skill-extractor prompt only needs the job
  description, not your whole resume history and email inbox.
- **Least privilege** — the email agent literally cannot call the resume-writing tool, because
  it was never given that tool. A bug or a bad LLM output can't do damage outside its lane.
- **Debuggability** — when something's wrong, you know exactly which agent's output to inspect
  instead of untangling one giant transcript.
- **Independent iteration** — you can improve the resume-tailor prompt without risking a
  regression in email classification.

## Where this connects to the rest of the system

The agent service never talks to Spark/Hadoop/Kafka directly — it only ever reads curated,
already-cleaned data out of Postgres. This is deliberate: the AI layer should reason over
trustworthy, already-validated numbers, not raw scraped data. That separation is also a good
answer to "how do you keep an LLM from hallucinating numbers" — you don't let it near raw data
in the first place.
