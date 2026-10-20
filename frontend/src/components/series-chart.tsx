import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { num } from "@/lib/format";

export interface Series<T> {
  key: keyof T & string;
  label: string;
  color: string; // css color, e.g. "var(--chart-1)"
  type?: "bar" | "line" | "area";
  axis?: "primary" | "secondary";
  format?: (v: number) => string;
}

/**
 * Time-series chart for RTL: time flows right → left (oldest on the right), the primary axis sits on the right.
 * Colors come from the theme tokens, so it follows dark mode.
 */
export function SeriesChart<T extends object>({
  data,
  x,
  xFormat,
  series,
  height = 260,
}: {
  data: T[];
  x: keyof T & string;
  xFormat?: (v: string) => string;
  series: Series<T>[];
  height?: number;
}) {
  const hasSecondary = series.some((s) => s.axis === "secondary");
  const fmt = (key: string) => series.find((s) => s.key === key)?.format ?? ((v: number) => num(v));
  return (
    <div dir="ltr" style={{ height }} className="w-full text-xs">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 4, left: 4, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
          <XAxis
            dataKey={x}
            reversed
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            minTickGap={24}
            tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
            tickFormatter={(v) => (xFormat ? xFormat(String(v)) : String(v))}
          />
          <YAxis
            yAxisId="primary"
            orientation="right"
            tickLine={false}
            axisLine={false}
            width={52}
            tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
            tickFormatter={(v: number) => fmt(series.find((s) => (s.axis ?? "primary") === "primary")?.key ?? "")(v)}
          />
          {hasSecondary && (
            <YAxis
              yAxisId="secondary"
              orientation="left"
              tickLine={false}
              axisLine={false}
              width={44}
              tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
              tickFormatter={(v: number) => fmt(series.find((s) => s.axis === "secondary")?.key ?? "")(v)}
            />
          )}
          <Tooltip
            cursor={{ fill: "var(--muted)", opacity: 0.5 }}
            content={(p: TooltipProps<number, string>) => (
              <ChartTooltip {...p} series={series} xFormat={xFormat} />
            )}
          />
          {series.map((s) => {
            const common = { key: s.key, dataKey: s.key, name: s.label, yAxisId: s.axis ?? "primary", isAnimationActive: false };
            if (s.type === "line")
              return <Line {...common} type="monotone" stroke={s.color} strokeWidth={2} dot={false} connectNulls />;
            if (s.type === "area")
              return (
                <Area {...common} type="monotone" stroke={s.color} fill={s.color} fillOpacity={0.15} strokeWidth={2} connectNulls />
              );
            return <Bar {...common} fill={s.color} radius={[3, 3, 0, 0]} maxBarSize={18} />;
          })}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function ChartTooltip<T>({
  active,
  payload,
  label,
  series,
  xFormat,
}: TooltipProps<number, string> & { series: Series<T>[]; xFormat?: (v: string) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div dir="rtl" className="min-w-36 rounded-lg border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      <div className="mb-1.5 font-medium">{xFormat ? xFormat(String(label)) : String(label)}</div>
      <div className="grid gap-1">
        {payload.map((p) => {
          const s = series.find((x) => x.key === p.dataKey);
          const v = typeof p.value === "number" ? p.value : null;
          return (
            <div key={String(p.dataKey)} className="flex items-center justify-between gap-4">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <span className="size-2 rounded-[2px]" style={{ background: s?.color }} />
                {s?.label ?? p.name}
              </span>
              <span className="num font-medium">{v === null ? "—" : s?.format ? s.format(v) : num(v, 2)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
