"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, User } from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);

  const [jobDescription, setJobDescription] = useState(
    "Looking for a Data Engineer with Spark, Airflow, Kafka, and cloud experience."
  );
  const [skillsResult, setSkillsResult] = useState<string | null>(null);
  const [copilotLoading, setCopilotLoading] = useState(false);
  const [copilotError, setCopilotError] = useState<string | null>(null);

  useEffect(() => {
    // Real enforcement of "must be logged in" happens server-side at the Gateway
    // (AuthMiddleware) — this check is only a UX nicety so a logged-out visitor sees a
    // redirect instead of a page full of failed requests.
    api
      .me()
      .then(setUser)
      .catch(() => router.push("/login"))
      .finally(() => setChecking(false));
  }, [router]);

  async function handleLogout() {
    await api.logout();
    router.push("/login");
  }

  async function handleExtractSkills(e: React.FormEvent) {
    e.preventDefault();
    setCopilotError(null);
    setCopilotLoading(true);
    setSkillsResult(null);
    try {
      const { result } = await api.extractSkills(jobDescription);
      setSkillsResult(JSON.stringify(result, null, 2));
    } catch (err) {
      setCopilotError(
        err instanceof ApiError
          ? `${err.message} — is the agent-service LLM_PROVIDER key set in infra/.env?`
          : "Something went wrong"
      );
    } finally {
      setCopilotLoading(false);
    }
  }

  if (checking) return <main className="p-8">Checking session...</main>;
  if (!user) return null; // already redirecting

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-8 px-6 py-12">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <p className="text-sm text-gray-600">
            Logged in as {user.email} ({user.role})
          </p>
        </div>
        <button onClick={handleLogout} className="rounded border px-3 py-2 text-sm">
          Log out
        </button>
      </header>

      <section className="flex flex-col gap-3 rounded border p-4">
        <h2 className="font-medium">AI Copilot — skill extractor (live demo)</h2>
        <p className="text-sm text-gray-600">
          Paste a job description; the agent-service&apos;s skill-extractor sub-agent
          calls the configured LLM and returns structured requirements. This exercises
          the whole path: Gateway → agent-service → LLM provider abstraction.
        </p>
        <form onSubmit={handleExtractSkills} className="flex flex-col gap-3">
          <textarea
            value={jobDescription}
            onChange={(e) => setJobDescription(e.target.value)}
            rows={4}
            className="rounded border px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={copilotLoading}
            className="self-start rounded bg-black px-3 py-2 text-sm text-white disabled:opacity-50"
          >
            {copilotLoading ? "Thinking..." : "Extract skills"}
          </button>
        </form>
        {copilotError && <p className="text-sm text-red-600">{copilotError}</p>}
        {skillsResult && (
          <pre className="overflow-x-auto rounded bg-gray-50 p-3 text-xs">{skillsResult}</pre>
        )}
      </section>

      <p className="text-sm text-gray-500">
        This is Phase 1-2 scope from docs/ROADMAP.md — resume matching, resume tailoring,
        and the email/funnel features light up as later phases get built.
      </p>
    </main>
  );
}
