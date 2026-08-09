"use client";

import { useId, useState } from "react";

/**
 * Small chart set built as inline SVG — no charting library, so nothing here is a black
 * box you can't explain.
 *
 * Design rules applied (they're deliberate, not decoration):
 *  - ONE hue for every chart, because each shows a single series. Multiple colors would
 *    imply multiple categories that don't exist. A single series also needs no legend —
 *    the title names it.
 *  - Rounded corners on the DATA end only; the baseline end stays square so bars read as
 *    anchored to zero rather than floating.
 *  - Recessive grid and axes (hairline, muted) so the data is the most prominent ink.
 *  - Direct labels only where they add information, never one on every mark.
 *  - Every chart ships a "Table" toggle — the accessible fallback, and genuinely useful
 *    when someone wants the exact number instead of a length.
 *  - Colors come from CSS custom properties defined per mode, so light/dark swap in one
 *    place instead of being hardcoded per element.
 */

export function ChartFrame({
  title,
  subtitle,
  note,
  children,
  rows,
  columns,
}: {
  title: string;
  subtitle?: string;
  /** A caveat about what the chart shows, printed UNDER the plot in muted text.
   *
   *  Separate from `subtitle` deliberately: a subtitle says what the chart IS and belongs
   *  above it; a note says what NOT to conclude from it and only makes sense once the
   *  reader has looked. Hidden in table view, where the numbers speak for themselves. */
  note?: string;
  children: React.ReactNode;
  rows?: (string | number | null)[][];
  columns?: string[];
}) {
  const [showTable, setShowTable] = useState(false);

  return (
    <section className="viz-root rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-card)] p-5">
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-[var(--text-primary)]">{title}</h3>
          {subtitle && <p className="mt-1 text-sm text-[var(--text-muted)]">{subtitle}</p>}
        </div>
        {rows && columns && (
          <button
            onClick={() => setShowTable((v) => !v)}
            className="shrink-0 rounded border border-[var(--border-strong)] px-2 py-1 text-xs text-[var(--text-secondary)] hover:bg-[var(--surface-page)] dark:hover:bg-zinc-800"
          >
            {showTable ? "Chart" : "Table"}
          </button>
        )}
      </header>

      {showTable && rows && columns ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm tabular-nums">
            <thead>
              <tr className="border-b border-[var(--border-subtle)]">
                {columns.map((c) => (
                  <th key={c} className="py-2 pr-4 font-medium text-[var(--text-muted)]">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b border-[var(--border-subtle)] last:border-0/60">
                  {r.map((cell, j) => (
                    <td key={j} className="py-2 pr-4 text-[var(--text-secondary)]">
                      {cell ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}

      {note && !showTable && (
        <p className="mt-3 border-t border-[var(--border-subtle)] pt-2.5 text-xs leading-relaxed text-[var(--text-muted)]">
          {note}
        </p>
      )}
    </section>
  );
}

/** Horizontal bar: the right form when category labels are words (they stay readable
 *  left-aligned) and the comparison is magnitude across a ranked list. */
export function BarChart({
  data,
  format = (v: number) => v.toLocaleString(),
  height = 22,
}: {
  data: { label: string; value: number }[];
  format?: (v: number) => string;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);

  if (!data.length) {
    return <p className="py-12 text-center text-xs text-[var(--text-muted)]">No data yet.</p>;
  }

  // The `1` floor keeps this safe when every value is 0 — dividing by a zero max would
  // make every bar width NaN.
  const max = Math.max(...data.map((d) => d.value), 1);
  const labelWidth = 108;
  const chartWidth = 460;
  const gap = 8;
  const radius = 4;

  return (
    <div className="relative overflow-x-auto">
      <svg
        viewBox={`0 0 ${labelWidth + chartWidth + 60} ${data.length * (height + gap)}`}
        className="w-full"
        style={{ minWidth: 380 }}
        role="img"
        aria-label="bar chart"
      >
        {data.map((d, i) => {
          const y = i * (height + gap);
          const w = Math.max((d.value / max) * chartWidth, 2);
          // rounded on the data end only, square against the baseline
          const path =
            w > radius
              ? `M${labelWidth},${y} H${labelWidth + w - radius} A${radius},${radius} 0 0 1 ${
                  labelWidth + w
                },${y + radius} V${y + height - radius} A${radius},${radius} 0 0 1 ${
                  labelWidth + w - radius
                },${y + height} H${labelWidth} Z`
              : `M${labelWidth},${y} h${w} v${height} h-${w} Z`;

          return (
            <g
              key={d.label}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              style={{ cursor: "default" }}
            >
              {/* invisible full-width hit target — bigger than the mark, so hovering
                  a short bar doesn't require pixel precision */}
              <rect
                x={0}
                y={y - gap / 2}
                width={labelWidth + chartWidth + 60}
                height={height + gap}
                fill="transparent"
              />
              <text
                x={labelWidth - 8}
                y={y + height / 2}
                textAnchor="end"
                dominantBaseline="central"
                className="fill-zinc-600 dark:fill-zinc-400"
                style={{ fontSize: 12.5 }}
              >
                {d.label}
              </text>
              <path d={path} fill="var(--chart-neutral)" opacity={hover === null || hover === i ? 1 : 0.4} />
              <text
                x={labelWidth + w + 8}
                y={y + height / 2}
                dominantBaseline="central"
                className="fill-zinc-500"
                style={{ fontSize: 12.5, fontVariantNumeric: "tabular-nums" }}
              >
                {format(d.value)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Line chart for change-over-time. Crosshair + tooltip on hover, per the interaction
 *  rules — a static line chart wastes the fact that it's on a screen. */
export function LineChart({
  data,
  format = (v: number) => v.toLocaleString(),
}: {
  data: { label: string; value: number }[];
  format?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const id = useId();

  // Charts render before their fetch resolves, so an empty array is a NORMAL state, not
  // an error — and it must be handled before any scale math runs.
  if (!data.length) {
    return <p className="py-12 text-center text-xs text-[var(--text-muted)]">No data yet.</p>;
  }

  const width = 560;
  const height = 200;
  const padding = { top: 16, right: 16, bottom: 28, left: 48 };
  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  const max = Math.max(...data.map((d) => d.value));
  const min = Math.min(...data.map((d) => d.value));

  // Pad the domain so the line never touches the frame edges.
  //
  // The `|| 1` guards a real failure: when every value is identical, max - min is 0, the
  // domain collapses to zero width, and every y coordinate becomes NaN — React then warns
  // "Received NaN for the y1 attribute" and the chart renders invisibly. The empty-data
  // case is handled by the early return above, which is the other way this used to break
  // (Math.max of an empty array is -Infinity).
  const spread = max - min || Math.abs(max) * 0.2 || 1;
  const domainMax = max + spread * 0.15;
  const domainMin = Math.max(0, min - spread * 0.15);

  const x = (i: number) => padding.left + (i / Math.max(data.length - 1, 1)) * plotW;
  const y = (v: number) =>
    padding.top + plotH - ((v - domainMin) / Math.max(domainMax - domainMin, 1)) * plotH;

  const linePath = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(d.value)}`).join(" ");
  const ticks = [domainMin, (domainMin + domainMax) / 2, domainMax];

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label="line chart"
        onMouseLeave={() => setHover(null)}
      >
        {/* recessive gridlines — present for reading values, never competing with data */}
        {ticks.map((t, i) => (
          <g key={i}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--chart-grid)"
              strokeWidth={1}
            />
            <text
              x={padding.left - 8}
              y={y(t)}
              textAnchor="end"
              dominantBaseline="central"
              className="fill-zinc-400"
              style={{ fontSize: 10, fontVariantNumeric: "tabular-nums" }}
            >
              {format(Math.round(t))}
            </text>
          </g>
        ))}

        <path d={linePath} fill="none" stroke="var(--chart-positive)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {data.map((d, i) => (
          <g key={d.label}>
            <rect
              x={x(i) - plotW / data.length / 2}
              y={padding.top}
              width={plotW / data.length}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
            />
            <text
              x={x(i)}
              y={height - 8}
              textAnchor="middle"
              className="fill-zinc-400"
              style={{ fontSize: 10 }}
            >
              {d.label}
            </text>
            {hover === i && (
              <>
                <line
                  x1={x(i)}
                  x2={x(i)}
                  y1={padding.top}
                  y2={padding.top + plotH}
                  className="stroke-zinc-300 dark:stroke-zinc-700"
                  strokeWidth={1}
                />
                {/* 2px surface ring keeps the marker legible over the line it sits on */}
                <circle cx={x(i)} cy={y(d.value)} r={5} fill="var(--chart-positive)" stroke="var(--surface-card)" strokeWidth={2} />
              </>
            )}
          </g>
        ))}
      </svg>

      {hover !== null && (
        <div
          className="pointer-events-none absolute rounded border border-[var(--border-subtle)] bg-[var(--surface-card)] px-2 py-1 text-xs shadow-sm"
          style={{ left: `${(x(hover) / width) * 100}%`, top: 0, transform: "translateX(-50%)" }}
          key={id}
        >
          <div className="font-medium text-[var(--text-primary)]">{data[hover].label}</div>
          <div className="tabular-nums text-[var(--text-secondary)]">
            {format(data[hover].value)}
          </div>
        </div>
      )}
    </div>
  );
}

/** A single number is often the right "chart" — no axes needed to say "195,959". */
export function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-card)] p-4">
      <div className="text-sm font-medium text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 text-3xl font-semibold text-[var(--text-primary)]">{value}</div>
      {hint && <div className="mt-1 text-xs text-[var(--text-muted)]">{hint}</div>}
    </div>
  );
}

/**
 * DIVERGING BAR — for "above or below a baseline", which a plain bar cannot express.
 *
 * The skill-premium data is a *deviation*: how far each skill's average salary sits from
 * the overall average. Drawn as an ordinary bar, every value looked positive and the
 * reader had to compare bar lengths to infer a sign that the data states outright. The
 * form was answering a different question than the data asked.
 *
 * Diverging is the documented form for polarity: two opposed hues around a NEUTRAL
 * midpoint, bars growing left or right from a zero line. Blue/red, not blue/aqua — two
 * cool hues read as "more/less of the same thing" rather than as opposites, and the
 * midpoint must read as *nothing*, which only a gray does.
 *
 * Palette validated before use, both modes, all six checks passing:
 *   light #2a78d6 ↔ #e34948   CVD ΔE 21.6 · normal ΔE 32.3
 *   dark  #3987e5 ↔ #e66767   CVD ΔE 19.2 · normal ΔE 29.0
 *
 * Sign is never carried by color alone — every bar is direct-labelled with its signed
 * value, and the two sides sit on opposite halves of the axis. Colorblind readers get the
 * side and the label; the hue is reinforcement, not the message.
 */
export function DivergingBar({
  data,
  format = (v: number) => v.toLocaleString(),
  height = 22,
}: {
  data: { label: string; value: number }[];
  format?: (v: number) => string;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);

  if (!data.length) {
    return <p className="py-12 text-center text-xs text-[var(--text-muted)]">No data yet.</p>;
  }

  const labelWidth = 92;
  const plotWidth = 340;
  const half = plotWidth / 2;
  const zeroX = labelWidth + half;
  const gap = 8;
  const radius = 4;

  // Scale on the LARGEST ABSOLUTE value so both arms share one scale. Scaling each side to
  // its own max would make a +$400 bar and a -$400 bar different lengths — the exact
  // comparison the form exists to make.
  const maxAbs = Math.max(...data.map((d) => Math.abs(d.value)), 1);

  return (
    <div className="relative overflow-x-auto">
      <svg
        viewBox={`0 0 ${labelWidth + plotWidth + 72} ${data.length * (height + gap)}`}
        className="w-full"
        style={{ minWidth: 380 }}
        role="img"
        aria-label="diverging bar chart: salary premium versus the overall average"
      >
        {data.map((d, i) => {
          const y = i * (height + gap);
          const w = Math.max((Math.abs(d.value) / maxAbs) * (half - 8), 2);
          const positive = d.value >= 0;
          // 1px clear of the zero line so a bar never sits on top of the baseline.
          const x = positive ? zeroX + 1 : zeroX - 1 - w;

          // Rounded on the DATA end only; the baseline end stays square so bars read as
          // anchored to zero rather than floating.
          const path = positive
            ? `M${x},${y} H${x + w - radius} A${radius},${radius} 0 0 1 ${x + w},${y + radius} V${y + height - radius} A${radius},${radius} 0 0 1 ${x + w - radius},${y + height} H${x} Z`
            : `M${x + w},${y} H${x + radius} A${radius},${radius} 0 0 0 ${x},${y + radius} V${y + height - radius} A${radius},${radius} 0 0 0 ${x + radius},${y + height} H${x + w} Z`;

          return (
            <g
              key={d.label}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              style={{ cursor: "default" }}
            >
              {/* Invisible full-width hit target — hovering a short bar must not require
                  pixel precision. */}
              <rect x={0} y={y - gap / 2} width={labelWidth + plotWidth + 72} height={height + gap} fill="transparent" />

              <text
                x={labelWidth - 10}
                y={y + height / 2}
                textAnchor="end"
                dominantBaseline="central"
                className="fill-zinc-600 dark:fill-zinc-400"
                style={{ fontSize: 12.5 }}
              >
                {d.label}
              </text>

              <path
                d={path}
                className={
                  positive
                    ? "fill-[var(--chart-positive)]"
                    : "fill-[var(--chart-negative)]"
                }
                opacity={hover === null || hover === i ? 1 : 0.45}
              />

              {/* Values live in a FIXED COLUMN on the right, not beside each bar.
                  Placed next to the mark, a long negative bar pushes its label left until
                  it collides with the category name — "Hadoop-$41,031" ran together on
                  screen. A dedicated column cannot collide with anything and makes the
                  numbers scannable down a line, which is what a reader does with them
                  anyway. This is still the secondary encoding that keeps the sign readable
                  without relying on colour. */}
              <text
                x={labelWidth + plotWidth + 66}
                y={y + height / 2}
                textAnchor="end"
                dominantBaseline="central"
                fill="var(--text-secondary)"
                style={{ fontSize: 12, fontVariantNumeric: "tabular-nums" }}
              >
                {d.value >= 0 ? "+" : "−"}
                {format(Math.abs(d.value))}
              </text>
            </g>
          );
        })}

        {/* The zero line, drawn LAST so it sits above the bars. Neutral gray: a hue here
            would read as a third category. */}
        <line
          x1={zeroX}
          x2={zeroX}
          y1={0}
          y2={data.length * (height + gap) - gap}
          className="stroke-zinc-400 dark:stroke-zinc-600"
          strokeWidth={1}
        />
      </svg>

      <p className="mt-2 text-center text-[11px] text-[var(--text-muted)]">
        ← below the overall average · above →
      </p>
    </div>
  );
}

/**
 * LOLLIPOP with a reference line — for few categories compared against a benchmark.
 *
 * Two problems with using a bar here, both real:
 *
 * A bar is a large block, and the viz guidance is explicit that saturated fills belong on
 * small marks and accents rather than large areas — which is exactly why the all-bar
 * dashboard read as heavy. A lollipop carries the same value with a hairline stem and a
 * small dot, so the accent hue can stay saturated and still be comfortable. Same data,
 * a fraction of the ink.
 *
 * More importantly a bare bar answers "how much?" and stops. Adding the overall average as
 * a reference line answers "compared to what?", which is the question anyone actually has
 * — and it turns each row into above-or-below at a glance instead of a length to compare
 * by eye against its neighbours.
 */
export function Lollipop({
  data,
  reference,
  referenceLabel = "average",
  format = (v: number) => v.toLocaleString(),
}: {
  data: { label: string; value: number }[];
  reference?: number;
  referenceLabel?: string;
  format?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);

  if (!data.length) {
    return <p className="py-12 text-center text-xs text-[var(--text-muted)]">No data yet.</p>;
  }

  const labelWidth = 108;
  const plotWidth = 400;
  const rowHeight = 34;
  const dotRadius = 6;

  // Domain starts at zero so stem lengths stay proportional — a truncated axis makes a 5%
  // difference look like 50%, which is the most common way a chart lies.
  const max = Math.max(...data.map((d) => d.value), reference ?? 0) * 1.12;
  const x = (v: number) => labelWidth + (v / Math.max(max, 1)) * plotWidth;

  return (
    <div className="relative overflow-x-auto">
      <svg
        viewBox={`0 0 ${labelWidth + plotWidth + 90} ${data.length * rowHeight + 18}`}
        className="w-full"
        style={{ minWidth: 420 }}
        role="img"
        aria-label="lollipop chart with reference line"
      >
        {reference !== undefined && (
          <g>
            {/* Solid hairline, never dashed — dashing adds noise and reads as "provisional". */}
            <line
              x1={x(reference)}
              x2={x(reference)}
              y1={0}
              y2={data.length * rowHeight}
              stroke="var(--border-strong)"
              strokeWidth={1}
            />
            <text
              x={x(reference)}
              y={data.length * rowHeight + 13}
              textAnchor="middle"
              fill="var(--text-muted)"
              style={{ fontSize: 10.5 }}
            >
              {referenceLabel} {format(reference)}
            </text>
          </g>
        )}

        {data.map((d, i) => {
          const cy = i * rowHeight + rowHeight / 2;
          const cx = x(d.value);
          const above = reference !== undefined && d.value >= reference;
          const active = hover === null || hover === i;

          return (
            <g
              key={d.label}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              style={{ cursor: "default" }}
            >
              <rect x={0} y={cy - rowHeight / 2} width={labelWidth + plotWidth + 90} height={rowHeight} fill="transparent" />

              <text
                x={labelWidth - 10}
                y={cy}
                textAnchor="end"
                dominantBaseline="central"
                fill="var(--text-secondary)"
                style={{ fontSize: 12.5 }}
              >
                {d.label}
              </text>

              {/* The stem is context, not data — recessive, so the dot reads as the value. */}
              <line
                x1={labelWidth}
                x2={cx - dotRadius}
                y1={cy}
                y2={cy}
                stroke="var(--chart-neutral-soft)"
                strokeWidth={1.5}
                opacity={active ? 1 : 0.4}
              />

              {/* 2px surface ring so a dot landing on the reference line stays legible. */}
              <circle
                cx={cx}
                cy={cy}
                r={dotRadius}
                fill={
                  reference === undefined
                    ? "var(--chart-positive)"
                    : above
                    ? "var(--chart-positive)"
                    : "var(--chart-negative)"
                }
                stroke="var(--surface-card)"
                strokeWidth={2}
                opacity={active ? 1 : 0.45}
              />

              <text
                x={cx + dotRadius + 8}
                y={cy}
                dominantBaseline="central"
                fill="var(--text-secondary)"
                style={{ fontSize: 12.5, fontVariantNumeric: "tabular-nums" }}
              >
                {format(d.value)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
