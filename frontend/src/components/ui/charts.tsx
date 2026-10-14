import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface Series { key: string; label: string; color: string }

/** Courbe temps réel sobre : pas de légende encombrante, infobulle au survol. */
export function TimeChart({ data, series, height = 120, max, format }: {
  data: Record<string, number>[]; series: Series[]; height?: number; max?: number; format?: (v: number) => string;
}) {
  const fmt = format ?? ((v: number) => `${v.toFixed(1)}`);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <defs>
          {series.map((s) => (
            <linearGradient key={s.key} id={`g-${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity={0.28} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
        <XAxis dataKey="t" hide />
        <YAxis width={34} domain={[0, max ?? "auto"]} tick={{ fontSize: 10, fill: "var(--faint)" }} axisLine={false} tickLine={false} tickFormatter={(v) => fmt(v)} />
        <Tooltip
          cursor={{ stroke: "var(--faint)", strokeDasharray: "3 3" }}
          contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12, padding: "6px 10px" }}
          labelFormatter={() => ""}
          formatter={(v, name) => [fmt(Number(v)), series.find((s) => s.key === name)?.label ?? String(name)]}
        />
        {series.map((s) => (
          <Area key={s.key} type="monotone" dataKey={s.key} stroke={s.color} strokeWidth={1.75} fill={`url(#g-${s.key})`} isAnimationActive={false} dot={false} />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
