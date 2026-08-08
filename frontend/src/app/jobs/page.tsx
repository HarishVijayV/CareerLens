"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { api, Job } from "@/lib/api";

const PAGE_SIZE = 20;

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filter values come from the warehouse, not hardcoded — so the options always match
  // what's actually in the data, and a filter can never silently return zero results
  // because the user guessed a spelling the DB doesn't use.
  const [filters, setFilters] = useState<{
    skills: string[]; regions: string[]; seniorities: string[]; pay_bands: string[];
  }>({ skills: [], regions: [], seniorities: [], pay_bands: [] });
  const [payBand, setPayBand] = useState("");
  const [region, setRegion] = useState("");

  const [q, setQ] = useState("");
  const [skill, setSkill] = useState("");
  const [seniority, setSeniority] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [minSalary, setMinSalary] = useState("");

  async function load(newOffset = 0) {
    setLoading(true);
    setError(null);
    try {
      const res = await api.searchJobs({
        q,
        skill,
        seniority,
        region,
        pay_band: payBand,
        remote_only: remoteOnly,
        min_salary: minSalary ? Number(minSalary) : undefined,
        limit: PAGE_SIZE,
        offset: newOffset,
      });
      setJobs(res.jobs);
      setTotal(res.total);
      setOffset(newOffset);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    api.jobFilters().then(setFilters).catch(() => {});
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const money = (v: number | null) => (v ? `$${v.toLocaleString()}` : "—");

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Jobs</h1>
        <p className="mt-1 text-base text-zinc-500">
          Searching the curated warehouse — {total.toLocaleString()} postings match.
        </p>
      </div>

      {/* filters in a single row above the results, per the interaction rules */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          load(0);
        }}
        className="mb-5 flex flex-wrap items-end gap-3 rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
      >
        <label className="flex flex-col gap-1 text-sm text-zinc-500">
          Title
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. Data Engineer"
            className="w-44 rounded border border-zinc-300 px-3 py-2 text-[15px] dark:border-zinc-700 dark:bg-zinc-800"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-zinc-500">
          Skill
          <select
            value={skill}
            onChange={(e) => setSkill(e.target.value)}
            className="w-36 rounded border border-zinc-300 px-3 py-2 text-[15px] dark:border-zinc-700 dark:bg-zinc-800"
          >
            <option value="">Any skill</option>
            {filters.skills.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm text-zinc-500">
          Region
          <select
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            className="w-36 rounded border border-zinc-300 px-3 py-2 text-[15px] dark:border-zinc-700 dark:bg-zinc-800"
          >
            <option value="">Any region</option>
            {filters.regions.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm text-zinc-500">
          Pay vs market
          <select
            value={payBand}
            onChange={(e) => setPayBand(e.target.value)}
            className="w-36 rounded border border-zinc-300 px-3 py-2 text-[15px] dark:border-zinc-700 dark:bg-zinc-800"
          >
            <option value="">Any</option>
            <option value="above_market">Above market</option>
            <option value="at_market">At market</option>
            <option value="below_market">Below market</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-zinc-500">
          Seniority
          <select
            value={seniority}
            onChange={(e) => setSeniority(e.target.value)}
            className="w-28 rounded border border-zinc-300 px-3 py-2 text-[15px] dark:border-zinc-700 dark:bg-zinc-800"
          >
            <option value="">Any</option>
            {filters.seniorities.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-zinc-500">
          Min salary
          <input
            type="number"
            value={minSalary}
            onChange={(e) => setMinSalary(e.target.value)}
            placeholder="100000"
            className="w-28 rounded border border-zinc-300 px-3 py-2 text-[15px] dark:border-zinc-700 dark:bg-zinc-800"
          />
        </label>
        <label className="flex items-center gap-2 pb-1.5 text-sm text-zinc-600 dark:text-zinc-400">
          <input
            type="checkbox"
            checked={remoteOnly}
            onChange={(e) => setRemoteOnly(e.target.checked)}
          />
          Remote only
        </label>
        <button
          type="submit"
          disabled={loading}
          className="rounded bg-zinc-900 px-4 py-1.5 text-sm text-white disabled:opacity-50 dark:bg-white dark:text-zinc-900"
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <table className="w-full text-left text-[15px]">
          <thead className="border-b border-zinc-200 text-xs text-zinc-500 dark:border-zinc-800">
            <tr>
              <th className="px-4 py-2.5 font-medium">Title</th>
              <th className="px-4 py-2.5 font-medium">Company</th>
              <th className="px-4 py-2.5 font-medium">Location</th>
              <th className="px-4 py-2.5 font-medium">Level</th>
              <th className="px-4 py-2.5 text-right font-medium">Salary</th>
              <th className="px-4 py-2.5 font-medium" title="Spark MLlib prediction vs the advertised salary">
                vs market
              </th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr
                key={job.posting_id}
                className="border-b border-zinc-100 last:border-0 hover:bg-zinc-50 dark:border-zinc-800/60 dark:hover:bg-zinc-800/40"
              >
                <td className="px-4 py-2.5 font-medium text-zinc-900 dark:text-zinc-100">
                  {job.title}
                  {job.remote && (
                    <span className="ml-2 rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                      remote
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-400">{job.company_name ?? "—"}</td>
                <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-400">{job.location ?? "—"}</td>
                <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-400">{job.seniority ?? "—"}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-zinc-700 dark:text-zinc-300">
                  {money(job.salary)}
                </td>
                <td className="px-4 py-2">
                  {job.pay_band && job.pay_band !== "unknown" ? (
                    <span
                      title={`Model predicts ${money(job.predicted_salary ?? null)} for this role`}
                      className={`rounded px-1.5 py-0.5 text-[10px] ${
                        job.pay_band === "above_market"
                          ? "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300"
                          : job.pay_band === "below_market"
                          ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                          : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                      }`}
                    >
                      {job.pay_band === "above_market"
                        ? `+${money(job.salary_vs_market ?? null)}`
                        : job.pay_band === "below_market"
                        ? money(job.salary_vs_market ?? null)
                        : "at market"}
                    </span>
                  ) : (
                    <span className="text-[10px] text-zinc-400">—</span>
                  )}
                </td>
              </tr>
            ))}
            {!jobs.length && !loading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-sm text-zinc-500">
                  No postings match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex items-center justify-between text-sm">
        <span className="text-zinc-500">
          {total ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total.toLocaleString()}` : ""}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => load(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0 || loading}
            className="rounded border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
          >
            Previous
          </button>
          <button
            onClick={() => load(offset + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= total || loading}
            className="rounded border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
          >
            Next
          </button>
        </div>
      </div>
    </AppShell>
  );
}
