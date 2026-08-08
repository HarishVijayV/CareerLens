import Link from "next/link";

/**
 * Landing page.
 *
 * Two audiences at once, and they want different things: a user wants to know what the
 * product does, an interviewer wants to know what was actually built. So the page leads
 * with the product and follows with the engineering — and every number on it is measured,
 * not marketing (sources in pipeline/data/*.json).
 *
 * A server component: no state, no effects, so there's no reason to ship it as client JS.
 */

const STATS = [
  { value: "146,972", label: "job postings processed", detail: "after dedup from 200K raw" },
  { value: "2.3×", label: "faster than MapReduce", detail: "same aggregation, measured" },
  { value: "17/17", label: "data quality tests pass", detail: "dbt, incl. referential integrity" },
  { value: "8", label: "AI agents & tools", detail: "tool-calling, least privilege" },
];

const FEATURES = [
  {
    title: "Job search over a real warehouse",
    body: "Filter 146K postings by title, skill, seniority, salary and region — served from a dbt star schema, not a spreadsheet.",
  },
  {
    title: "Market analytics",
    body: "Which skills are in demand, which actually pay above average, how salaries move by seniority and region, and when hiring peaks.",
  },
  {
    title: "AI copilot that shows its work",
    body: "Ask in plain English. A planner routes to a specialist agent, which calls real tools against your data — and every call it made is displayed.",
  },
  {
    title: "Resume workspace",
    body: "Upload .tex, .pdf or .docx. Edit by hand or ask the assistant to rewrite it, preview the compiled PDF, and roll back any version.",
  },
  {
    title: "Application tracking",
    body: "Connect Gmail and an agent classifies your inbox into applied → interview → offer, then shows which resume version gets more replies.",
  },
  {
    title: "Salary benchmarking",
    body: "A Spark MLlib model scores every posting against what the market pays for that role, so you can filter for roles paying above market.",
  },
];

const STACK = [
  { group: "Data", items: ["PySpark", "Hadoop / MapReduce", "Kafka", "Airflow", "dbt", "Snowflake"] },
  { group: "Backend", items: ["FastAPI", "PostgreSQL", "Redis", "Celery", "JWT", "Docker"] },
  { group: "AI", items: ["Tool-calling agents", "LangGraph", "MCP server", "Fireworks / OpenAI / Anthropic"] },
  { group: "Frontend", items: ["Next.js", "React", "TypeScript", "Tailwind"] },
];

export default function HomePage() {
  return (
    <div className="min-h-screen bg-white text-zinc-900 dark:bg-zinc-950 dark:text-zinc-50">
      {/* ---------------------------------------------------------------- nav */}
      <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
        <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <span className="text-lg font-semibold tracking-tight">CareerLens</span>
          <div className="flex items-center gap-3 text-sm">
            <Link href="/login" className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">
              Log in
            </Link>
            <Link
              href="/signup"
              className="rounded-lg bg-zinc-900 px-4 py-2 font-medium text-white transition hover:bg-zinc-800 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              Get started
            </Link>
          </div>
        </nav>
      </header>

      {/* ---------------------------------------------------------------- hero */}
      <section className="relative overflow-hidden">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.07] dark:opacity-[0.12]"
          style={{
            backgroundImage:
              "radial-gradient(700px circle at 15% 0%, #2a78d6, transparent 55%), radial-gradient(600px circle at 85% 30%, #1baf7a, transparent 55%)",
          }}
        />
        <div className="relative mx-auto max-w-6xl px-6 py-20 sm:py-28">
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-zinc-200 px-3 py-1 text-xs text-zinc-600 dark:border-zinc-800 dark:text-zinc-400">
            <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
            Distributed pipeline · multi-agent AI · running locally
          </p>

          <h1 className="max-w-3xl text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl">
            Understand the job market,
            <br />
            and where you fit in it.
          </h1>

          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-zinc-600 dark:text-zinc-400">
            CareerLens ingests job postings at scale, processes them through a Spark
            pipeline into a modelled warehouse, and puts a team of AI agents on top — to
            find roles, score your resume against them, tailor it, and track every
            application you send.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/signup"
              className="rounded-lg bg-zinc-900 px-6 py-3 text-sm font-medium text-white transition hover:bg-zinc-800 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              Create an account
            </Link>
            <Link
              href="/login"
              className="rounded-lg border border-zinc-300 px-6 py-3 text-sm font-medium transition hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              Sign in
            </Link>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------------- stats */}
      <section className="border-y border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/40">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-8 px-6 py-12 lg:grid-cols-4">
          {STATS.map((stat) => (
            <div key={stat.label}>
              <div className="text-3xl font-semibold tabular-nums">{stat.value}</div>
              <div className="mt-1 text-sm font-medium text-zinc-700 dark:text-zinc-300">
                {stat.label}
              </div>
              <div className="mt-0.5 text-xs text-zinc-500">{stat.detail}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------------- features */}
      <section className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-2xl font-semibold tracking-tight">What it does</h2>
        <div className="mt-10 grid gap-x-10 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature) => (
            <div key={feature.title}>
              <h3 className="text-base font-medium">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
                {feature.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------------- pipeline */}
      <section className="border-y border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/40">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="text-2xl font-semibold tracking-tight">How the data gets here</h2>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
            Nothing reaches the app until it has been cleaned, modelled and tested. If the
            data is wrong, the pipeline fails at the quality gate rather than serving bad
            numbers to a dashboard.
          </p>

          <ol className="mt-10 grid gap-6 md:grid-cols-5">
            {[
              ["Ingest", "Job-board APIs across India and the US, plus a generator for scale"],
              ["Land", "Raw, immutable — so any run can be reprocessed from source"],
              ["Process", "PySpark cleans, dedupes and aggregates; MLlib scores salaries"],
              ["Model", "dbt builds a star schema and runs 17 data-quality tests"],
              ["Serve", "Postgres for the app, Snowflake for historical analytics"],
            ].map(([title, body], i) => (
              <li key={title} className="relative">
                <div className="mb-2 flex h-7 w-7 items-center justify-center rounded-full bg-zinc-900 text-xs font-medium text-white dark:bg-white dark:text-zinc-900">
                  {i + 1}
                </div>
                <h3 className="text-sm font-medium">{title}</h3>
                <p className="mt-1 text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                  {body}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ---------------------------------------------------------------- stack */}
      <section className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-2xl font-semibold tracking-tight">Built with</h2>
        <div className="mt-8 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {STACK.map((column) => (
            <div key={column.group}>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                {column.group}
              </h3>
              <ul className="mt-3 space-y-1.5">
                {column.items.map((item) => (
                  <li key={item} className="text-sm text-zinc-700 dark:text-zinc-300">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------------- cta */}
      <section className="border-t border-zinc-200 dark:border-zinc-800">
        <div className="mx-auto flex max-w-6xl flex-col items-start gap-6 px-6 py-16 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Ready to look around?</h2>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              Create an account and start with your profile — it drives everything else.
            </p>
          </div>
          <Link
            href="/signup"
            className="rounded-lg bg-zinc-900 px-6 py-3 text-sm font-medium text-white transition hover:bg-zinc-800 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            Get started
          </Link>
        </div>
      </section>

      <footer className="border-t border-zinc-200 dark:border-zinc-800">
        <div className="mx-auto max-w-6xl px-6 py-8 text-xs text-zinc-500">
          CareerLens — a portfolio project. Every figure above was measured on this
          machine; the raw output is committed in <code>pipeline/data/</code>.
        </div>
      </footer>
    </div>
  );
}
