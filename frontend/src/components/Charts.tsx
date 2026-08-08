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
  children,
  rows,
  columns,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  rows?: (string | number | null)[][];
  columns?: string[];
}) {
  const [showTable, setShowTable] = useState(false);

  return (
    <section className="viz-root rounded-lg border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
      <header className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">{title}</h3>
          {subtitle && <p className="mt-1 text-sm text-zinc-500">{subtitle}</p>}
        </div>
        {rows && columns && (
          <button
            onClick={() => setShowTable((v) => !v)}
            className="shrink-0 rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
          >
            {showTable ? "Chart" : "Table"}
          </button>
        )}
      </header>

      {showTable && rows && columns ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm tabular-nums">
            <thead>
              <tr className="border-b border-zinc-200 dark:border-zinc-800">
                {columns.map((c) => (
                  <th key={c} className="py-2 pr-4 font-medium text-zinc-500">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  {r.map((cell, j) => (
                    <td key={j} className="py-2 pr-4 text-zinc-700 dark:text-zinc-300">
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
    return <p className="py-12 text-center text-xs text-zinc-500">No data yet.</p>;
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
              <path d={path} className="fill-[#2a78d6] dark:fill-[#3987e5]" opacity={hover === null || hover === i ? 1 : 0.45} />
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
    return <p className="py-12 text-center text-xs text-zinc-500">No data yet.</p>;
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
              className="stroke-zinc-200 dark:stroke-zinc-800"
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

        <path d={linePath} fill="none" className="stroke-[#2a78d6] dark:stroke-[#3987e5]" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

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
                <circle cx={x(i)} cy={y(d.value)} r={5} className="fill-[#2a78d6] dark:fill-[#3987e5] stroke-white dark:stroke-zinc-900" strokeWidth={2} />
              </>
            )}
          </g>
        ))}
      </svg>

      {hover !== null && (
        <div
          className="pointer-events-none absolute rounded border border-zinc-200 bg-white px-2 py-1 text-xs shadow-sm dark:border-zinc-700 dark:bg-zinc-800"
          style={{ left: `${(x(hover) / width) * 100}%`, top: 0, transform: "translateX(-50%)" }}
          key={id}
        >
          <div className="font-medium text-zinc-900 dark:text-zinc-100">{data[hover].label}</div>
          <div className="tabular-nums text-zinc-600 dark:text-zinc-400">
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
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="text-sm font-medium text-zinc-500">{label}</div>
      <div className="mt-1 text-3xl font-semibold text-zinc-900 dark:text-zinc-50">{value}</div>
      {hint && <div className="mt-1 text-xs text-zinc-400">{hint}</div>}
    </div>
  );
}
