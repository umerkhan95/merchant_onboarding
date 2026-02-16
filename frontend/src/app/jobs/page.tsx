"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { JobListResponse } from "@/lib/types";
import { JobsTable } from "@/components/jobs/jobs-table";

export default function JobsPage() {
  const [data, setData] = useState<JobListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const fetchJobs = useCallback(async () => {
    try {
      const params = filter ? `?status=${filter}` : "";
      const res = await apiFetch<JobListResponse>(`/api/v1/jobs${params}`);
      setData(res);
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }, [filter]);

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 10_000);
    return () => clearInterval(interval);
  }, [fetchJobs]);

  const statuses = [
    "",
    "queued",
    "detecting",
    "discovering",
    "extracting",
    "normalizing",
    "ingesting",
    "completed",
    "failed",
    "needs_review",
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">
            Jobs
          </h2>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            {data ? `${data.total} jobs` : "Loading..."}
          </p>
        </div>

        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))]"
        >
          {statuses.map((s) => (
            <option key={s} value={s}>
              {s || "All statuses"}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}

      {data && <JobsTable jobs={data.jobs} />}
    </div>
  );
}
