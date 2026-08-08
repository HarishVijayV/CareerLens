"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { AgentAnswer, api } from "@/lib/api";

const EXAMPLES = [
  "Which skills pay the most above average?",
  "Find me remote data engineering jobs paying over 120000",
  "How does hiring change across the year?",
  "Tailor my resume for posting P000177873",
];

/**
 * Shows the agent's TOOL CALLS alongside its answer, on purpose.
 *
 * Anyone can put a chat box in front of an LLM. Displaying which tools ran, with which
 * arguments, and what came back is the difference between "a chatbot" and "an agent that
 * actually queried my data" — and it's what makes the answer verifiable rather than
 * something you have to take on faith.
 */
export default function CopilotPage() {
  const [message, setMessage] = useState("");
  const [agent, setAgent] = useState("");
  const [agents, setAgents] = useState<Record<string, { description: string; tools: string[] }>>({});
  const [result, setResult] = useState<AgentAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listAgents().then(setAgents).catch(() => {});
  }, []);

  async function submit(text: string) {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.ask(text, agent || undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Agent call failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-xl font-semibold">AI Copilot</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Ask in plain English. A planner picks the right specialist agent, which calls real
          tools against your data — you can see every call it made below its answer.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(message);
            }}
            className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
          >
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={3}
              placeholder="Ask anything about jobs, the market, or your resume…"
              className="w-full resize-y rounded border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
            />
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <select
                value={agent}
                onChange={(e) => setAgent(e.target.value)}
                className="rounded border border-zinc-300 px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-800"
              >
                <option value="">Auto-route (planner decides)</option>
                {Object.keys(agents).map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                disabled={loading}
                className="rounded bg-zinc-900 px-4 py-1.5 text-sm text-white disabled:opacity-50 dark:bg-white dark:text-zinc-900"
              >
                {loading ? "Thinking…" : "Ask"}
              </button>
            </div>
          </form>

          <div className="mt-3 flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => {
                  setMessage(ex);
                  submit(ex);
                }}
                className="rounded-full border border-zinc-300 px-3 py-1 text-xs text-zinc-600 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
              >
                {ex}
              </button>
            ))}
          </div>

          {error && (
            <div className="mt-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
              {error}
            </div>
          )}

          {result && (
            <div className="mt-5 space-y-4">
              <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                  <span className="rounded bg-zinc-900 px-2 py-0.5 text-white dark:bg-white dark:text-zinc-900">
                    {result.agent}
                  </span>
                  <span className="text-zinc-500">
                    {result.iterations} LLM turn{result.iterations === 1 ? "" : "s"} ·{" "}
                    {result.tool_calls.length} tool call{result.tool_calls.length === 1 ? "" : "s"}
                  </span>
                  {result.routing_reason && (
                    <span className="text-zinc-400">— routed: {result.routing_reason}</span>
                  )}
                </div>
                <p className="whitespace-pre-wrap text-sm text-zinc-800 dark:text-zinc-200">
                  {result.answer}
                </p>
                {result.stopped_early && (
                  <p className="mt-2 text-xs text-amber-700 dark:text-amber-500">
                    Hit the tool-call limit — answer may be partial.
                  </p>
                )}
              </div>

              {result.tool_calls.length > 0 && (
                <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
                  <h3 className="mb-3 text-xs font-semibold text-zinc-500">
                    Tools the agent actually called
                  </h3>
                  <ol className="space-y-3">
                    {result.tool_calls.map((tc, i) => (
                      <li key={i} className="border-l-2 border-zinc-200 pl-3 dark:border-zinc-700">
                        <div className="font-mono text-xs font-medium text-zinc-800 dark:text-zinc-200">
                          {tc.tool}({JSON.stringify(tc.arguments)})
                        </div>
                        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all text-[11px] text-zinc-500">
                          {tc.result_preview}
                        </pre>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          )}
        </div>

        <aside className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <h3 className="mb-3 text-xs font-semibold text-zinc-500">Agents & their permissions</h3>
          <ul className="space-y-3">
            {Object.entries(agents).map(([name, cfg]) => (
              <li key={name}>
                <div className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{name}</div>
                <div className="text-xs text-zinc-500">{cfg.description}</div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {cfg.tools.map((t) => (
                    <span
                      key={t}
                      className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-[11px] leading-relaxed text-zinc-400">
            Each agent can only call the tools listed. The email agent literally cannot touch
            your resume — it was never given that tool.
          </p>
        </aside>
      </div>
    </AppShell>
  );
}
