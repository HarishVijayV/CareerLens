"use client";

import Link from "next/link";

/**
 * Shared shell for login and signup.
 *
 * Two columns on desktop, one on mobile. The left panel isn't decoration — a sign-in page
 * for an unfamiliar product should answer "what is this?" before asking for a password,
 * and concrete numbers do that better than a tagline. They're the project's real measured
 * figures, so the page doubles as the first thing an interviewer reads.
 */
export default function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-white dark:bg-zinc-950">
      {/* ---------- brand panel (desktop only) ---------- */}
      <aside className="relative hidden w-1/2 flex-col justify-between overflow-hidden bg-zinc-900 p-12 text-white lg:flex">
        {/* soft radial wash — keeps the dark panel from reading as a flat black slab */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.18]"
          style={{
            backgroundImage:
              "radial-gradient(600px circle at 20% 10%, #2a78d6, transparent 55%), radial-gradient(500px circle at 80% 80%, #1baf7a, transparent 55%)",
          }}
        />

        <div className="relative">
          <span className="text-lg font-semibold tracking-tight">CareerLens</span>
        </div>

        <div className="relative max-w-md">
          <h2 className="text-3xl font-semibold leading-tight">
            Job market intelligence, built from the data up.
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-zinc-400">
            A distributed pipeline processes job postings at scale, a warehouse models them,
            and a team of AI agents helps you find, match and tailor your way into the right
            role.
          </p>

          <dl className="mt-10 grid grid-cols-3 gap-6">
            {[
              { value: "146K+", label: "postings analyzed" },
              { value: "2.3×", label: "faster than MapReduce" },
              { value: "17/17", label: "data quality tests" },
            ].map((stat) => (
              <div key={stat.label}>
                <dt className="text-2xl font-semibold tabular-nums">{stat.value}</dt>
                <dd className="mt-1 text-xs leading-snug text-zinc-500">{stat.label}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="relative flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-600">
          {["PySpark", "Kafka", "Airflow", "dbt", "FastAPI", "Next.js"].map((t) => (
            <span key={t}>{t}</span>
          ))}
        </div>
      </aside>

      {/* ---------- form panel ---------- */}
      <main className="flex w-full flex-col justify-center px-6 py-12 lg:w-1/2 lg:px-16">
        <div className="mx-auto w-full max-w-sm">
          <Link
            href="/"
            className="mb-10 inline-block text-lg font-semibold tracking-tight lg:hidden"
          >
            CareerLens
          </Link>

          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            {title}
          </h1>
          <p className="mt-2 text-sm text-zinc-500">{subtitle}</p>

          <div className="mt-8">{children}</div>

          <p className="mt-8 text-sm text-zinc-500">{footer}</p>
        </div>
      </main>
    </div>
  );
}

/** Shared field styling, so login and signup can't drift apart visually. */
export const fieldClass =
  "w-full rounded-lg border border-zinc-300 bg-white px-3.5 py-2.5 text-sm text-zinc-900 " +
  "outline-none transition placeholder:text-zinc-400 " +
  "focus:border-zinc-900 focus:ring-2 focus:ring-zinc-900/10 " +
  "dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:focus:border-zinc-100 " +
  "dark:focus:ring-zinc-100/10";

export const labelClass =
  "mb-1.5 block text-sm font-medium text-zinc-700 dark:text-zinc-300";

export const buttonClass =
  "w-full rounded-lg bg-zinc-900 px-4 py-2.5 text-sm font-medium text-white transition " +
  "hover:bg-zinc-800 focus:outline-none focus:ring-2 focus:ring-zinc-900/20 " +
  "disabled:cursor-not-allowed disabled:opacity-50 " +
  "dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200";
