"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { api, Job, Profile } from "@/lib/api";

const PAGE_SIZE = 20;

// The profile stores Adzuna country CODES; the warehouse stores region NAMES. Without an
// explicit map the two never compare equal and profile ranking silently does nothing —
// the worst kind of bug, because the UI still says it's matching your profile.
const COUNTRY_TO_REGION: Record<string, string> = {
  in: "India",
  us: "North America",
  ca: "North America",
  gb: "Europe",
  de: "Europe",
  au: "Asia Pacific",
  sg: "Asia Pacific",
};

function profileRegions(profile: Profile | null): string[] {
  if (!profile) return [];
  const regions = (profile.countries || "")
    .split(",")
    .map((c) => COUNTRY_TO_REGION[c.trim().toLowerCase()])
    .filter(Boolean);
  // Remote roles are location-independent, so they belong with whatever you picked.
  return Array.from(new Set([...regions, "Remote"]));
}

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
    source_counts?: { real?: number; synthetic?: number };
  }>({ skills: [], regions: [], seniorities: [], pay_bands: [] });
  const [payBand, setPayBand] = useState("");
  const [region, setRegion] = useState("");
  const [sourceType, setSourceType] = useState("");

  // Profile-driven relevance, on by default.
  //
  // Ranking, not filtering: someone in India should see Indian roles first — clicking a
  // US listing and being told "not available in your region" is a wasted click — but
  // hiding US roles outright would be wrong for exactly the same person, who is moving
  // there for a Master's. Update the profile and the priority follows; the toggle exists
  // for the moment you want to browse the whole market anyway.
  const [profile, setProfile] = useState<Profile | null>(null);
  const [matchProfile, setMatchProfile] = useState(true);

  const [q, setQ] = useState("");
  const [skill, setSkill] = useState("");
  const [seniority, setSeniority] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [minSalary, setMinSalary] = useState("");

  // posting_id -> true once tracked. Kept per-render rather than re-fetching applications
  // on every search: the button only needs to stop offering to add the same job twice.
  const [applied, setApplied] = useState<Record<string, boolean>>({});
  const [applying, setApplying] = useState<string | null>(null);

  /** Open the real listing AND record the application in one action.
   *
   * These belong together. Applying on the job board and then remembering to log it here
   * is exactly the step people skip, which is how an application tracker ends up emptier
   * than the truth and its funnel chart becomes fiction.
   *
   * The tab is opened FIRST and synchronously inside the click handler — opening it after
   * `await` makes the browser treat it as an unrequested popup and block it.
   */
  async function applyTo(job: Job) {
    if (job.url) window.open(job.url, "_blank", "noopener,noreferrer");
    setApplying(job.posting_id);
    try {
      await api.createApplication({
        company: job.company_name ?? "Unknown",
        role: job.title ?? undefined,
        posting_id: job.posting_id,
        status: "applied",
      });
      setApplied((prev) => ({ ...prev, [job.posting_id]: true }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the application");
    } finally {
      setApplying(null);
    }
  }

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
        source_type: sourceType,
        remote_only: remoteOnly,
        min_salary: minSalary ? Number(minSalary) : undefined,
        prioritize_regions: matchProfile ? profileRegions(profile).join(",") : undefined,
        prioritize_skills: matchProfile ? (profile?.skills ?? undefined) : undefined,
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
    // Load the profile, then re-search with it. The first load runs without it rather
    // than blocking the page on a second request — results appear immediately and
    // re-order once the profile lands.
    api
      .getProfile()
      .then((p) => setProfile(p))
      .catch(() => {});
    load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-rank whenever the profile arrives or the toggle flips. Without this the profile
  // would load into state and change nothing until the user happened to press Search —
  // the feature would look broken precisely when it first matters.
  useEffect(() => {
    if (profile) load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, matchProfile]);

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

        <label
          className="flex cursor-pointer select-none items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400"
          title={
            profile
              ? `Ranks ${profileRegions(profile).join(", ") || "your regions"} first, then roles wanting your skills`
              : "Loading your profile…"
          }
        >
          <input
            type="checkbox"
            checked={matchProfile}
            onChange={(e) => setMatchProfile(e.target.checked)}
            className="h-4 w-4"
          />
          Match my profile
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

        {/* Provenance filter. Counts are shown in the labels because "real postings" is
            only meaningful next to how many there are — 4,911 of 151,883 sets a very
            different expectation than the bare word does. */}
        <label className="flex flex-col gap-1 text-sm text-zinc-500">
          Source
          <select
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value)}
            className="w-44 rounded border border-zinc-300 px-3 py-2 text-[15px] dark:border-zinc-700 dark:bg-zinc-800"
          >
            <option value="">All (real listed first)</option>
            <option value="real">
              Real job-board only
              {filters.source_counts?.real ? ` (${filters.source_counts.real.toLocaleString()})` : ""}
            </option>
            <option value="synthetic">
              Generated only
              {filters.source_counts?.synthetic
                ? ` (${filters.source_counts.synthetic.toLocaleString()})`
                : ""}
            </option>
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
              <th className="px-4 py-2.5 text-right font-medium">Apply</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr
                key={job.posting_id}
                className="border-b border-zinc-100 last:border-0 hover:bg-zinc-50 dark:border-zinc-800/60 dark:hover:bg-zinc-800/40"
              >
                <td className="px-4 py-2.5 font-medium text-zinc-900 dark:text-zinc-100">
                  {job.url ? (
                    // A real posting has somewhere to apply. Linking the title is the
                    // whole point of ingesting real data — without it the row is just
                    // as inert as a generated one.
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline decoration-zinc-300 underline-offset-2 hover:decoration-current"
                    >
                      {job.title}
                    </a>
                  ) : (
                    job.title
                  )}
                  {job.is_real ? (
                    <span
                      title={`Live posting from ${job.source ?? "a job board"} — the link opens the real listing`}
                      className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400"
                    >
                      live
                    </span>
                  ) : (
                    <span
                      title="Generated posting — exists to give the pipeline volume, not applyable"
                      className="ml-2 rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-500"
                    >
                      sample
                    </span>
                  )}
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

                <td className="px-4 py-2 text-right">
                  {applied[job.posting_id] ? (
                    <span
                      className="text-xs text-emerald-700 dark:text-emerald-400"
                      title="Added to your Applications — track its status there"
                    >
                      ✓ Tracked
                    </span>
                  ) : job.is_real ? (
                    <button
                      onClick={() => applyTo(job)}
                      disabled={applying === job.posting_id}
                      className="rounded border border-zinc-300 px-2.5 py-1 text-xs font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                    >
                      {applying === job.posting_id ? "…" : "Apply"}
                    </button>
                  ) : (
                    // Generated postings have nowhere to apply. A disabled-looking dash is
                    // honest; an Apply button that opened nothing would be worse than none.
                    <span
                      className="text-xs text-zinc-400"
                      title="Generated posting — no real listing to apply to"
                    >
                      —
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {!jobs.length && !loading && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-zinc-500">
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
