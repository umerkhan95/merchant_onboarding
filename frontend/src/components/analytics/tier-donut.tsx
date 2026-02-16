"use client";

import type { TierCount } from "@/lib/types";
import { TIER_LABELS, CHART_COLORS } from "@/lib/constants";

export function TierDonut({ data }: { data: TierCount[] }) {
  if (data.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
        No tier data yet
      </p>
    );
  }

  const total = data.reduce((sum, d) => sum + d.count, 0);

  // Build conic-gradient segments
  let cumulative = 0;
  const segments = data.map((d, idx) => {
    const start = cumulative;
    const pct = (d.count / total) * 100;
    cumulative += pct;
    return {
      name: TIER_LABELS[d.tier] || d.tier,
      color: CHART_COLORS[idx % CHART_COLORS.length],
      pct,
      start,
      end: cumulative,
      count: d.count,
    };
  });

  const gradient = segments
    .map((s) => `${s.color} ${s.start}% ${s.end}%`)
    .join(", ");

  return (
    <div className="flex flex-col items-center gap-4">
      {/* Donut */}
      <div className="relative">
        <div
          className="h-40 w-40 rounded-full"
          style={{ background: `conic-gradient(${gradient})` }}
        />
        <div className="absolute inset-0 m-auto h-20 w-20 rounded-full bg-[hsl(var(--card))]" />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-bold text-[hsl(var(--foreground))]">
            {total}
          </span>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap justify-center gap-x-4 gap-y-1">
        {segments.map((s) => (
          <div key={s.name} className="flex items-center gap-1.5 text-xs">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: s.color }}
            />
            <span className="text-[hsl(var(--muted-foreground))]">
              {s.name}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
