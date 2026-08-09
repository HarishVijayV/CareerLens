"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { BarChart, ChartFrame, Histogram, LineChart, Lollipop, StatTile } from "@/components/Charts";
import { api } from "@/lib/api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface Overview {
  total_postings: number;
  total_companies: number;
  avg_salary: number;
  remote_percent: number;
  total_skills: number;
}

export default function AnalyticsPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [topSkills, setTopSkills] = useState<{ skill_name: string; posting_count: number }[]>([]);
  const [bySeniority, setBySeniority] = useState<{ seniority: string; avg_salary: number }[]>([]);
  const [byRegion, setByRegion] = useState<{ region: string; avg_salary: number }[]>([]);
  const [distribution, setDistribution] = useState<{ bucket_start: number; postings: number }[]>([]);
  const [byMonth, setByMonth] = useState<{ posted_month: number; postings: number }[]>([]);
  const [premium, setPremium] = useState<
    { skill_name: string; avg_salary: number; premium_vs_average: number }[]
  >([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.analytics<Overview>("overview").then(setOverview),
      api.analytics<typeof topSkills>("top-skills").then(setTopSkills),
      api.analytics<typeof bySeniority>("salary-by-seniority").then(setBySeniority),
      api.analytics<typeof byRegion>("salary-by-region").then(setByRegion),
      api.analytics<typeof byMonth>("postings-by-month").then(setByMonth),
      api.analytics<typeof distribution>("salary-distribution").then(setDistribution),
    ]).catch((e) => setError(e.message));
  }, []);

  const money = (v: number) => `$${Math.round(v).toLocaleString()}`;

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Job Market Analytics</h1>
        <p className="mt-1 text-base text-[var(--text-muted)]">
          Every number here is computed by the data pipeline — Spark cleans and aggregates,
          dbt models it into a star schema, and these charts read the result.
        </p>

        {/* Provenance, stated explicitly. "Is this AI?" is the first thing anyone asks of
            a dashboard in an AI-branded product, and leaving it ambiguous invites the
            assumption that the numbers were generated rather than computed. */}
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <span className="rounded-full border border-[var(--border-strong)] px-2.5 py-1 text-[var(--text-secondary)]">
            <strong>SQL</strong> — these charts: plain aggregations over the warehouse
          </span>
          <span className="rounded-full border border-[var(--border-strong)] px-2.5 py-1 text-[var(--text-secondary)]">
            <strong>ML</strong> — pay bands on the Jobs page: Spark MLlib, batch-scored
          </span>
          <span className="rounded-full border border-[var(--border-strong)] px-2.5 py-1 text-[var(--text-secondary)]">
            <strong>LLM</strong> — only the Assistant &amp; Resume assistant
          </span>
        </div>
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          No number on this page was produced by a language model — they are SQL results,
          which is why they are reproducible and identical on every refresh.
        </p>
      </div>

      {error && (
        <div className="mb-6 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error} — has the pipeline been run? See docs/SETUP_CHECKLIST.md.
        </div>
      )}

      {overview && (
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5">
          <StatTile label="Job postings" value={overview.total_postings.toLocaleString()} />
          <StatTile label="Companies" value={overview.total_companies.toLocaleString()} />
          <StatTile label="Average salary" value={money(overview.avg_salary)} />
          <StatTile label="Remote" value={`${overview.remote_percent}%`} hint="of all postings" />
          <StatTile label="Skills tracked" value={String(overview.total_skills)} />
        </div>
      )}

      {/* items-start so each card is its own height. Without it a grid row stretches
          every card to match its tallest sibling, so a 3-row lollipop sat in a card sized
          for a 12-bar chart with a block of empty space underneath. */}
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <ChartFrame
          title="Most in-demand skills"
          subtitle="Number of postings requiring each skill"
          columns={["Skill", "Postings"]}
          rows={topSkills.map((s) => [s.skill_name, s.posting_count.toLocaleString()])}
        >
          <BarChart
            data={topSkills.slice(0, 12).map((s) => ({ label: s.skill_name, value: s.posting_count }))}
          />
        </ChartFrame>

        <ChartFrame
          title="Salary distribution"
          subtitle="How many postings fall in each salary band"
          columns={["Band", "Postings"]}
          rows={distribution.map((d) => [
            `${money(d.bucket_start)}–${money(d.bucket_start + 25000)}`,
            d.postings.toLocaleString(),
          ])}
        >
          {/* A histogram, because the average hides the actual shape. The mean is
              $108,640 and describes almost nobody — there are two populations here, an
              Indian cluster under $25k and a US cluster around $100-125k. */}
          <Histogram
            data={distribution.map((d) => ({ bucket: d.bucket_start, count: d.postings }))}
            formatBucket={(v) => `$${Math.round(v / 1000)}k`}
          />
        </ChartFrame>

        {/* The skill-premium chart was removed, not hidden.
            It reported PostgreSQL at -$50,899 from 19 postings and Docker at -$25,363 from
            23 — differences that large from samples that small are noise, and a chart
            nobody can defend costs more credibility than the insight was worth. Skills are
            only extracted from postings whose description survived Adzuna's truncation
            (~20% of them), so the per-skill samples are a fraction of the 5,397 and skew
            toward whichever listings happened to be verbose.
            The endpoint and the DivergingBar component both remain — bring it back with a
            HAVING floor around 100 postings, where only Python, SQL, Spark, AWS, Java,
            Azure, GCP and Scala survive and every number is supportable. */}


        <ChartFrame
          title="Salary by seniority"
          columns={["Seniority", "Avg salary"]}
          rows={bySeniority.map((s) => [s.seniority, money(s.avg_salary)])}
        >
          {/* Lollipop, not a bar: three categories do not need three large blocks, and the
              reference line answers "compared to what?" — which is the actual question. */}
          <Lollipop
            data={bySeniority.map((s) => ({ label: s.seniority, value: s.avg_salary }))}
            reference={overview?.avg_salary}
            referenceLabel="overall avg"
            format={money}
          />
        </ChartFrame>

        <ChartFrame
          title="Salary by region"
          columns={["Region", "Avg salary"]}
          rows={byRegion.map((r) => [r.region, money(r.avg_salary)])}
        >
          <Lollipop
            data={byRegion.map((r) => ({ label: r.region, value: r.avg_salary }))}
            reference={overview?.avg_salary}
            referenceLabel="overall avg"
            format={money}
          />
        </ChartFrame>

        <ChartFrame
          title="Hiring seasonality"
          subtitle="Postings per month — hiring dips sharply in December"
          columns={["Month", "Postings"]}
          rows={byMonth.map((m) => [MONTHS[m.posted_month - 1], m.postings.toLocaleString()])}
        >
          <LineChart
            data={byMonth.map((m) => ({
              label: MONTHS[m.posted_month - 1],
              value: m.postings,
            }))}
          />
        </ChartFrame>
      </div>
    </AppShell>
  );
}
