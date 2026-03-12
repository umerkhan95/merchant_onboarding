"use client";

import Link from "next/link";
import type { JobSummary } from "@/lib/types";
import { TIER_LABELS } from "@/lib/constants";
import { formatDuration, timeAgo } from "@/lib/utils";
import { StatusPill } from "./status-pill";

interface JobsTableProps {
  jobs: JobSummary[];
}

function getDuration(job: JobSummary): number | null {
  if (!job.started_at || !job.completed_at) return null;
  return (
    (new Date(job.completed_at).getTime() -
      new Date(job.started_at).getTime()) /
    1000
  );
}

export function JobsTable({ jobs }: JobsTableProps) {
  if (jobs.length === 0) {
    return (
      <div className="rounded-md border border-[hsl(var(--border))] p-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
        No jobs found. Start by onboarding a store.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-[hsl(var(--border))]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]">
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Job ID
            </th>
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Shop URL
            </th>
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Platform
            </th>
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Status
            </th>
            <th className="px-4 py-3 text-right font-medium text-[hsl(var(--muted-foreground))]">
              Products
            </th>
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Duration
            </th>
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Tier
            </th>
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Started
            </th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr
              key={job.job_id}
              className="border-b border-[hsl(var(--border))] last:border-b-0 hover:bg-[hsl(var(--accent))]"
            >
              <td className="px-4 py-3 font-mono text-xs">{job.job_id}</td>
              <td className="max-w-[200px] truncate px-4 py-3">
                {job.shop_url ? (
                  <Link
                    href={`/stores/${encodeURIComponent(job.shop_url)}`}
                    className="text-[hsl(var(--primary))] hover:underline"
                  >
                    {job.shop_url}
                  </Link>
                ) : (
                  "-"
                )}
              </td>
              <td className="px-4 py-3 capitalize">{job.platform || "-"}</td>
              <td className="px-4 py-3">
                <StatusPill status={job.status} />
              </td>
              <td className="px-4 py-3 text-right tabular-nums">
                {job.products_count > 0 && job.shop_url ? (
                  <Link
                    href={`/products?shop_id=${encodeURIComponent(job.shop_url)}`}
                    className="text-[hsl(var(--primary))] hover:underline"
                  >
                    {job.products_count}
                  </Link>
                ) : (
                  job.products_count
                )}
              </td>
              <td className="px-4 py-3 tabular-nums">
                {formatDuration(getDuration(job))}
              </td>
              <td className="px-4 py-3">
                {job.extraction_tier
                  ? TIER_LABELS[job.extraction_tier] || job.extraction_tier
                  : "-"}
              </td>
              <td className="px-4 py-3 text-[hsl(var(--muted-foreground))]">
                {timeAgo(job.started_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
