"use client";

import { useCallback, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { BarChart, ChartFrame, StatTile } from "@/components/Charts";
import { api, Application, FunnelResponse, GmailStatus, ResumePerformance } from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  applied: "Applied",
  recruiter_outreach: "Recruiter reached out",
  interview_invite: "Interview",
  offer: "Offer",
  rejected: "Rejected",
};

const STATUS_STYLE: Record<string, string> = {
  applied: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  recruiter_outreach: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  interview_invite: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  offer: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export default function ApplicationsPage() {
  const [applications, setApplications] = useState<Application[]>([]);
  const [funnel, setFunnel] = useState<FunnelResponse | null>(null);
  const [performance, setPerformance] = useState<ResumePerformance[]>([]);
  const [gmail, setGmail] = useState<GmailStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(() => {
    api.listApplications().then(setApplications).catch(() => {});
    api.funnel().then(setFunnel).catch(() => {});
    api.resumePerformance().then(setPerformance).catch(() => {});
    api.gmailStatus().then(setGmail).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    if (new URLSearchParams(window.location.search).get("gmail") === "connected") {
      setMessage("Gmail connected. Run a sync to import your applications.");
    }
  }, [load]);

  async function connectGmail() {
    try {
      const { authorization_url } = await api.gmailConnect();
      window.location.href = authorization_url;
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not start Google sign-in");
    }
  }

  async function runSync() {
    setSyncing(true);
    setMessage(null);
    try {
      await api.syncInbox();
      // The sync runs in a Celery worker, so there's nothing to await — poll shortly
      // after instead of blocking the UI on an inbox scan.
      setMessage("Sync queued. Reading your inbox in the background…");
      setTimeout(load, 6000);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <AppShell>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Applications</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Connect Gmail and an AI agent reads your inbox, classifies each message, and
            builds this funnel automatically.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {gmail?.connected ? (
            <>
              <span className="text-xs text-zinc-500">{gmail.google_email}</span>
              <button
                onClick={runSync}
                disabled={syncing}
                className="rounded bg-zinc-900 px-4 py-1.5 text-sm text-white disabled:opacity-50 dark:bg-white dark:text-zinc-900"
              >
                {syncing ? "Syncing…" : "Sync inbox"}
              </button>
            </>
          ) : gmail?.configured ? (
            <button
              onClick={connectGmail}
              className="rounded bg-zinc-900 px-4 py-1.5 text-sm text-white dark:bg-white dark:text-zinc-900"
            >
              Connect Gmail
            </button>
          ) : (
            <span className="max-w-xs text-right text-xs text-zinc-500">
              Gmail not configured — add Google OAuth credentials (see docs/CREDENTIALS.md)
            </span>
          )}
        </div>
      </div>

      {message && (
        <div className="mb-5 rounded border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300">
          {message}
        </div>
      )}

      {funnel && (
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile label="Applications" value={String(funnel.total_applications)} />
          <StatTile
            label="Interviews"
            value={String(funnel.stages.find((s) => s.stage === "interview_invite")?.count ?? 0)}
          />
          <StatTile label="Offers" value={String(funnel.stages.find((s) => s.stage === "offer")?.count ?? 0)} />
          <StatTile label="Awaiting reply" value={String(funnel.awaiting_response)} />
        </div>
      )}

      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        {funnel && funnel.total_applications > 0 && (
          <ChartFrame
            title="Application funnel"
            subtitle="Counted from events, so an application that was later rejected still counts as having reached interview"
            columns={["Stage", "Count", "% of applied"]}
            rows={funnel.stages.map((s) => [
              STATUS_LABEL[s.stage] ?? s.stage,
              s.count,
              `${s.percent_of_applied}%`,
            ])}
          >
            <BarChart
              data={funnel.stages.map((s) => ({
                label: STATUS_LABEL[s.stage] ?? s.stage,
                value: s.count,
              }))}
            />
          </ChartFrame>
        )}

        {performance.length > 0 && (
          <ChartFrame
            title="Resume version performance"
            subtitle="Response rate per resume version — check the sample size before believing it"
            columns={["Version", "Applications", "Responses", "Rate"]}
            rows={performance.map((p) => [
              p.resume_version,
              p.applications,
              p.positive_responses,
              `${p.response_rate_percent}%${p.sample_warning ? " ⚠" : ""}`,
            ])}
          >
            <BarChart
              data={performance.map((p) => ({
                label: p.resume_version,
                value: p.response_rate_percent,
              }))}
              format={(v) => `${v}%`}
            />
          </ChartFrame>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-zinc-200 text-xs text-zinc-500 dark:border-zinc-800">
            <tr>
              <th className="px-4 py-2 font-medium">Company</th>
              <th className="px-4 py-2 font-medium">Role</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Resume</th>
              <th className="px-4 py-2 font-medium">Source</th>
              <th className="px-4 py-2 font-medium">Updated</th>
            </tr>
          </thead>
          <tbody>
            {applications.map((app) => (
              <tr
                key={app.id}
                className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60"
              >
                <td className="px-4 py-2 font-medium text-zinc-900 dark:text-zinc-100">{app.company}</td>
                <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{app.role ?? "—"}</td>
                <td className="px-4 py-2">
                  <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[app.status] ?? ""}`}>
                    {STATUS_LABEL[app.status] ?? app.status}
                  </span>
                </td>
                <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                  {app.resume_version ?? "—"}
                </td>
                <td className="px-4 py-2 text-zinc-500">{app.source}</td>
                <td className="px-4 py-2 text-zinc-500">
                  {new Date(app.updated_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
            {!applications.length && (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-sm text-zinc-500">
                  No applications yet. Connect Gmail and run a sync, or add one manually.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
