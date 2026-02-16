"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";
import type { AnalyticsSummary, PerfStats, CrawlerStats } from "@/lib/types";
import { StatCards } from "@/components/analytics/stat-cards";
import { TierDonut } from "@/components/analytics/tier-donut";
import { PlatformBar } from "@/components/analytics/platform-bar";
import { StatusPie } from "@/components/analytics/status-pie";
import { PerfDashboard } from "@/components/analytics/perf-dashboard";
import { CrawlerPerf } from "@/components/analytics/crawler-perf";

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [perfData, setPerfData] = useState<PerfStats | null>(null);
  const [crawlerData, setCrawlerData] = useState<CrawlerStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(() => {
    apiFetch<AnalyticsSummary>("/api/v1/analytics")
      .then(setData)
      .catch((err) => setError(String(err)));
    apiFetch<PerfStats>("/api/v1/performance")
      .then(setPerfData)
      .catch(() => {});
    apiFetch<CrawlerStats>("/api/v1/crawler-stats")
      .then(setCrawlerData)
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  if (error) {
    return (
      <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
        {error}
      </div>
    );
  }

  if (!data) {
    return (
      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        Loading analytics...
      </p>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">
          Analytics
        </h2>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Aggregated metrics across all onboarding jobs
        </p>
      </div>

      <StatCards data={data} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <h3 className="mb-2 text-sm font-medium text-[hsl(var(--muted-foreground))]">
            Extraction Tier Distribution
          </h3>
          <TierDonut data={data.jobs_by_tier} />
        </div>

        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <h3 className="mb-2 text-sm font-medium text-[hsl(var(--muted-foreground))]">
            Platform Breakdown
          </h3>
          <PlatformBar data={data.jobs_by_platform} />
        </div>

        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <h3 className="mb-2 text-sm font-medium text-[hsl(var(--muted-foreground))]">
            Job Status Distribution
          </h3>
          <StatusPie data={data.jobs_by_status} />
        </div>
      </div>

      <CrawlerPerf data={crawlerData} />

      <PerfDashboard data={perfData} />
    </div>
  );
}
