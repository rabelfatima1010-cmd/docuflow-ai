"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type ChartColors = { series: string; grid: string; text: string; border: string; hover: string };
const FALLBACK: ChartColors = { series: "#2a78d6", grid: "#e7e6e1", text: "#52514e", border: "#e2e1dc", hover: "#f0efec" };

/** SVG presentation attributes (fill/stroke) ignore CSS var(), so resolve the theme tokens to real
 *  colors and re-resolve when the light/dark preference changes. */
function useChartColors(): ChartColors {
  const [colors, setColors] = useState<ChartColors>(FALLBACK);
  useEffect(() => {
    const read = () => {
      const s = getComputedStyle(document.documentElement);
      const v = (name: string, fb: string) => s.getPropertyValue(name).trim() || fb;
      setColors({
        series: v("--series-1", FALLBACK.series),
        grid: v("--grid", FALLBACK.grid),
        text: v("--text-2", FALLBACK.text),
        border: v("--border", FALLBACK.border),
        hover: v("--surface-2", FALLBACK.hover),
      });
    };
    read();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", read);
    return () => mq.removeEventListener("change", read);
  }, []);
  return colors;
}

interface Props {
  title: string;
  data: { label: string; value: number }[];
  horizontal?: boolean;
  format: (v: number) => string;
  empty?: string;
}

/** Single-series bar chart: one hue, no legend (the title names the series), hover tooltip, table view. */
export function BarChartCard({ title, data, horizontal = false, format, empty = "No approved documents yet." }: Props) {
  const [table, setTable] = useState(false);
  const c = useChartColors();
  const height = horizontal ? Math.max(160, data.length * 36 + 40) : 260;
  const axisTick = { fill: c.text, fontSize: 12 };

  return (
    <div className="card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold">{title}</h2>
        <button className="text-xs muted hover:underline" onClick={() => setTable((t) => !t)}>
          {table ? "Chart view" : "Table view"}
        </button>
      </div>
      {data.length === 0 ? (
        <div className="py-12 text-center text-sm faint">{empty}</div>
      ) : table ? (
        <table className="w-full text-sm">
          <tbody>
            {data.map((d) => (
              <tr key={d.label} style={{ borderTop: "1px solid var(--border)" }}>
                <td className="py-1.5">{d.label}</td>
                <td className="py-1.5 text-right tabular">{format(d.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <BarChart
            data={data}
            layout={horizontal ? "vertical" : "horizontal"}
            margin={{ top: 4, right: 16, bottom: 4, left: horizontal ? 8 : 0 }}
            barCategoryGap={horizontal ? 8 : "25%"}
          >
            <CartesianGrid stroke={c.grid} vertical={horizontal} horizontal={!horizontal} />
            {/* Recharts only finds axes that are direct children, so no fragments here */}
            {horizontal ? (
              <XAxis type="number" tick={axisTick} tickFormatter={format} axisLine={false} tickLine={false} />
            ) : (
              <XAxis dataKey="label" tick={axisTick} axisLine={{ stroke: c.border }} tickLine={false} />
            )}
            {horizontal ? (
              <YAxis type="category" dataKey="label" tick={axisTick} width={150} axisLine={false} tickLine={false} />
            ) : (
              <YAxis tick={axisTick} tickFormatter={format} axisLine={false} tickLine={false} width={72} />
            )}
            <Tooltip
              cursor={{ fill: c.hover }}
              contentStyle={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                color: "var(--text)",
                fontSize: 13,
              }}
              labelStyle={{ color: "var(--text-2)" }}
              formatter={(v: number) => [format(v), "Spend"]}
            />
            <Bar
              dataKey="value"
              fill={c.series}
              isAnimationActive={false}
              radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]}
              maxBarSize={horizontal ? 22 : 40}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
