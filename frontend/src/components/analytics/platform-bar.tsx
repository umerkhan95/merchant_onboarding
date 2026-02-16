"use client";

import { useState, useEffect } from "react";
import type { PlatformCount } from "@/lib/types";
import { PLATFORM_COLORS } from "@/lib/constants";

export function PlatformBar({ data }: { data: PlatformCount[] }) {
  const [animated, setAnimated] = useState(false);
  const [hovered, setHovered] = useState<number | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 100);
    return () => clearTimeout(t);
  }, []);

  if (data.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
        No platform data yet
      </p>
    );
  }

  const max = Math.max(...data.map((d) => d.count));
  const total = data.reduce((sum, d) => sum + d.count, 0);

  return (
    <div className="flex flex-col gap-4 pt-2">
      {data.map((d, i) => {
        const pct = max > 0 ? (d.count / max) * 100 : 0;
        const share = total > 0 ? ((d.count / total) * 100).toFixed(1) : "0";
        const color = PLATFORM_COLORS[d.platform] || "#6B7280";
        const label = d.platform.charAt(0).toUpperCase() + d.platform.slice(1);
        const isHovered = hovered === i;

        return (
          <div
            key={d.platform}
            className="group cursor-pointer"
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
          >
            <div className="mb-1.5 flex items-center justify-between text-xs">
              <span
                className={`font-medium transition-colors duration-150 ${
                  isHovered
                    ? "text-[hsl(var(--foreground))]"
                    : "text-[hsl(var(--muted-foreground))]"
                }`}
              >
                {label}
              </span>
              <div className="flex items-center gap-2">
                <span
                  className={`transition-all duration-200 ${
                    isHovered
                      ? "text-[hsl(var(--foreground))] font-semibold"
                      : "text-[hsl(var(--muted-foreground))]"
                  }`}
                >
                  {d.count}
                </span>
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium transition-opacity duration-200 ${
                    isHovered ? "opacity-100" : "opacity-0"
                  }`}
                  style={{
                    backgroundColor: `${color}20`,
                    color: color,
                  }}
                >
                  {share}%
                </span>
              </div>
            </div>
            <div className="relative h-7 w-full overflow-hidden rounded-md bg-[hsl(var(--muted))]">
              <div
                className="h-full rounded-md transition-all duration-700 ease-out"
                style={{
                  width: animated ? `${pct}%` : "0%",
                  backgroundColor: color,
                  opacity: hovered !== null && !isHovered ? 0.4 : 1,
                  transitionDelay: `${i * 100}ms`,
                }}
              />
              {isHovered && (
                <div className="absolute inset-0 flex items-center justify-end pr-2">
                  <span className="text-[10px] font-bold text-white drop-shadow-sm">
                    {d.count} jobs
                  </span>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
