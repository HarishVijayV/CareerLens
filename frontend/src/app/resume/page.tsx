"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ActiveResume, api, ApiError, ResumeVersion, ToolCall } from "@/lib/api";

interface ChatTurn {
  role: "user" | "assistant";
  text: string;
  toolCalls?: ToolCall[];
}

const RESUME_CHAT_KEY = "careerlens.resume.chat";

const QUICK_ASKS = [
  "Convert my resume to LaTeX",
  "Rewrite my bullets to emphasise data engineering",
  "Add measurable impact to my experience bullets",
];

type Tab = "document" | "text" | "latex";

export default function ResumePage() {
  const [active, setActive] = useState<ActiveResume | null>(null);
  const [versions, setVersions] = useState<ResumeVersion[]>([]);
  const [tab, setTab] = useState<Tab>("document");
  const [draftText, setDraftText] = useState("");
  const [draftLatex, setDraftLatex] = useState("");
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);

  /* The resume conversation survives navigation, same as the Assistant's.
   *
   * Routing away unmounts this page, so the chat went with it — and a resume rewrite takes
   * 30-90 seconds, which is exactly long enough that switching tabs to do something else
   * is the natural thing to do. Coming back to an empty panel makes it look like the
   * request failed when it actually succeeded and saved a new version. */
  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [chatRestored, setChatRestored] = useState(false);

  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(RESUME_CHAT_KEY);
      if (saved) setChat(JSON.parse(saved));
    } catch {
      // A corrupt entry must never stop the page loading.
    }
    setChatRestored(true);
  }, []);

  useEffect(() => {
    if (!chatRestored) return;   // don't write the empty initial state over saved turns
    try {
      sessionStorage.setItem(RESUME_CHAT_KEY, JSON.stringify(chat));
    } catch {
      // Quota exceeded — keep working in memory.
    }
  }, [chat, chatRestored]);
  const [message, setMessage] = useState("");
  const [thinking, setThinking] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  // Which version the current PDF blob belongs to, so a reload is only forced on a change.
  const activeIdRef = useRef<string | null>(null);

  const hasLatex = Boolean(draftLatex);
  // A document view is possible either from stored LaTeX (compiled) or from an original
  // uploaded PDF (served back as-is).
  const canShowDocument = hasLatex || Boolean(active?.has_original_pdf);

  const load = useCallback(async () => {
    const [a, v] = await Promise.all([api.getActiveResume(), api.listResumeVersions()]);
    setActive(a);
    setVersions(v);
    setDraftText(a.content_text ?? "");
    setDraftLatex(a.content_latex ?? "");
    setDirty(false);

    // Drop the cached PDF only when the active version actually changed — otherwise
    // load(), which runs after every chat message, would discard a perfectly current
    // render and recompile it. That needless recompile was the visible "blink".
    //
    // The comparison is captured BEFORE the state update, not read inside it. Reading
    // activeIdRef from within the setPdfUrl updater was a race: React runs updaters
    // asynchronously, so by the time it ran, the line below had already advanced the ref
    // to the NEW id — the check compared the new id against itself, concluded nothing had
    // changed, and kept the stale PDF. The result was the opposite of the bug it fixed:
    // the agent rewrote the resume, the LaTeX tab showed the new text, and the PDF still
    // showed the old document until a manual refresh.
    //
    // A stale-closure race like this is exactly what refs invite; comparing plain values
    // taken at a known point avoids the question entirely.
    const previousId = activeIdRef.current;
    const versionChanged = previousId !== (a.id ?? null);
    activeIdRef.current = a.id ?? null;

    if (versionChanged) {
      setPdfUrl((old) => {
        if (old) URL.revokeObjectURL(old);
        return null;      // null triggers the render effect, which fetches the new PDF
      });
      setPdfError(null);
    }
  }, []);

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [load]);

  const renderPdf = useCallback(async () => {
    setRendering(true);
    setPdfError(null);
    try {
      const url = await api.previewResumePdf();
      setPdfUrl((old) => {
        if (old) URL.revokeObjectURL(old);   // release the previous blob or it leaks
        return url;
      });
    } catch (e) {
      setPdfError(e instanceof ApiError ? e.message : "Could not render the document");
    } finally {
      setRendering(false);
    }
  }, []);

  // Render once when the document tab is shown and there's something to render. Not on
  // every keystroke — compiling LaTeX is real server-side work.
  useEffect(() => {
    if (tab === "document" && canShowDocument && !pdfUrl && !pdfError && !rendering) {
      renderPdf();
    }
  }, [tab, canShowDocument, pdfUrl, pdfError, rendering, renderPdf]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const version = await api.uploadResume(file);
      setStatus(`Uploaded ${version.label}`);
      await load();
      setTab("document");
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
      setChat((c) => [...c, { role: "assistant", text: result.answer, toolCalls: result.tool_calls }]);
      await load();   // the agent saved a new version; show what it actually persisted
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "The assistant call failed — is an LLM key set in infra/.env?"
      );
    } finally {
      setThinking(false);
    }
  }

  async function deleteVersion(id: string, label: string) {
    if (!confirm(`Delete "${label}"? This cannot be undone.`)) return;
    try {
      await api.deleteResumeVersion(id);
      setStatus(`Deleted ${label}`);
      await load();
    } catch (e) {
      // The backend refuses to delete the active or last-remaining version, and its
      // message explains what to do instead — surface it verbatim.
      setError(e instanceof ApiError ? e.message : "Could not delete");
    }
  }

  async function download(fmt: "tex" | "txt" | "pdf") {
    if (fmt === "pdf") {
      try {
        const url = pdfUrl ?? (await api.previewResumePdf());
        const a = document.createElement("a");
        a.href = url;
        a.download = "resume.pdf";
        a.click();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Download failed");
      }
      return;
    }
    window.open(api.downloadResumeUrl(fmt), "_blank");
  }

  const tabs: { id: Tab; label: string; disabled: boolean; hint?: string }[] = [
    { id: "document", label: "Document", disabled: !canShowDocument,
      hint: canShowDocument ? undefined : "Upload a PDF/.tex, or ask the assistant to convert to LaTeX" },
    { id: "text", label: "Text", disabled: false },
    { id: "latex", label: "LaTeX", disabled: !hasLatex,
      hint: hasLatex ? undefined : "No LaTeX yet — ask the assistant to convert it" },
  ];

  return (
    <AppShell>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Resume</h1>
          <p className="mt-1 text-base text-[var(--text-muted)]">
            Upload it, edit it, or ask the assistant to rewrite it. Every save is a new
            version — nothing is overwritten.
          </p>
        </div>

        <div className="flex items-center gap-2">
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
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]"
          >
            {busy ? "Uploading…" : "Upload resume"}
          </button>

          {/* Downloads grouped into one control instead of three loose buttons, which
              read as unrelated actions and cluttered the header. */}
          <div className="flex overflow-hidden rounded-lg border border-[var(--border-strong)]">
            <button
              onClick={() => download("pdf")}
              disabled={!canShowDocument}
              className="px-3 py-2 text-sm hover:bg-[var(--surface-page)] disabled:opacity-40 dark:hover:bg-zinc-800"
            >
              PDF
            </button>
            <button
              onClick={() => download("tex")}
              disabled={!hasLatex}
              className="border-l border-[var(--border-strong)] px-3 py-2 text-sm hover:bg-[var(--surface-page)] disabled:opacity-40 dark:hover:bg-zinc-800"
            >
              .tex
            </button>
            <button
              onClick={() => download("txt")}
              className="border-l border-[var(--border-strong)] px-3 py-2 text-sm hover:bg-[var(--surface-page)] dark:hover:bg-zinc-800"
            >
              .txt
            </button>
          </div>
        </div>
      </div>

      {status && (
        <div className="mb-4 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800 dark:border-green-900 dark:bg-green-950 dark:text-green-300">
          {status}
        </div>
      )}
      {error && (
        <div className="mb-4 whitespace-pre-wrap rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {!active?.exists && (
        <div className="rounded-lg border border-dashed border-[var(--border-strong)] p-12 text-center">
          <p className="text-sm font-medium">No resume yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-[var(--text-muted)]">
            Upload a <strong>.pdf</strong>, <strong>.tex</strong>, <strong>.docx</strong> or
            <strong> .txt</strong>. Upload <strong>.tex</strong> if you have it — it&apos;s the
            only format where an AI edit produces a document you can compile and send straight
            back out.
          </p>
          <button
            onClick={() => fileInput.current?.click()}
            className="mt-4 rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]"
          >
            Choose a file
          </button>
        </div>
      )}

      {active?.exists && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
          {/* ---------- viewer / editor ---------- */}
          <section className="overflow-hidden rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-card)]">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-subtle)] px-3 py-2">
              <div className="flex gap-1">
                {tabs.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setTab(t.id)}
                    disabled={t.disabled}
                    title={t.hint}
                    className={`rounded px-3 py-1.5 text-xs transition disabled:opacity-40 ${
                      tab === t.id
                        ? "bg-zinc-900 text-white dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]"
                        : "text-[var(--text-secondary)] hover:bg-[var(--surface-sunken)] dark:hover:bg-zinc-800"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                {tab === "document" && (
                  <button
                    onClick={renderPdf}
                    disabled={rendering || !canShowDocument}
                    className="rounded border border-[var(--border-strong)] px-2.5 py-1 text-xs disabled:opacity-40"
                  >
                    {rendering ? "Rendering…" : "Refresh"}
                  </button>
                )}
                {tab !== "document" && (
                  <button
                    onClick={handleSave}
                    disabled={busy || !dirty}
                    className="rounded bg-zinc-900 px-3 py-1 text-xs text-white disabled:opacity-40 dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]"
                  >
                    {dirty ? "Save as new version" : "Saved"}
                  </button>
                )}
              </div>
            </div>

            {tab === "document" ? (
              <div className="h-[calc(100vh-230px)] min-h-[600px] bg-[var(--surface-sunken)]">
                {pdfError ? (
                  <div className="p-5">
                    <p className="whitespace-pre-wrap text-xs text-red-600">{pdfError}</p>
                    <button
                      onClick={() => send("Fix the LaTeX so it compiles — use only standard packages (article, geometry, enumitem, hyperref)")}
                      className="mt-3 rounded bg-zinc-900 px-3 py-1.5 text-xs text-white dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]"
                    >
                      Ask the assistant to fix it
                    </button>
                  </div>
                ) : !canShowDocument ? (
                  // No LaTeX and no uploaded PDF, so there is genuinely nothing to render.
                  // This used to fall through to "Rendering document…" and sit there
                  // forever — a spinner that waits for something nobody is producing,
                  // which reads as "slow" when the real answer is "not possible yet".
                  // AI-tailored versions are plain text, so this is the COMMON case right
                  // after a tailor, not an edge case.
                  <div className="p-5">
                    <p className="text-sm font-medium text-[var(--text-secondary)]">
                      This version is plain text.
                    </p>
                    <p className="mt-1 text-xs text-[var(--text-muted)]">
                      There is no LaTeX source or uploaded PDF for{" "}
                      <strong>{active?.label ?? "this version"}</strong>, so there is no
                      document to display. Read it under <strong>Text</strong>, or convert
                      it so it can be rendered and downloaded as a PDF.
                    </p>
                    <button
                      onClick={() => send("Convert my resume to LaTeX")}
                      className="mt-3 rounded bg-zinc-900 px-3 py-1.5 text-xs text-white dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]"
                    >
                      Convert to LaTeX
                    </button>
                  </div>
                ) : rendering || !pdfUrl ? (
                  <p className="p-5 text-xs text-[var(--text-muted)]">Rendering document…</p>
                ) : (
                  // `key` pinned to the URL, so React reuses this iframe across renders
                  // instead of tearing it down and building a new one. Without it any
                  // state change on the page — typing in the chat, a status message —
                  // remounted the iframe, and the PDF viewer reloaded from scratch each
                  // time. That is the blink: not a slow render, a repeated one.
                  <iframe
                    key={pdfUrl}
                    src={pdfUrl}
                    className="h-full w-full"
                    title="Resume document"
                  />
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
                className="h-[calc(100vh-230px)] min-h-[600px] w-full resize-none bg-transparent p-4 font-mono text-xs outline-none"
                spellCheck={false}
              />
            )}
          </section>

          {/* ---------- assistant + versions ---------- */}
          <div className="space-y-5">
            <section className="flex h-[440px] flex-col rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-card)]">
              <h2 className="border-b border-[var(--border-subtle)] px-4 py-2.5 text-sm font-semibold">
                Resume assistant
              </h2>

              <div className="flex-1 space-y-2 overflow-y-auto p-3">
                {!chat.length && (
                  <div className="space-y-1.5">
                    {QUICK_ASKS.map((q) => (
                      <button
                        key={q}
                        onClick={() => send(q)}
                        className="block w-full rounded border border-[var(--border-subtle)] px-2 py-1.5 text-left text-xs text-[var(--text-secondary)] hover:bg-[var(--surface-page)] dark:hover:bg-zinc-800"
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
                        ? "bg-[var(--surface-sunken)]"
                        : "border border-[var(--border-subtle)]"
                    }`}
                  >
                    <div className="mb-1 font-medium text-[var(--text-muted)]">
                      {turn.role === "user" ? "You" : "Assistant"}
                    </div>
                    {turn.role === "user" ? (
                      <p className="whitespace-pre-wrap text-[var(--text-primary)]">{turn.text}</p>
                    ) : (
                      // Same models, same markdown as the Assistant page — bold, headings
                      // and lists arrived here as literal ** and # because this panel
                      // rendered pre-wrapped text.
                      <div className="text-[var(--text-primary)] [&_h2]:mt-2 [&_h2]:mb-1 [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:mt-2 [&_h3]:font-semibold [&_li]:my-0.5 [&_ol]:my-1.5 [&_ol]:list-decimal [&_ol]:pl-4 [&_p]:my-1.5 [&_strong]:font-semibold [&_ul]:my-1.5 [&_ul]:list-disc [&_ul]:pl-4">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.text}</ReactMarkdown>
                      </div>
                    )}
                    {turn.toolCalls?.length ? (
                      <p className="mt-1.5 border-t border-[var(--border-subtle)] pt-1 text-[10px] text-[var(--text-muted)]">
                        tools: {turn.toolCalls.map((t) => t.tool).join(", ")}
                      </p>
                    ) : null}
                  </div>
                ))}

                {thinking && <p className="text-xs text-[var(--text-muted)]">Working…</p>}
              </div>

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  send(message);
                }}
                className="flex gap-2 border-t border-[var(--border-subtle)] p-2.5"
              >
                <input
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Ask for a change…"
                  className="flex-1 rounded border border-[var(--border-strong)] px-2 py-1.5 text-xs"
                />
                <button
                  type="submit"
                  disabled={thinking}
                  className="rounded bg-zinc-900 px-3 py-1.5 text-xs text-white disabled:opacity-50 dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]"
                >
                  Send
                </button>
              </form>
            </section>

            <section className="rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-card)] p-4">
              <h2 className="mb-1 text-base font-semibold">Versions</h2>
              <p className="mb-3 text-[11px] text-[var(--text-muted)]">Click any version to restore it.</p>
              <ul className="max-h-60 space-y-1.5 overflow-y-auto">
                {versions.map((v) => (
                  <li
                    key={v.id}
                    className={`group flex items-start gap-1 rounded border px-2 py-1.5 ${
                      v.is_active
                        ? "border-zinc-900 dark:border-white"
                        : "border-[var(--border-subtle)] hover:bg-[var(--surface-page)] dark:hover:bg-zinc-800"
                    }`}
                  >
                    <button
                      onClick={() =>
                        api.activateResumeVersion(v.id).then(load).catch((e) => setError(e.message))
                      }
                      className="min-w-0 flex-1 text-left text-xs"
                      title={v.is_active ? "Currently active" : "Click to make this the active version"}
                    >
                      <div className="flex items-center gap-2">
                        <span className="truncate font-medium">{v.label}</span>
                        {v.is_active && (
                          <span className="shrink-0 rounded bg-zinc-900 px-1.5 py-0.5 text-[10px] text-white dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]">
                            active
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 text-[10px] text-[var(--text-muted)]">
                        {v.origin.replace("_", " ")}
                        {v.has_latex && " · LaTeX"}
                        {" · "}
                        {new Date(v.created_at).toLocaleDateString()}
                      </div>
                    </button>

                    {!v.is_active && (
                      <button
                        onClick={() => deleteVersion(v.id, v.label)}
                        title="Delete this version"
                        aria-label={`Delete ${v.label}`}
                        className="shrink-0 rounded border border-[var(--border-subtle)] px-2 py-0.5 text-xs text-[var(--text-muted)] transition hover:border-red-300 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950"
                      >
                        Delete
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </div>
      )}
    </AppShell>
  );
}
