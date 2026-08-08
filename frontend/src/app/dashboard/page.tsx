"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import { StatTile } from "@/components/Charts";
import { api, Job, Profile } from "@/lib/api";

interface Overview {
  total_postings: number;
  total_companies: number;
  avg_salary: number;
  remote_percent: number;
  total_skills: number;
}

export default function DashboardPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [matches, setMatches] = useState<Job[]>([]);

  useEffect(() => {
    api.analytics<Overview>("overview").then(setOverview).catch(() => {});
    api
      .getProfile()
      .then((p) => {
        setProfile(p);
        // Use the profile to show relevant jobs immediately, rather than a generic list —
        // the profile is only worth filling in if the app visibly acts on it.
        const firstRole = (p.target_roles ?? "").split(",")[0]?.trim();
        return api.searchJobs({
          q: firstRole || undefined,
          min_salary: p.min_salary ?? undefined,
          remote_only: p.remote_only,
          limit: 5,
        });
      })
      .then((r) => setMatches(r.jobs))
      .catch(() => {});
  }, []);

  const profileComplete = Boolean(profile?.skills && profile?.target_roles);

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-xl font-semibold">
          {profile?.full_name ? `Welcome back, ${profile.full_name.split(" ")[0]}` : "Dashboard"}
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          Job-market data pipeline + multi-agent AI copilot.
        </p>
      </div>

      {!profileComplete && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm dark:border-amber-900 dark:bg-amber-950">
          <p className="font-medium text-amber-900 dark:text-amber-200">Finish your profile first</p>
          <p className="mt-1 text-amber-800 dark:text-amber-300">
            Your skills and target roles drive which jobs get fetched and how the agents rank
            them.{" "}
            <Link href="/profile" className="underline">
              Fill it in →
            </Link>
          </p>
        </div>
      )}

      {overview && (
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile label="Postings analyzed" value={overview.total_postings.toLocaleString()} />
          <StatTile label="Companies" value={overview.total_companies.toLocaleString()} />
          <StatTile label="Average salary" value={`$${overview.avg_salary.toLocaleString()}`} />
          <StatTile label="Remote share" value={`${overview.remote_percent}%`} />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Jobs for you</h2>
            <Link href="/jobs" className="text-xs text-zinc-500 underline">
              See all
            </Link>
          </div>
          {matches.length ? (
            <ul className="space-y-2">
              {matches.map((job) => (
                <li
                  key={job.posting_id}
                  className="flex items-center justify-between gap-3 border-b border-zinc-100 pb-2 last:border-0 dark:border-zinc-800/60"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{job.title}</div>
                    <div className="truncate text-xs text-zinc-500">
                      {job.company_name} · {job.location}
                    </div>
                  </div>
                  <div className="shrink-0 text-sm tabular-nums text-zinc-600 dark:text-zinc-400">
                    {job.salary ? `$${job.salary.toLocaleString()}` : "—"}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-zinc-500">
              No matches yet — fill in your profile, then run the pipeline.
            </p>
          )}
        </section>

        <section className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="mb-3 text-sm font-semibold">What you can do here</h2>
          <ul className="space-y-3 text-sm">
            <li>
              <Link href="/analytics" className="font-medium underline">
                Analytics
              </Link>
              <p className="text-xs text-zinc-500">
                Skill demand, salary by seniority and region, hiring seasonality — all computed
                by the Spark + dbt pipeline.
              </p>
            </li>
            <li>
              <Link href="/copilot" className="font-medium underline">
                AI Copilot
              </Link>
              <p className="text-xs text-zinc-500">
                Ask questions in plain English. Agents call real tools against your data and
                show you every call they made.
              </p>
            </li>
            <li>
              <Link href="/jobs" className="font-medium underline">
                Jobs
              </Link>
              <p className="text-xs text-zinc-500">
                Search the curated warehouse by title, skill, seniority, salary and location.
              </p>
            </li>
          </ul>
        </section>
      </div>
    </AppShell>
  );
}
