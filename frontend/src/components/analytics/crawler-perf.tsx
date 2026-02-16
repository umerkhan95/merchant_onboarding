"use client";

import { useState, useEffect } from "react";
import type { CrawlerStats } from "@/lib/types";
import { TIER_LABELS, PLATFORM_COLORS } from "@/lib/constants";

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

function getThroughputColor(pps: number): string {
  if (pps >= 50) return "text-green-600 dark:text-green-400";
  if (pps >= 10) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

function getThroughputBg(pps: number): string {
  if (pps >= 50) return "#10B981";
  if (pps >= 10) return "#F59E0B";
  return "#EF4444";
}

export function CrawlerPerf({ data }: { data: CrawlerStats | null }) {
  const [animated, setAnimated] = useState(false);
  const [hoveredTier, setHoveredTier] = useState<number | null>(null);
  const [hoveredRow, setHoveredRow] = useState<number | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setAnimated(true), 150);
    return () => clearTimeout(t);
  }, []);

  if (!data || (data.by_tier.length === 0 && data.recent_crawls.length === 0)) {
    return (
      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-8 text-center">
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          No crawler performance data available
        </p>
      </div>
    );
  }

  const maxPps = Math.max(...data.by_tier.map((t) => t.products_per_second), 1);

  const summaryCards = [
    {
      label: "Avg Throughput",
      value: `${data.avg_products_per_second.toFixed(1)}/s`,
      accent: "from-emerald-500 to-teal-600",
      colorClass: getThroughputColor(data.avg_products_per_second),
    },
    {
      label: "Total Crawl Time",
      value: formatDuration(data.total_crawl_time_seconds),
      accent: "from-blue-500 to-indigo-600",
      colorClass: "text-[hsl(var(--foreground))]",
    },
    {
      label: "Active Tiers",
      value: String(data.by_tier.length),
      accent: "from-purple-500 to-violet-600",
      colorClass: "text-[hsl(var(--foreground))]",
    },
    {
      label: "Recent Crawls",
      value: String(data.recent_crawls.length),
      accent: "from-orange-500 to-amber-600",
      colorClass: "text-[hsl(var(--foreground))]",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[hsl(var(--foreground))]">
          Crawler Performance
        </h2>
        <span className="text-xs text-[hsl(var(--muted-foreground))]">
          Total crawl time: {formatDuration(data.total_crawl_time_seconds)}
        </span>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {summaryCards.map((card) => (
          <div
            key={card.label}
            className="group relative overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4 transition-all duration-200 hover:shadow-lg hover:shadow-black/5 hover:-translate-y-0.5"
          >
            <div
              className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${card.accent} opacity-0 transition-opacity duration-200 group-hover:opacity-100`}
            />
            <p className="text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
              {card.label}
            </p>
            <p className={`mt-1 text-2xl font-bold ${card.colorClass}`}>
              {card.value}
            </p>
          </div>
        ))}
      </div>

      {/* Tier throughput bars */}
      {data.by_tier.length > 0 && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
          <h3 className="mb-4 text-sm font-semibold text-[hsl(var(--foreground))]">
            Throughput by Extraction Tier
          </h3>
          <div className="flex flex-col gap-4">
            {data.by_tier.map((t, i) => {
              const pct = (t.products_per_second / maxPps) * 100;
              const label = TIER_LABELS[t.tier] || t.tier;
              const isHovered = hoveredTier === i;

              return (
                <div
                  key={t.tier}
                  className="cursor-pointer"
                  onMouseEnter={() => setHoveredTier(i)}
                  onMouseLeave={() => setHoveredTier(null)}
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
                      <span className="ml-2 text-[hsl(var(--muted-foreground))]">
                        ({t.jobs} jobs, avg {formatDuration(t.avg_duration_seconds)})
                      </span>
                    </span>
                    <span
                      className={`font-bold transition-all duration-150 ${getThroughputColor(
                        t.products_per_second
                      )} ${isHovered ? "scale-110" : ""}`}
                    >
                      {t.products_per_second.toFixed(1)} products/s
                    </span>
                  </div>
                  <div className="relative h-6 w-full overflow-hidden rounded-md bg-[hsl(var(--muted))]">
                    <div
                      className="h-full rounded-md transition-all duration-700 ease-out"
                      style={{
                        width: animated ? `${pct}%` : "0%",
                        backgroundColor: getThroughputBg(t.products_per_second),
                        opacity: hoveredTier !== null && !isHovered ? 0.35 : 1,
                        transitionDelay: `${i * 120}ms`,
                      }}
                    />
                    {isHovered && (
                      <div className="absolute inset-0 flex items-center justify-end pr-2">
                        <span className="text-[10px] font-bold text-white drop-shadow-sm">
                          avg {t.avg_products.toFixed(0)} products
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Recent crawls table */}
      {data.recent_crawls.length > 0 && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
          <div className="border-b border-[hsl(var(--border))] px-5 py-3">
            <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">
              Recent Crawls
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-[hsl(var(--border))]">
                <tr className="text-left">
                  <th className="px-5 py-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                    Shop
                  </th>
                  <th className="px-5 py-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                    Platform
                  </th>
                  <th className="px-5 py-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                    Tier
                  </th>
                  <th className="px-5 py-3 text-right text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                    Products
                  </th>
                  <th className="px-5 py-3 text-right text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                    Duration
                  </th>
                  <th className="px-5 py-3 text-right text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                    Throughput
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.recent_crawls.map((crawl, index) => {
                  const domain = (() => {
                    try {
                      return new URL(crawl.shop_url).hostname.replace("www.", "");
                    } catch {
                      return crawl.shop_url;
                    }
                  })();
                  const platformColor = PLATFORM_COLORS[crawl.platform] || "#6B7280";
                  const tierLabel = TIER_LABELS[crawl.tier] || crawl.tier;
                  const isRowHovered = hoveredRow === index;

                  return (
                    <tr
                      key={crawl.job_id}
                      className={`transition-colors duration-150 ${
                        isRowHovered
                          ? "bg-[hsl(var(--muted))]"
                          : ""
                      } ${
                        index < data.recent_crawls.length - 1
                          ? "border-b border-[hsl(var(--border))]"
                          : ""
                      }`}
                      onMouseEnter={() => setHoveredRow(index)}
                      onMouseLeave={() => setHoveredRow(null)}
                    >
                      <td className="px-5 py-3 text-sm font-medium text-[hsl(var(--foreground))]">
                        {domain}
                      </td>
                      <td className="px-5 py-3">
                        <span
                          className="inline-flex rounded-md px-2 py-1 text-xs font-medium transition-transform duration-150"
                          style={{
                            backgroundColor: `${platformColor}20`,
                            color: platformColor,
                            transform: isRowHovered ? "scale(1.05)" : "scale(1)",
                          }}
                        >
                          {crawl.platform}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-sm text-[hsl(var(--muted-foreground))]">
                        {tierLabel}
                      </td>
                      <td className="px-5 py-3 text-right text-sm font-medium text-[hsl(var(--foreground))]">
                        {crawl.products.toLocaleString()}
                      </td>
                      <td className="px-5 py-3 text-right text-sm text-[hsl(var(--muted-foreground))]">
                        {formatDuration(crawl.duration_seconds)}
                      </td>
                      <td
                        className={`px-5 py-3 text-right text-sm font-bold ${getThroughputColor(
                          crawl.products_per_second
                        )}`}
                      >
                        {crawl.products_per_second.toFixed(1)}/s
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
