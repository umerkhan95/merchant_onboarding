"use client";

import type { StatusCount } from "@/lib/types";
import { CHART_COLORS } from "@/lib/constants";

const STATUS_CHART_COLORS: Record<string, string> = {
  completed: "#10B981",
  extracting: "#3B82F6",
  discovering: "#F59E0B",
  failed: "#EF4444",
  queued: "#6B7280",
  detecting: "#8B5CF6",
  normalizing: "#EC4899",
  ingesting: "#06B6D4",
  needs_review: "#F97316",
};

export function StatusPie({ data }: { data: StatusCount[] }) {
  if (data.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
        No status data yet
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
      name: d.status.replace("_", " "),
      color:
        STATUS_CHART_COLORS[d.status] ||
        CHART_COLORS[idx % CHART_COLORS.length],
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
      {/* Pie */}
      <div className="relative">
        <div
          className="h-40 w-40 rounded-full"
          style={{ background: `conic-gradient(${gradient})` }}
        />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-bold text-white drop-shadow-md">
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
              {s.name} ({s.count})
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
