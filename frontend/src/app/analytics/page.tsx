"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";
import type { AnalyticsSummary, PerfStats, CrawlerStats, MerchantProfile } from "@/lib/types";
import { StatCards } from "@/components/analytics/stat-cards";
import { TierDonut } from "@/components/analytics/tier-donut";
import { PlatformBar } from "@/components/analytics/platform-bar";
import { StatusPie } from "@/components/analytics/status-pie";
import { PerfDashboard } from "@/components/analytics/perf-dashboard";
import { CrawlerPerf } from "@/components/analytics/crawler-perf";
import { StoresOverview } from "@/components/analytics/stores-overview";

function LoadingSkeleton() {
  return (
    <div className="space-y-8 animate-pulse">
      <div>
        <div className="h-8 w-32 rounded-md bg-[hsl(var(--muted))]" />
        <div className="mt-2 h-4 w-64 rounded-md bg-[hsl(var(--muted))]" />
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="h-24 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
          />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        {[...Array(3)].map((_, i) => (
          <div
            key={i}
            className="h-64 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
          />
        ))}
      </div>
    </div>
  );
}

export default function AnalyticsPage() {
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [perfData, setPerfData] = useState<PerfStats | null>(null);
  const [crawlerData, setCrawlerData] = useState<CrawlerStats | null>(null);
  const [storesData, setStoresData] = useState<MerchantProfile[] | null>(null);
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
    apiFetch<MerchantProfile[]>("/api/v1/merchants/profiles")
      .then(setStoresData)
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 dark:border-red-900/50 dark:bg-red-900/20">
        <p className="text-sm font-medium text-red-700 dark:text-red-400">
          {error}
        </p>
      </div>
    );
  }

  if (!data) {
    return <LoadingSkeleton />;
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">
          Analytics
        </h2>
        <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
          Aggregated metrics across all onboarding jobs
        </p>
      </div>

      <StatCards data={data} />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="group rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 transition-shadow duration-200 hover:shadow-lg hover:shadow-black/5">
          <h3 className="mb-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
            Extraction Tier Distribution
          </h3>
          <TierDonut data={data.jobs_by_tier} />
        </div>

        <div className="group rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 transition-shadow duration-200 hover:shadow-lg hover:shadow-black/5">
          <h3 className="mb-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
            Platform Breakdown
          </h3>
          <PlatformBar data={data.jobs_by_platform} />
        </div>

        <div className="group rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 transition-shadow duration-200 hover:shadow-lg hover:shadow-black/5">
          <h3 className="mb-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
            Job Status Distribution
          </h3>
          <StatusPie data={data.jobs_by_status} />
        </div>
      </div>

      <StoresOverview stores={storesData} />

      <CrawlerPerf data={crawlerData} />

      <PerfDashboard data={perfData} />
    </div>
  );
}
