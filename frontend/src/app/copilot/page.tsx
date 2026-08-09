"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import AppShell from "@/components/AppShell";
import { AgentAnswer, api, ApiError } from "@/lib/api";
import { getPending, startRequest, subscribe } from "@/lib/pendingRequests";

const CHAT_STORAGE_KEY = "careerlens.assistant.turns";

const EXAMPLES = [
  "Which skills pay the most above average?",
  "Find me remote data engineering jobs paying over 120000",
  "How does hiring change across the year?",
  "What skills am I missing for a senior data engineer role?",
];

/** One concrete question per agent, so the sidebar shows what each is FOR rather than
 *  just what it's called. Clicking one also demonstrates the planner routing correctly. */
const AGENT_EXAMPLES: Record<string, string> = {
  job_matcher: "What jobs match my skills, and what am I missing?",
  resume_tailor: "Rewrite my resume bullets to emphasise data engineering",
  market_analyst: "Which skills pay the most above average?",
  skill_extractor: "Extract the requirements from this job description: ...",
  email_classifier: "Classify this email: Subject: Thank you for applying to Acme",
};

interface Turn {
  role: "user" | "assistant";
  text: string;
  answer?: AgentAnswer; // assistant turns carry the full trace
  error?: boolean;
}

/**
 * Shows the agent's TOOL CALLS alongside its answer, on purpose.
 *
 * Anyone can put a chat box in front of an LLM. Displaying which tools ran, with which
 * arguments, and what came back is the difference between "a chatbot" and "an agent that
 * actually queried my data" — it makes the answer verifiable rather than something you
 * have to take on faith.
 */
/** The label of a resume version saved during this turn, if any.
 *
 *  Read from the tool RESULT rather than the arguments: the arguments are what the model
 *  asked for, the result is what the server actually stored — and the server appends a
 *  suffix when a label collides, so the two can differ. Showing the requested name would
 *  send the user looking for a version that does not exist under that name. */
function savedResumeLabel(answer: AgentAnswer | undefined): string | null {
  const call = answer?.tool_calls?.find((c) => c.tool === "save_tailored_resume");
  if (!call) return null;
  try {
    const parsed = JSON.parse(call.result_preview);
    return parsed.saved ? (parsed.label ?? null) : null;
  } catch {
    // result_preview is truncated at 400 chars, so a long result may not parse. The label
    // sits near the front, so fall back to reading it out directly.
    const match = call.result_preview.match(/"label"\s*:\s*"([^"]+)"/);
    return match ? match[1] : null;
  }
}

/** What each specialist was brought in to do.
 *
 *  Fixed labels, not the generated question. The orchestrator writes its own wording for
 *  each sub-agent and that text kept containing the internal user id — "[user_id: ...]",
 *  "For user_id ...", "User ID: ..." — in a new shape each time. Stripping it with regexes
 *  was whack-a-mole: a model can write an id a dozen ways, and every miss put a raw
 *  database uuid on screen next to the user's own question.
 *
 *  The generated wording was never worth showing anyway. What a reader actually wants to
 *  know is WHICH specialist ran and what it touched, and both of those are structured
 *  fields we already have. Not rendering model-written text at all removes the whole class
 *  of bug rather than patching instances of it.
 *
 *  The full question is still in the API response for debugging — it is just not UI. */
const AGENT_ROLE: Record<string, string> = {
  job_matcher: "found and scored matching jobs",
  resume_tailor: "rewrote your resume for the role",
  market_analyst: "looked up market statistics",
  skill_extractor: "pulled requirements out of a job description",
  profile_extractor: "read your resume into profile fields",
  email_classifier: "classified an email",
};

export default function AssistantPage() {
  /* Conversation survives navigation.
   *
   * Next.js unmounts a page when you route away, so the component's state went with it —
   * click Dashboard and come back and the whole conversation was gone, including answers
   * that had taken ninety seconds to produce. Losing that to a navigation is the same
   * class of problem as losing it to a logout: work destroyed by something the user did
   * not think of as destructive.
   *
   * sessionStorage rather than localStorage: a conversation belongs to a browsing session,
   * not to the machine forever. Closing the tab is a deliberate end; clicking a nav link
   * is not.
   */
  const [turns, setTurns] = useState<Turn[]>([]);
  const [restored, setRestored] = useState(false);

  useEffect(() => {
    // Read in an effect, not in the useState initialiser: this component renders on the
    // server first, where sessionStorage does not exist, and touching it during render is
    // a hydration mismatch.
    try {
      const saved = sessionStorage.getItem(CHAT_STORAGE_KEY);
      if (saved) setTurns(JSON.parse(saved));
    } catch {
      // A corrupt or oversized entry must never stop the page loading.
    }
    setRestored(true);
  }, []);

  useEffect(() => {
    if (!restored) return;   // don't overwrite saved turns with the empty initial state
    try {
      sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(turns));
    } catch {
      // Quota exceeded on a very long conversation — keep the chat working in memory.
    }
  }, [turns, restored]);
  const [message, setMessage] = useState("");
  const [agent, setAgent] = useState("");
  const [agents, setAgents] = useState<Record<string, { description: string; tools: string[] }>>({});
  const [loading, setLoading] = useState(false);
  const [showOverride, setShowOverride] = useState(false);
  // Team mode = orchestration: several specialists, then a combined answer. Off by
  // default because each delegation is a full nested LLM loop — richer, but multiple
  // times the cost of routing to one agent.
  const [teamMode, setTeamMode] = useState(false);
  const [expandedTools, setExpandedTools] = useState<number | null>(null);

  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.listAgents().then(setAgents).catch(() => {});
  }, []);

  // Keep the newest turn in view as the conversation grows.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, loading]);

  /** Append whatever a request produced — used by submit() and by the reconnect effect,
   *  so an answer lands in identical state whether you stayed on the page or not. */
  const settle = useCallback((result: AgentAnswer | Error) => {
    setTurns((t) => [
      ...t,
      result instanceof Error
        ? {
            role: "assistant" as const,
            text: result instanceof ApiError ? result.message : "The assistant call failed.",
            error: true,
          }
        : { role: "assistant" as const, text: result.answer, answer: result },
    ]);
    setLoading(false);
  }, []);

  // Re-attach to a request that was already running when this page mounted. The registry
  // is shared and keyed by page, so wandering Resume -> Assistant -> Resume cannot lose an
  // answer or let one page claim another's.
  useEffect(() => {
    if (!getPending("assistant")) return;
    setLoading(true);
    const unsubscribe = subscribe("assistant", settle);
    return unsubscribe ?? undefined;
  }, [settle]);

  async function submit(text: string) {
    if (!text.trim() || loading) return;

    // APPEND, don't replace. The previous version wiped the screen on every question,
    // which threw away context the user was still reading and made it impossible to
    // compare a follow-up answer against the one before it.
    setTurns((t) => [...t, { role: "user", text }]);
    setMessage("");
    setLoading(true);

    try {
      const answer = await startRequest("assistant", text, () =>
        api.ask(text, agent || undefined, teamMode ? "orchestrate" : "auto")
      );
      settle(answer);
    } catch (e) {
      settle(e instanceof Error ? e : new Error(String(e)));
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter newlines — the convention every chat UI uses. Without it
    // the textarea just inserted a newline and nothing was sent, which reads as broken.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(message);
    }
  }

  return (
    <AppShell>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Assistant</h1>
          <p className="mt-1 text-base text-[var(--text-muted)]">
            Ask in plain English. A planner picks one specialist — or the whole team — which calls real
            tools against your data — every call is shown with its answer.
          </p>
        </div>
        {turns.length > 0 && (
          <button
            onClick={() => {
              setTurns([]);
              try { sessionStorage.removeItem(CHAT_STORAGE_KEY); } catch {}
            }}
            className="rounded-lg border border-[var(--border-strong)] px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--surface-page)] dark:hover:bg-zinc-800"
          >
            Clear conversation
          </button>
        )}
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        {/* ---------------- conversation ---------------- */}
        <div className="flex h-[calc(100vh-250px)] min-h-[540px] flex-col rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-card)]">
          <div className="flex-1 space-y-4 overflow-y-auto p-6">
            {turns.length === 0 && (
              <div className="py-12 text-center">
                <p className="text-lg font-medium">What would you like to know?</p>
                <p className="mt-1.5 text-sm text-[var(--text-muted)]">
                  The planner decides which agent handles it — you don&apos;t have to choose.
                </p>
                <div className="mx-auto mt-6 flex max-w-2xl flex-wrap justify-center gap-2">
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex}
                      onClick={() => submit(ex)}
                      className="rounded-full border border-[var(--border-strong)] px-4 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--surface-sunken)] dark:hover:bg-zinc-800"
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {turns.map((turn, i) =>
              turn.role === "user" ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-zinc-900 px-4 py-3 text-base text-white dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]">
                    {turn.text}
                  </div>
                </div>
              ) : (
                <div key={i} className="flex justify-start">
                  <div
                    className={`max-w-[88%] rounded-2xl rounded-bl-sm border px-4 py-3 ${
                      turn.error
                        ? "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950"
                        : "border-[var(--border-subtle)] bg-[var(--surface-page)]/50"
                    }`}
                  >
                    {turn.answer && (
                      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                        <span className="rounded bg-zinc-900 px-2 py-0.5 text-white dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]">
                          {turn.answer.agent}
                        </span>
                        {turn.answer.routing_reason ? (
                          <span className="text-[var(--text-muted)]">
                            planner chose this — {turn.answer.routing_reason}
                          </span>
                        ) : (
                          <span className="text-[var(--text-muted)]">(agent forced)</span>
                        )}
                      </div>
                    )}

                    {turn.error ? (
                      // Errors are our own plain strings, never markdown.
                      <p className="whitespace-pre-wrap text-base leading-relaxed text-red-700 dark:text-red-300">
                        {turn.text}
                      </p>
                    ) : (
                      // The models answer in markdown — headings, bold, and tables. Rendered
                      // as pre-wrapped text, that arrived as literal "**Machine Learning
                      // Engineer**" and pipe-delimited table rows, which is unreadable
                      // exactly where the answer is densest.
                      //
                      // remark-gfm is what makes tables and strikethrough work; plain
                      // react-markdown only handles CommonMark, which has no table syntax —
                      // and tables are most of what these answers use.
                      <div className="prose-chat text-base leading-relaxed text-[var(--text-primary)]">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            // Links go to real job postings, so they must open away from
                            // the chat rather than replacing it and losing the answer.
                            a: ({ ...props }) => (
                              <a
                                {...props}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-blue-700 underline dark:text-blue-400"
                              />
                            ),
                            table: ({ ...props }) => (
                              // Own scroll container: a wide table must never make the
                              // whole page scroll sideways.
                              <div className="my-3 overflow-x-auto">
                                <table {...props} className="w-full border-collapse text-sm" />
                              </div>
                            ),
                            th: ({ ...props }) => (
                              <th
                                {...props}
                                className="border-b border-[var(--border-strong)] px-2 py-1.5 text-left font-medium"
                              />
                            ),
                            td: ({ ...props }) => (
                              <td
                                {...props}
                                className="border-b border-[var(--border-subtle)] px-2 py-1.5 align-top"
                              />
                            ),
                            h2: ({ ...props }) => (
                              <h2 {...props} className="mt-4 mb-2 text-lg font-semibold" />
                            ),
                            h3: ({ ...props }) => (
                              <h3 {...props} className="mt-3 mb-1.5 text-base font-semibold" />
                            ),
                            ul: ({ ...props }) => (
                              <ul {...props} className="my-2 list-disc space-y-1 pl-5" />
                            ),
                            ol: ({ ...props }) => (
                              <ol {...props} className="my-2 list-decimal space-y-1 pl-5" />
                            ),
                            p: ({ ...props }) => <p {...props} className="my-2" />,
                            code: ({ ...props }) => (
                              <code
                                {...props}
                                className="rounded bg-[var(--surface-sunken)] px-1 py-0.5 text-[13px]"
                              />
                            ),
                            hr: () => (
                              <hr className="my-4 border-[var(--border-subtle)]" />
                            ),
                          }}
                        >
                          {turn.text}
                        </ReactMarkdown>
                      </div>
                    )}

                    {savedResumeLabel(turn.answer) && (
                      // Surface the saved version by NAME. It was only visible inside the
                      // collapsed tool-call list, so the assistant would say "I tailored
                      // your resume" and you had no idea what to look for on the Resume
                      // page — an action with no receipt.
                      <div className="mb-3 rounded border border-emerald-200 bg-emerald-50 p-2 text-xs dark:border-emerald-900 dark:bg-emerald-950/40">
                        <span className="text-emerald-900 dark:text-emerald-300">
                          Saved as a new version:{" "}
                          <strong>{savedResumeLabel(turn.answer)}</strong>
                        </span>{" "}
                        <a href="/resume" className="underline text-emerald-800 dark:text-emerald-400">
                          open in Resume
                        </a>
                        <div className="mt-0.5 text-emerald-800/80 dark:text-emerald-400/80">
                          Your previous versions are untouched.
                        </div>
                      </div>
                    )}

                    {turn.answer?.delegations && turn.answer.delegations.length > 0 && (
                      <div className="mb-3 rounded border border-blue-200 bg-blue-50 p-2 text-xs dark:border-blue-900 dark:bg-blue-950/40">
                        <div className="mb-1 font-medium text-blue-900 dark:text-blue-300">
                          Delegated to {turn.answer.delegations.length} specialist
                          {turn.answer.delegations.length === 1 ? "" : "s"}
                        </div>
                        {turn.answer.delegations.map((d, k) => (
                          <div key={k} className="text-blue-800 dark:text-blue-400">
                            {k + 1}. <strong>{d.agent}</strong> — {AGENT_ROLE[d.agent] ?? "worked on this"}
                            {d.tools_used?.length ? (
                              <span className="text-blue-700/70 dark:text-blue-400/70">
                                {" "}
                                ({d.tools_used.join(", ")})
                              </span>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}

                    {turn.answer && turn.answer.tool_calls.length > 0 && (
                      <div className="mt-3 border-t border-[var(--border-subtle)] pt-2">
                        <button
                          onClick={() => setExpandedTools(expandedTools === i ? null : i)}
                          className="text-xs text-[var(--text-muted)] underline decoration-dotted"
                        >
                          {expandedTools === i ? "Hide" : "Show"} {turn.answer.tool_calls.length}{" "}
                          tool call{turn.answer.tool_calls.length === 1 ? "" : "s"} ·{" "}
                          {Object.entries(
                            turn.answer.tool_calls.reduce<Record<string, number>>((acc, c) => {
                              acc[c.tool] = (acc[c.tool] ?? 0) + 1;
                              return acc;
                            }, {})
                          )
                            .map(([tool, n]) => (n > 1 ? `${tool} ×${n}` : tool))
                            .join(", ")}
                        </button>

                        {expandedTools === i && (
                          <ol className="mt-2 space-y-2">
                            {turn.answer.tool_calls.map((tc, j) => (
                              <li key={j} className="border-l-2 border-[var(--border-strong)] pl-2">
                                <div className="font-mono text-xs font-medium text-[var(--text-secondary)]">
                                  {tc.tool}({JSON.stringify(tc.arguments)})
                                </div>
                                <pre className="mt-0.5 max-h-28 overflow-auto whitespace-pre-wrap break-all text-[11px] text-[var(--text-muted)]">
                                  {tc.result_preview}
                                </pre>
                              </li>
                            ))}
                          </ol>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )
            )}

            {loading && (
              <div className="flex justify-start">
                <div className="rounded-2xl rounded-bl-sm border border-[var(--border-subtle)] bg-[var(--surface-page)] px-4 py-3 text-base text-[var(--text-muted)]/50">
                  Thinking…
                </div>
              </div>
            )}

            <div ref={endRef} />
          </div>

          {/* ---------------- composer ---------------- */}
          <div className="border-t border-[var(--border-subtle)] p-4">
            <div className="flex items-end gap-2">
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={onKeyDown}
                rows={2}
                placeholder="Ask anything…   (Enter to send · Shift+Enter for a new line)"
                className="flex-1 resize-none rounded-lg border border-[var(--border-strong)] px-4 py-3 text-base outline-none focus:border-zinc-900 dark:focus:border-[var(--border-subtle)]"
              />
              <button
                onClick={() => submit(message)}
                disabled={loading || !message.trim()}
                className="rounded-lg bg-zinc-900 px-5 py-3 text-base font-medium text-white disabled:opacity-40 dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]"
              >
                Send
              </button>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-[var(--text-muted)]">
              <label className="flex cursor-pointer items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={teamMode}
                  onChange={(e) => setTeamMode(e.target.checked)}
                />
                <span title="The orchestrator delegates to several specialists and combines their answers. Slower and costlier, but handles questions one agent can't.">
                  Use the whole team <span className="text-[var(--text-muted)]">(multi-agent)</span>
                </span>
              </label>

              {!showOverride ? (
                <button onClick={() => setShowOverride(true)} className="underline decoration-dotted">
                  Force a specific agent
                </button>
              ) : (
                <>
                  <select
                    value={agent}
                    onChange={(e) => setAgent(e.target.value)}
                    className="rounded border border-[var(--border-strong)] px-2 py-1 text-xs"
                  >
                    <option value="">Auto (planner decides)</option>
                    {Object.keys(agents).map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => {
                      setAgent("");
                      setShowOverride(false);
                    }}
                    className="underline decoration-dotted"
                  >
                    hide
                  </button>
                </>
              )}
            </div>
          </div>
        </div>

        {/* ---------------- sidebar ---------------- */}
        <aside className="flex h-[calc(100vh-250px)] min-h-[540px] flex-col overflow-y-auto rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-card)] p-5">
          <h3 className="mb-2 text-sm font-semibold text-[var(--text-secondary)]">
            How a question is handled
          </h3>
          <ol className="mb-6 space-y-1.5 text-xs leading-relaxed text-[var(--text-muted)]">
            <li>
              1. A <strong>planner</strong> reads your question and picks the cheapest mode
              that can answer it — <strong>one specialist</strong>, or <strong>the team</strong>
              if the question spans several
            </li>
            <li>2. Each agent decides which of ITS tools to call</li>
            <li>3. Our Python runs the tool and feeds the result back</li>
            <li>4. Repeat until it answers — every call shown with the reply</li>
          </ol>

          <h3 className="mb-3 text-sm font-semibold text-[var(--text-secondary)]">
            Agents &amp; permissions
          </h3>
          <ul className="space-y-3">
            {Object.entries(agents).map(([name, cfg]) => (
              <li key={name} className="border-b border-[var(--border-subtle)] pb-3 last:border-0">
                <div className="text-sm font-medium text-[var(--text-primary)]">{name}</div>
                <div className="text-xs text-[var(--text-muted)]">{cfg.description}</div>

                {AGENT_EXAMPLES[name] && (
                  <button
                    onClick={() => submit(AGENT_EXAMPLES[name])}
                    className="mt-2 block w-full rounded border border-[var(--border-subtle)] px-2 py-1.5 text-left text-xs italic text-[var(--text-secondary)] hover:bg-[var(--surface-page)] dark:hover:bg-zinc-800"
                    title="Ask this — the planner should route it here"
                  >
                    &ldquo;{AGENT_EXAMPLES[name]}&rdquo;
                  </button>
                )}

                <div className="mt-2 flex flex-wrap gap-1">
                  {cfg.tools.map((t) => (
                    <span
                      key={t}
                      className="rounded bg-[var(--surface-sunken)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>

          <p className="mt-4 text-xs leading-relaxed text-[var(--text-muted)]">
            Each agent can only call the tools listed. The email agent literally cannot touch
            your resume — it was never given that tool.
          </p>
        </aside>
      </div>
    </AppShell>
  );
}
