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

  const [chat, setChat] = useState<ChatTurn[]>([]);
  const [message, setMessage] = useState("");
  const [thinking, setThinking] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

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

    // Drop any cached PDF — the active version just changed, so a stale render would be
    // showing a different document entirely.
    setPdfUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return null;
    });
    setPdfError(null);
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
          <h1 className="text-xl font-semibold">Resume</h1>
          <p className="mt-1 text-sm text-zinc-500">
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
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-zinc-900"
          >
            {busy ? "Uploading…" : "Upload resume"}
          </button>

          {/* Downloads grouped into one control instead of three loose buttons, which
              read as unrelated actions and cluttered the header. */}
          <div className="flex overflow-hidden rounded-lg border border-zinc-300 dark:border-zinc-700">
            <button
              onClick={() => download("pdf")}
              disabled={!canShowDocument}
              className="px-3 py-2 text-sm hover:bg-zinc-50 disabled:opacity-40 dark:hover:bg-zinc-800"
            >
              PDF
            </button>
            <button
              onClick={() => download("tex")}
              disabled={!hasLatex}
              className="border-l border-zinc-300 px-3 py-2 text-sm hover:bg-zinc-50 disabled:opacity-40 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              .tex
            </button>
            <button
              onClick={() => download("txt")}
              className="border-l border-zinc-300 px-3 py-2 text-sm hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
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
        <div className="rounded-lg border border-dashed border-zinc-300 p-12 text-center dark:border-zinc-700">
          <p className="text-sm font-medium">No resume yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-zinc-500">
            Upload a <strong>.pdf</strong>, <strong>.tex</strong>, <strong>.docx</strong> or
            <strong> .txt</strong>. Upload <strong>.tex</strong> if you have it — it&apos;s the
            only format where an AI edit produces a document you can compile and send straight
            back out.
          </p>
          <button
            onClick={() => fileInput.current?.click()}
            className="mt-4 rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white dark:bg-white dark:text-zinc-900"
          >
            Choose a file
          </button>
        </div>
      )}

      {active?.exists && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_400px]">
          {/* ---------- viewer / editor ---------- */}
          <section className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 px-3 py-2 dark:border-zinc-800">
              <div className="flex gap-1">
                {tabs.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setTab(t.id)}
                    disabled={t.disabled}
                    title={t.hint}
                    className={`rounded px-3 py-1.5 text-xs transition disabled:opacity-40 ${
                      tab === t.id
                        ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                        : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
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
                    className="rounded border border-zinc-300 px-2.5 py-1 text-xs disabled:opacity-40 dark:border-zinc-700"
                  >
                    {rendering ? "Rendering…" : "Refresh"}
                  </button>
                )}
                {tab !== "document" && (
                  <button
                    onClick={handleSave}
                    disabled={busy || !dirty}
                    className="rounded bg-zinc-900 px-3 py-1 text-xs text-white disabled:opacity-40 dark:bg-white dark:text-zinc-900"
                  >
                    {dirty ? "Save as new version" : "Saved"}
                  </button>
                )}
              </div>
            </div>

            {tab === "document" ? (
              <div className="h-[calc(100vh-230px)] min-h-[600px] bg-zinc-100 dark:bg-zinc-950">
                {pdfError ? (
                  <div className="p-5">
                    <p className="whitespace-pre-wrap text-xs text-red-600">{pdfError}</p>
                    <button
                      onClick={() => send("Fix the LaTeX so it compiles — use only standard packages (article, geometry, enumitem, hyperref)")}
                      className="mt-3 rounded bg-zinc-900 px-3 py-1.5 text-xs text-white dark:bg-white dark:text-zinc-900"
                    >
                      Ask the assistant to fix it
                    </button>
                  </div>
                ) : rendering || !pdfUrl ? (
                  <p className="p-5 text-xs text-zinc-500">Rendering document…</p>
                ) : (
                  <iframe src={pdfUrl} className="h-full w-full" title="Resume document" />
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
            <section className="flex h-[440px] flex-col rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="border-b border-zinc-200 px-4 py-2.5 text-sm font-semibold dark:border-zinc-800">
                Resume assistant
              </h2>

              <div className="flex-1 space-y-2 overflow-y-auto p-3">
                {!chat.length && (
                  <div className="space-y-1.5">
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
                    <p className="whitespace-pre-wrap text-zinc-800 dark:text-zinc-200">
                      {turn.text}
                    </p>
                    {turn.toolCalls?.length ? (
                      <p className="mt-1.5 border-t border-zinc-200 pt-1 text-[10px] text-zinc-400 dark:border-zinc-700">
                        tools: {turn.toolCalls.map((t) => t.tool).join(", ")}
                      </p>
                    ) : null}
                  </div>
                ))}

                {thinking && <p className="text-xs text-zinc-500">Working…</p>}
              </div>

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  send(message);
                }}
                className="flex gap-2 border-t border-zinc-200 p-2.5 dark:border-zinc-800"
              >
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
              </form>
            </section>

            <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <h2 className="mb-1 text-sm font-semibold">Versions</h2>
              <p className="mb-3 text-[11px] text-zinc-500">Click any version to restore it.</p>
              <ul className="max-h-52 space-y-1.5 overflow-y-auto">
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
                        {v.is_active && (
                          <span className="shrink-0 text-[10px] text-zinc-500">active</span>
                        )}
                      </div>
                      <div className="mt-0.5 text-[10px] text-zinc-500">
                        {v.origin.replace("_", " ")}
                        {v.has_latex && " · LaTeX"}
                        {" · "}
                        {new Date(v.created_at).toLocaleDateString()}
                      </div>
                    </button>
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
