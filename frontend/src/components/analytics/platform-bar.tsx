"use client";

import type { PlatformCount } from "@/lib/types";
import { PLATFORM_COLORS } from "@/lib/constants";

export function PlatformBar({ data }: { data: PlatformCount[] }) {
  if (data.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
        No platform data yet
      </p>
    );
  }

  const max = Math.max(...data.map((d) => d.count));

  return (
    <div className="flex flex-col gap-3 pt-2">
      {data.map((d) => {
        const pct = max > 0 ? (d.count / max) * 100 : 0;
        const color = PLATFORM_COLORS[d.platform] || "#6B7280";
        const label = d.platform.charAt(0).toUpperCase() + d.platform.slice(1);

        return (
          <div key={d.platform} className="group">
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="font-medium text-[hsl(var(--foreground))]">
                {label}
              </span>
              <span className="text-[hsl(var(--muted-foreground))]">
                {d.count}
              </span>
            </div>
            <div className="h-6 w-full overflow-hidden rounded bg-[hsl(var(--muted))]">
              <div
                className="h-full rounded transition-all duration-300"
                style={{ width: `${pct}%`, backgroundColor: color }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
