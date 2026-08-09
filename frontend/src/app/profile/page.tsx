"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { api, Profile } from "@/lib/api";

/**
 * The profile is not a settings page you fill once and forget — it's the INPUT to two
 * things: which jobs get fetched from the job-board APIs (skills/roles/countries become
 * query parameters), and how the agents rank and tailor. That's why it's prominent, and
 * why it explains itself on screen.
 */
// The fields the resume can fill. Everything else on this page (salary floor, remote-only)
// is a PREFERENCE, not a fact about the person — a resume can't know them, so extraction
// must never touch them.
const FILLABLE = [
  "full_name",
  "headline",
  "skills",
  "target_roles",
  "seniority",
  "preferred_locations",
  "countries",
] as const;

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [extractNote, setExtractNote] = useState<string | null>(null);

  useEffect(() => {
    api.getProfile().then(setProfile).catch((e) => setError(e.message));
  }, []);

  function set<K extends keyof Profile>(key: K, value: Profile[K]) {
    setProfile((p) => (p ? { ...p, [key]: value } : p));
    setSaved(false);
  }

  /** Merge a suggestion into the form WITHOUT saving, and without clobbering anything the
   *  user typed themselves. An empty extraction result must never blank an existing value —
   *  the model failing to find a name is not evidence the name is wrong. */
  function applySuggestion(suggestion: Partial<Record<string, string | null>>) {
    setProfile((p) => {
      if (!p) return p;
      const next = { ...p };
      const filled: string[] = [];
      for (const key of FILLABLE) {
        const value = suggestion[key];
        if (value && value.trim()) {
          (next as Record<string, unknown>)[key] = value.trim();
          filled.push(key.replace(/_/g, " "));
        }
      }
      setExtractNote(
        filled.length
          ? `Filled in ${filled.length} field${filled.length === 1 ? "" : "s"}: ${filled.join(", ")}.`
          : "Couldn't find anything usable in that resume."
      );
      return next;
    });
    setSaved(false);
  }

  async function extractFromExisting() {
    setExtracting(true);
    setExtractError(null);
    setExtractNote(null);
    try {
      const res = await api.profileFromResume();
      applySuggestion(res.suggestion);
    } catch (e) {
      setExtractError(e instanceof Error ? e.message : "Couldn't read the resume");
    } finally {
      setExtracting(false);
    }
  }

  /** Upload, then extract. Uploading through the normal resume endpoint on purpose: it
   *  already handles PDF/LaTeX text extraction and version history, so the file you drop
   *  here also becomes a resume version you can tailor and download later — rather than
   *  being read once and thrown away. */
  async function uploadAndExtract(file: File) {
    setExtracting(true);
    setExtractError(null);
    setExtractNote(null);
    try {
      await api.uploadResume(file);
      const res = await api.profileFromResume();
      applySuggestion(res.suggestion);
    } catch (e) {
      setExtractError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setExtracting(false);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!profile) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateProfile({
        full_name: profile.full_name,
        headline: profile.headline,
        skills: profile.skills,
        target_roles: profile.target_roles,
        countries: profile.countries,
        preferred_locations: profile.preferred_locations,
        remote_only: profile.remote_only,
        min_salary: profile.min_salary,
        seniority: profile.seniority,
        // resume_text is deliberately NOT sent: the resume lives in resume_versions now,
        // and sending it from here would let a stale copy overwrite the real one.
      });
      setProfile(updated);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (!profile) {
    return (
      <AppShell>
        <p className="text-sm text-[var(--text-muted)]">{error ?? "Loading profile…"}</p>
      </AppShell>
    );
  }

  const input =
    "w-full rounded-lg border border-[var(--border-strong)] px-3 py-2.5 text-[15px]";
  const labelCls = "flex flex-col gap-1.5 text-sm font-medium text-[var(--text-secondary)]";
  const hint = "text-xs font-normal text-[var(--text-muted)]";

  const filledCount = FILLABLE.filter((k) => (profile[k] ?? "").toString().trim()).length;

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Your Profile</h1>
        <p className="mt-1 text-base text-[var(--text-muted)]">
          This drives everything: which jobs get fetched from the job boards, how postings are
          ranked for you, and what the AI agents know when they tailor your resume.
        </p>
      </div>

      {/* Upload-first. Everything below this box is already written in the resume, so
          asking someone to retype it is busywork — and a retyped skill list drifts out of
          sync with the resume the moment either changes. The fields stay editable because
          extraction is a starting point, not an authority. */}
      <div className="mb-6 max-w-4xl rounded-lg border border-dashed border-[var(--border-strong)] bg-[var(--surface-page)] p-5/50">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              Fill this in from your resume
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              Upload a PDF, .tex or .txt and the fields below get filled in for you. Nothing
              is saved until you review it and press Save.
            </p>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <label
              className={`cursor-pointer rounded-lg border border-[var(--border-strong)] bg-[var(--surface-card)] px-3 py-2 text-sm font-medium hover:bg-[var(--surface-page)] dark:hover:bg-zinc-700 ${
                extracting ? "pointer-events-none opacity-60" : ""
              }`}
            >
              {extracting ? "Reading…" : "Upload resume"}
              <input
                type="file"
                accept=".pdf,.tex,.txt"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  // Reset the input so picking the SAME file twice still fires onChange —
                  // otherwise a failed first attempt can't be retried without picking a
                  // different file, which looks like the button is broken.
                  e.target.value = "";
                  if (file) uploadAndExtract(file);
                }}
              />
            </label>

            <button
              type="button"
              onClick={() => extractFromExisting()}
              disabled={extracting}
              className="rounded-lg px-3 py-2 text-sm text-[var(--text-secondary)] underline-offset-2 hover:underline disabled:opacity-50"
            >
              Use my saved resume
            </button>
          </div>
        </div>

        {extractError && (
          <p className="mt-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-400">
            {extractError}
          </p>
        )}
        {extractNote && (
          <p className="mt-3 rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400">
            {extractNote} Review the fields below, then press <strong>Save profile</strong>.
          </p>
        )}
        {!extractNote && !extractError && filledCount === 0 && (
          <p className="mt-3 text-sm text-[var(--text-muted)]">
            Your profile is empty — job search and matching won&apos;t work well until it has
            your skills.
          </p>
        )}
      </div>

      <form onSubmit={handleSave} className="max-w-4xl space-y-5">
        <div className="grid gap-5 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-card)] p-5 sm:grid-cols-2">
          <label className={labelCls}>
            Full name
            <input
              className={input}
              value={profile.full_name ?? ""}
              onChange={(e) => set("full_name", e.target.value)}
            />
          </label>
          <label className={labelCls}>
            Headline
            <span className={hint}>Your current or target title</span>
            <input
              className={input}
              placeholder="Data Engineer"
              value={profile.headline ?? ""}
              onChange={(e) => set("headline", e.target.value)}
            />
          </label>

          <label className={`${labelCls} sm:col-span-2`}>
            Skills
            <span className={hint}>Comma-separated. Used to score how well you match a job.</span>
            <input
              className={input}
              placeholder="Python, Spark, SQL, Airflow, AWS"
              value={profile.skills ?? ""}
              onChange={(e) => set("skills", e.target.value)}
            />
          </label>

          <label className={`${labelCls} sm:col-span-2`}>
            Target roles
            <span className={hint}>
              Comma-separated. These become the actual search terms sent to the job-board APIs.
            </span>
            <input
              className={input}
              placeholder="Data Engineer, Analytics Engineer"
              value={profile.target_roles ?? ""}
              onChange={(e) => set("target_roles", e.target.value)}
            />
          </label>
        </div>

        <div className="grid gap-5 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-card)] p-5 sm:grid-cols-2">
          <label className={labelCls}>
            Countries
            <span className={hint}>
              Adzuna country codes — `in` India, `us` USA. Both works fine.
            </span>
            <input
              className={input}
              placeholder="in,us"
              value={profile.countries ?? ""}
              onChange={(e) => set("countries", e.target.value)}
            />
          </label>
          <label className={labelCls}>
            Preferred locations
            <input
              className={input}
              placeholder="Bangalore, Remote"
              value={profile.preferred_locations ?? ""}
              onChange={(e) => set("preferred_locations", e.target.value)}
            />
          </label>
          <label className={labelCls}>
            Seniority
            <select
              className={input}
              value={profile.seniority ?? ""}
              onChange={(e) => set("seniority", e.target.value)}
            >
              <option value="">Not set</option>
              <option value="junior">Junior</option>
              <option value="mid">Mid</option>
              <option value="senior">Senior</option>
            </select>
          </label>
          <label className={labelCls}>
            Minimum salary
            <input
              type="number"
              className={input}
              placeholder="100000"
              value={profile.min_salary ?? ""}
              onChange={(e) => set("min_salary", e.target.value ? Number(e.target.value) : null)}
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)] sm:col-span-2">
            <input
              type="checkbox"
              checked={profile.remote_only}
              onChange={(e) => set("remote_only", e.target.checked)}
            />
            Remote roles only
          </label>
        </div>

        {/* The paste-your-resume-text box that used to live here is gone. It predated
            resume uploads and became actively harmful once they existed: it was a SECOND
            copy of the resume, editable here, while the real versions lived on the Resume
            page. Whichever one you edited, the other was silently stale — and the tailor
            agent reads the uploaded version, so text pasted here did nothing at all. */}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-zinc-900 px-6 py-2.5 text-base font-medium text-white disabled:opacity-50 dark:bg-[var(--surface-card)] dark:text-[var(--text-primary)]"
          >
            {saving ? "Saving…" : "Save profile"}
          </button>
          {saved && <span className="text-sm text-green-700 dark:text-green-500">Saved</span>}
        </div>
      </form>
    </AppShell>
  );
}
