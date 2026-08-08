"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import { ActiveResume, api, ApiError, ResumeVersion, ToolCall } from "@/lib/api";

interface ChatTurn {
  role: "user" | "assistant";
  text: string;
  toolCalls?: ToolCall[];
}

const QUICK_ASKS = [
  "Convert my resume to LaTeX",
  "Rewrite my bullets to emphasise data engineering",
  "Make my summary punchier and more specific",
  "Add measurable impact to my experience bullets",
];

export default function ResumePage() {
  const [active, setActive] = useState<ActiveResume | null>(null);
  const [versions, setVersions] = useState<ResumeVersion[]>([]);
  const [tab, setTab] = useState<"text" | "latex" | "preview">("text");
  const [draftText, setDraftText] = useState("");
  const [draftLatex, setDraftLatex] = useState("");
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [message, setMessage] = useState("");
  const [thinking, setThinking] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const [a, v] = await Promise.all([api.getActiveResume(), api.listResumeVersions()]);
    setActive(a);
    setVersions(v);
    setDraftText(a.content_text ?? "");
    setDraftLatex(a.content_latex ?? "");
    setDirty(false);

    // Drop any cached PDF — the active version just changed (upload, save, agent edit or
    // restore), so a stale render would be showing the wrong document entirely.
    setPdfUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return null;
    });

    setTab((current) => (current === "preview" ? "preview" : a.content_latex ? "latex" : "text"));
  }, []);

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const version = await api.uploadResume(file);
      setStatus(`Uploaded "${version.label}" — extracted ${version.source_format.toUpperCase()}`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      await api.saveResume(draftText, draftLatex || null);
      setStatus("Saved as a new version");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function send(text: string) {
    if (!text.trim()) return;
    setChat((c) => [...c, { role: "user", text }]);
    setMessage("");
    setThinking(true);
    setError(null);
    try {
      const result = await api.ask(text, "resume_tailor");
      setChat((c) => [
        ...c,
        { role: "assistant", text: result.answer, toolCalls: result.tool_calls },
      ]);
      // The agent writes a NEW version via its save tool, so reload to pick it up —
      // the editor should show what the agent actually persisted, not a stale draft.
      await load();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `${err.message}`
          : "The assistant call failed — is an LLM key set in infra/.env?"
      );
    } finally {
      setThinking(false);
    }
  }

  function download(fmt: "tex" | "txt" | "pdf") {
    if (fmt === "pdf") {
      // Reuse the already-fetched blob if we have one, so clicking Download right after
      // a preview doesn't recompile the PDF server-side for no reason.
      if (pdfUrl) {
        const a = document.createElement("a");
        a.href = pdfUrl;
        a.download = "resume.pdf";
        a.click();
        return;
      }
      api
        .previewResumePdf()
        .then((url) => {
          const a = document.createElement("a");
          a.href = url;
          a.download = "resume.pdf";
          a.click();
        })
        .catch((e) => setError(e.message));
      return;
    }
    window.open(api.downloadResumeUrl(fmt), "_blank");
  }

  const refreshPreview = useCallback(async () => {
    setPreviewing(true);
    setPreviewError(null);
    try {
      const url = await api.previewResumePdf();
      // Release the previous blob � without this every recompile leaks a few hundred KB
      // that the browser holds until the tab closes.
      setPdfUrl((old) => {
        if (old) URL.revokeObjectURL(old);
        return url;
      });
    } catch (e) {
      setPreviewError(e instanceof ApiError ? e.message : "Could not render PDF");
    } finally {
      setPreviewing(false);
    }
  }, []);

  const hasLatex = Boolean(draftLatex);

  // Render on first switch to the preview tab, not on every keystroke — compiling LaTeX
  // is a real server-side cost, so it's an explicit "Re-render" action after that.
  useEffect(() => {
    if (tab === "preview" && !pdfUrl && hasLatex) refreshPreview();
  }, [tab, pdfUrl, hasLatex, refreshPreview]);

  return (
    <AppShell>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Resume</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Upload, edit, or ask the assistant to rewrite it. Every save creates a new
            version — nothing is ever overwritten.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInput}
            type="file"
            accept=".tex,.latex,.pdf,.docx,.txt,.md"
            onChange={handleUpload}
            className="hidden"
          />
          <button
            onClick={() => fileInput.current?.click()}
            disabled={busy}
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Upload file
          </button>
          <button
            onClick={() => download("txt")}
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            .txt
          </button>
          <button
            onClick={() => download("tex")}
            disabled={!hasLatex}
            title={hasLatex ? "" : "No LaTeX yet — ask the assistant to convert it"}
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-50 disabled:opacity-40 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            .tex
          </button>
          <button
            onClick={() => download("pdf")}
            disabled={!hasLatex}
            className="rounded bg-zinc-900 px-3 py-1.5 text-sm text-white disabled:opacity-40 dark:bg-white dark:text-zinc-900"
          >
            .pdf
          </button>
        </div>
      </div>

      <p className="mb-4 text-xs text-zinc-500">
        Accepts <strong>.tex</strong>, .pdf, .docx, .txt. Upload <strong>.tex</strong> if you
        have it — it&apos;s the only format where an AI edit can produce a document you can
        compile and send straight back out. PDF text extraction is one-way.
      </p>

      {status && (
        <div className="mb-4 rounded border border-green-200 bg-green-50 p-3 text-sm text-green-800 dark:border-green-900 dark:bg-green-950 dark:text-green-300">
          {status}
        </div>
      )}
      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
        {/* ---------- editor ---------- */}
        <section className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2 dark:border-zinc-800">
            <div className="flex gap-1">
              {(["text", "latex", "preview"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  disabled={t !== "text" && !hasLatex}
                  title={t !== "text" && !hasLatex ? "Needs a LaTeX version" : ""}
                  className={`rounded px-3 py-1 text-xs disabled:opacity-40 ${
                    tab === t
                      ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                      : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                  }`}
                >
                  {t === "text" ? "Plain text" : t === "latex" ? "LaTeX" : "PDF preview"}
                </button>
              ))}
            </div>

            <div className="flex gap-2">
              {tab === "preview" && (
                <button
                  onClick={refreshPreview}
                  disabled={previewing}
                  className="rounded border border-zinc-300 px-3 py-1 text-xs disabled:opacity-40 dark:border-zinc-700"
                >
                  {previewing ? "Rendering…" : "Re-render"}
                </button>
              )}
              <button
                onClick={handleSave}
                disabled={busy || !dirty}
                className="rounded bg-zinc-900 px-3 py-1 text-xs text-white disabled:opacity-40 dark:bg-white dark:text-zinc-900"
              >
                {dirty ? "Save as new version" : "Saved"}
              </button>
            </div>
          </div>

          {tab === "preview" ? (
            <div className="h-[520px] p-2">
              {previewError ? (
                <div className="p-4 text-xs text-red-600">
                  {previewError}
                  <p className="mt-2 text-zinc-500">
                    LaTeX compile errors usually mean an unsupported package. The assistant is
                    told to stick to article/geometry/enumitem/hyperref — ask it to simplify
                    the preamble.
                  </p>
                </div>
              ) : previewing && !pdfUrl ? (
                <p className="p-4 text-xs text-zinc-500">Compiling LaTeX…</p>
              ) : pdfUrl ? (
                <iframe src={pdfUrl} className="h-full w-full rounded" title="Resume PDF preview" />
              ) : (
                <p className="p-4 text-xs text-zinc-500">Nothing rendered yet.</p>
              )}
            </div>
          ) : (
            <textarea
              value={tab === "text" ? draftText : draftLatex}
              onChange={(e) => {
                if (tab === "text") setDraftText(e.target.value);
                else setDraftLatex(e.target.value);
                setDirty(true);
              }}
              placeholder={
                active?.exists
                  ? ""
                  : "Upload a file, paste your resume here, or ask the assistant to help you write one."
              }
              className="h-[520px] w-full resize-y bg-transparent p-4 font-mono text-xs outline-none"
              spellCheck={false}
            />
          )}
        </section>

        {/* ---------- assistant + versions ---------- */}
        <div className="space-y-5">
          <section className="flex h-[460px] flex-col rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="border-b border-zinc-200 px-4 py-2 text-sm font-semibold dark:border-zinc-800">
              Resume assistant
            </h2>

            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {!chat.length && (
                <div className="space-y-2">
                  <p className="text-xs text-zinc-500">Ask for anything, e.g.:</p>
                  {QUICK_ASKS.map((q) => (
                    <button
                      key={q}
                      onClick={() => send(q)}
                      className="block w-full rounded border border-zinc-200 px-2 py-1.5 text-left text-xs text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              )}

              {chat.map((turn, i) => (
                <div
                  key={i}
                  className={`rounded p-2 text-xs ${
                    turn.role === "user"
                      ? "bg-zinc-100 dark:bg-zinc-800"
                      : "border border-zinc-200 dark:border-zinc-700"
                  }`}
                >
                  <div className="mb-1 font-medium text-zinc-500">
                    {turn.role === "user" ? "You" : "Assistant"}
                  </div>
                  <p className="whitespace-pre-wrap text-zinc-800 dark:text-zinc-200">{turn.text}</p>
                  {turn.toolCalls && turn.toolCalls.length > 0 && (
                    <div className="mt-2 border-t border-zinc-200 pt-1 dark:border-zinc-700">
                      <span className="text-[10px] text-zinc-400">
                        tools used: {turn.toolCalls.map((t) => t.tool).join(", ")}
                      </span>
                    </div>
                  )}
                </div>
              ))}

              {thinking && <p className="text-xs text-zinc-500">Working on your resume…</p>}
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                send(message);
              }}
              className="border-t border-zinc-200 p-3 dark:border-zinc-800"
            >
              <div className="flex gap-2">
                <input
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Ask for a change…"
                  className="flex-1 rounded border border-zinc-300 px-2 py-1.5 text-xs dark:border-zinc-700 dark:bg-zinc-800"
                />
                <button
                  type="submit"
                  disabled={thinking}
                  className="rounded bg-zinc-900 px-3 py-1.5 text-xs text-white disabled:opacity-50 dark:bg-white dark:text-zinc-900"
                >
                  Send
                </button>
              </div>
            </form>
          </section>

          <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="mb-2 text-sm font-semibold">Versions</h2>
            <p className="mb-3 text-[11px] text-zinc-500">
              Every edit is kept. Click any version to restore it.
            </p>
            <ul className="max-h-56 space-y-2 overflow-y-auto">
              {versions.map((v) => (
                <li key={v.id}>
                  <button
                    onClick={() =>
                      api.activateResumeVersion(v.id).then(load).catch((e) => setError(e.message))
                    }
                    className={`w-full rounded border px-2 py-1.5 text-left text-xs ${
                      v.is_active
                        ? "border-zinc-900 dark:border-white"
                        : "border-zinc-200 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{v.label}</span>
                      {v.is_active && <span className="shrink-0 text-[10px] text-zinc-500">active</span>}
                    </div>
                    <div className="mt-0.5 flex gap-2 text-[10px] text-zinc-500">
                      <span>{v.origin.replace("_", " ")}</span>
                      {v.has_latex && <span>· LaTeX</span>}
                      <span>· {new Date(v.created_at).toLocaleDateString()}</span>
                    </div>
                    {v.change_summary && (
                      <p className="mt-1 text-[10px] text-zinc-500">{v.change_summary}</p>
                    )}
                  </button>
                </li>
              ))}
              {!versions.length && (
                <li className="text-xs text-zinc-500">No versions yet — upload or paste to start.</li>
              )}
            </ul>
          </section>
        </div>
      </div>
    </AppShell>
  );
}
