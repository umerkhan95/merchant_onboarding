"use client";

import { useState } from "react";
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
  const [hovered, setHovered] = useState<number | null>(null);

  if (data.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
        No status data yet
      </p>
    );
  }

  const total = data.reduce((sum, d) => sum + d.count, 0);

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
      <div className="relative group cursor-pointer">
        <div
          className="h-40 w-40 rounded-full transition-transform duration-300 hover:scale-105"
          style={{ background: `conic-gradient(${gradient})` }}
        />
        <div className="absolute inset-0 m-auto h-20 w-20 rounded-full bg-[hsl(var(--card))] transition-all duration-300" />
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold text-[hsl(var(--foreground))]">
            {hovered !== null ? segments[hovered].count : total}
          </span>
          <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
            {hovered !== null ? segments[hovered].name : "total"}
          </span>
        </div>
      </div>

      <div className="flex flex-wrap justify-center gap-x-4 gap-y-1.5">
        {segments.map((s, i) => (
          <div
            key={s.name}
            className="flex items-center gap-1.5 text-xs cursor-pointer rounded-md px-2 py-1 transition-colors duration-150 hover:bg-[hsl(var(--muted))]"
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
          >
            <span
              className="inline-block h-2.5 w-2.5 rounded-full transition-transform duration-150"
              style={{
                backgroundColor: s.color,
                transform: hovered === i ? "scale(1.4)" : "scale(1)",
              }}
            />
            <span
              className={`transition-colors duration-150 ${
                hovered === i
                  ? "text-[hsl(var(--foreground))] font-medium"
                  : "text-[hsl(var(--muted-foreground))]"
              }`}
            >
              {s.name} ({s.count})
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
