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
export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getProfile().then(setProfile).catch((e) => setError(e.message));
  }, []);

  function set<K extends keyof Profile>(key: K, value: Profile[K]) {
    setProfile((p) => (p ? { ...p, [key]: value } : p));
    setSaved(false);
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
        resume_text: profile.resume_text,
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
        <p className="text-sm text-zinc-500">{error ?? "Loading profile…"}</p>
      </AppShell>
    );
  }

  const input =
    "w-full rounded-lg border border-zinc-300 px-3 py-2.5 text-[15px] dark:border-zinc-700 dark:bg-zinc-800";
  const labelCls = "flex flex-col gap-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300";
  const hint = "text-xs font-normal text-zinc-500";

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Your Profile</h1>
        <p className="mt-1 text-base text-zinc-500">
          This drives everything: which jobs get fetched from the job boards, how postings are
          ranked for you, and what the AI agents know when they tailor your resume.
        </p>
      </div>

      <form onSubmit={handleSave} className="max-w-4xl space-y-5">
        <div className="grid gap-5 rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900 sm:grid-cols-2">
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

        <div className="grid gap-5 rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900 sm:grid-cols-2">
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
          <label className="flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-300 sm:col-span-2">
            <input
              type="checkbox"
              checked={profile.remote_only}
              onChange={(e) => set("remote_only", e.target.checked)}
            />
            Remote roles only
          </label>
        </div>

        <div className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <label className={labelCls}>
            Resume
            <span className={hint}>
              Paste your resume text. The resume-tailor agent rewrites THIS for a specific job —
              it can rephrase and reorder, but it is instructed never to invent experience.
            </span>
            <textarea
              className={`${input} min-h-48 font-mono text-xs`}
              value={profile.resume_text ?? ""}
              onChange={(e) => set("resume_text", e.target.value)}
            />
          </label>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-zinc-900 px-6 py-2.5 text-base font-medium text-white disabled:opacity-50 dark:bg-white dark:text-zinc-900"
          >
            {saving ? "Saving…" : "Save profile"}
          </button>
          {saved && <span className="text-sm text-green-700 dark:text-green-500">Saved</span>}
        </div>
      </form>
    </AppShell>
  );
}
