"use client";

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

export function CrawlerPerf({ data }: { data: CrawlerStats | null }) {
  if (!data || (data.by_tier.length === 0 && data.recent_crawls.length === 0)) {
    return (
      <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-8 text-center">
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          No crawler performance data available
        </p>
      </div>
    );
  }

  const maxPps = Math.max(...data.by_tier.map((t) => t.products_per_second), 1);

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
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
            Avg Throughput
          </p>
          <p className={`mt-1 text-2xl font-bold ${getThroughputColor(data.avg_products_per_second)}`}>
            {data.avg_products_per_second.toFixed(1)}/s
          </p>
        </div>
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
            Total Crawl Time
          </p>
          <p className="mt-1 text-2xl font-bold text-[hsl(var(--foreground))]">
            {formatDuration(data.total_crawl_time_seconds)}
          </p>
        </div>
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
            Active Tiers
          </p>
          <p className="mt-1 text-2xl font-bold text-[hsl(var(--foreground))]">
            {data.by_tier.length}
          </p>
        </div>
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
            Recent Crawls
          </p>
          <p className="mt-1 text-2xl font-bold text-[hsl(var(--foreground))]">
            {data.recent_crawls.length}
          </p>
        </div>
      </div>

      {/* Tier throughput bars */}
      {data.by_tier.length > 0 && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <h3 className="mb-4 text-sm font-semibold text-[hsl(var(--foreground))]">
            Throughput by Extraction Tier
          </h3>
          <div className="flex flex-col gap-3">
            {data.by_tier.map((t) => {
              const pct = (t.products_per_second / maxPps) * 100;
              const label = TIER_LABELS[t.tier] || t.tier;
              return (
                <div key={t.tier}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="font-medium text-[hsl(var(--foreground))]">
                      {label}
                      <span className="ml-2 text-[hsl(var(--muted-foreground))]">
                        ({t.jobs} jobs, avg {formatDuration(t.avg_duration_seconds)})
                      </span>
                    </span>
                    <span className={`font-bold ${getThroughputColor(t.products_per_second)}`}>
                      {t.products_per_second.toFixed(1)} products/s
                    </span>
                  </div>
                  <div className="h-5 w-full overflow-hidden rounded bg-[hsl(var(--muted))]">
                    <div
                      className="h-full rounded transition-all duration-300"
                      style={{
                        width: `${pct}%`,
                        backgroundColor:
                          t.products_per_second >= 50
                            ? "#10B981"
                            : t.products_per_second >= 10
                              ? "#F59E0B"
                              : "#EF4444",
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Recent crawls table */}
      {data.recent_crawls.length > 0 && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
          <div className="border-b border-[hsl(var(--border))] px-4 py-3">
            <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">
              Recent Crawls
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-[hsl(var(--border))]">
                <tr className="text-left">
                  <th className="px-4 py-3 text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Shop
                  </th>
                  <th className="px-4 py-3 text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Platform
                  </th>
                  <th className="px-4 py-3 text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Tier
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Products
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-[hsl(var(--muted-foreground))]">
                    Duration
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-[hsl(var(--muted-foreground))]">
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

                  return (
                    <tr
                      key={crawl.job_id}
                      className={
                        index < data.recent_crawls.length - 1
                          ? "border-b border-[hsl(var(--border))]"
                          : ""
                      }
                    >
                      <td className="px-4 py-3 text-sm text-[hsl(var(--foreground))]">
                        {domain}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className="inline-flex rounded-md px-2 py-1 text-xs font-medium"
                          style={{
                            backgroundColor: `${platformColor}20`,
                            color: platformColor,
                          }}
                        >
                          {crawl.platform}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-[hsl(var(--muted-foreground))]">
                        {tierLabel}
                      </td>
                      <td className="px-4 py-3 text-right text-sm text-[hsl(var(--foreground))]">
                        {crawl.products.toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right text-sm text-[hsl(var(--muted-foreground))]">
                        {formatDuration(crawl.duration_seconds)}
                      </td>
                      <td
                        className={`px-4 py-3 text-right text-sm font-medium ${getThroughputColor(
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
