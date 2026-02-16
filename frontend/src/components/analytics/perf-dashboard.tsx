"use client";

import { useState, useEffect } from "react";
import type { PerfStats } from "@/lib/types";

interface PerfDashboardProps {
  data: PerfStats | null;
}

function formatUptime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function getRequestsColor(rpm: number): string {
  if (rpm < 50) return "text-green-600 dark:text-green-400";
  if (rpm < 100) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

function getLatencyColor(ms: number): string {
  if (ms < 100) return "text-green-600 dark:text-green-400";
  if (ms < 500) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

function getErrorRateColor(rate: number): string {
  if (rate < 1) return "text-green-600 dark:text-green-400";
  if (rate < 5) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

function getMethodColor(method: string): string {
  const colors: Record<string, string> = {
    GET: "bg-blue-500/10 text-blue-700 dark:text-blue-400",
    POST: "bg-green-500/10 text-green-700 dark:text-green-400",
    PUT: "bg-yellow-500/10 text-yellow-700 dark:text-yellow-400",
    DELETE: "bg-red-500/10 text-red-700 dark:text-red-400",
  };
  return colors[method] || "bg-[hsl(var(--muted))] text-[hsl(var(--foreground))]";
}

export function PerfDashboard({ data }: PerfDashboardProps) {
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());
  const [timeAgo, setTimeAgo] = useState<string>("0s");
  const [hoveredRow, setHoveredRow] = useState<number | null>(null);

  useEffect(() => {
    if (data) {
      setLastUpdate(new Date());
    }
  }, [data]);

  useEffect(() => {
    const interval = setInterval(() => {
      const seconds = Math.floor((Date.now() - lastUpdate.getTime()) / 1000);
      setTimeAgo(`${seconds}s`);
    }, 1000);

    return () => clearInterval(interval);
  }, [lastUpdate]);

  if (!data) {
    return (
      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-8 text-center">
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          No performance data available
        </p>
      </div>
    );
  }

  const sortedEndpoints = [...data.endpoints].sort((a, b) => b.count - a.count);

  const statCards = [
    {
      label: "Requests/min",
      value: data.requests_per_minute.toFixed(1),
      color: getRequestsColor(data.requests_per_minute),
      accent: "from-cyan-500 to-blue-600",
    },
    {
      label: "p95 Latency",
      value: `${data.p95_ms.toFixed(1)}ms`,
      color: getLatencyColor(data.p95_ms),
      accent: "from-amber-500 to-orange-600",
    },
    {
      label: "Error Rate",
      value: `${data.error_rate.toFixed(1)}%`,
      color: getErrorRateColor(data.error_rate),
      accent: "from-rose-500 to-red-600",
    },
    {
      label: "Uptime",
      value: formatUptime(data.uptime_seconds),
      color: "text-[hsl(var(--foreground))]",
      accent: "from-green-500 to-emerald-600",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[hsl(var(--foreground))]">
          API Performance
        </h2>
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-green-500" />
          </span>
          <span className="text-xs text-[hsl(var(--muted-foreground))]">
            Updated {timeAgo} ago
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {statCards.map((card) => (
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
            <p className={`mt-1 text-2xl font-bold ${card.color}`}>
              {card.value}
            </p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-hidden">
        <div className="border-b border-[hsl(var(--border))] px-5 py-3">
          <h3 className="text-sm font-semibold text-[hsl(var(--foreground))]">
            Endpoint Performance
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-[hsl(var(--border))]">
              <tr className="text-left">
                <th className="px-5 py-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                  Method
                </th>
                <th className="px-5 py-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                  Endpoint
                </th>
                <th className="px-5 py-3 text-right text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                  Requests
                </th>
                <th className="px-5 py-3 text-right text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                  Avg (ms)
                </th>
                <th className="px-5 py-3 text-right text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
                  p95 (ms)
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedEndpoints.map((endpoint, index) => {
                const isRowHovered = hoveredRow === index;
                return (
                  <tr
                    key={`${endpoint.method}-${endpoint.endpoint}`}
                    className={`transition-colors duration-150 ${
                      isRowHovered ? "bg-[hsl(var(--muted))]" : ""
                    } ${
                      index < sortedEndpoints.length - 1
                        ? "border-b border-[hsl(var(--border))]"
                        : ""
                    }`}
                    onMouseEnter={() => setHoveredRow(index)}
                    onMouseLeave={() => setHoveredRow(null)}
                  >
                    <td className="px-5 py-3">
                      <span
                        className={`inline-flex rounded-md px-2 py-1 text-xs font-medium transition-transform duration-150 ${getMethodColor(
                          endpoint.method
                        )}`}
                        style={{
                          transform: isRowHovered ? "scale(1.05)" : "scale(1)",
                        }}
                      >
                        {endpoint.method}
                      </span>
                    </td>
                    <td className="px-5 py-3 font-mono text-sm text-[hsl(var(--foreground))]">
                      {endpoint.endpoint}
                    </td>
                    <td className="px-5 py-3 text-right text-sm font-medium text-[hsl(var(--foreground))]">
                      {endpoint.count.toLocaleString()}
                    </td>
                    <td
                      className={`px-5 py-3 text-right text-sm font-medium ${getLatencyColor(
                        endpoint.avg_ms
                      )}`}
                    >
                      {endpoint.avg_ms.toFixed(1)}
                    </td>
                    <td
                      className={`px-5 py-3 text-right text-sm font-bold ${getLatencyColor(
                        endpoint.p95_ms
                      )}`}
                    >
                      {endpoint.p95_ms.toFixed(1)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {sortedEndpoints.length === 0 && (
          <div className="px-4 py-8 text-center">
            <p className="text-sm text-[hsl(var(--muted-foreground))]">
              No endpoint data available
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
