"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import { PIPELINE_STEPS, STATUS_COLORS } from "@/lib/constants";
import type { JobProgress } from "@/lib/types";

interface ProgressDisplayProps {
  progress: JobProgress;
}

export function ProgressDisplay({ progress }: ProgressDisplayProps) {
  const currentIdx = PIPELINE_STEPS.findIndex(
    (s) => s.key === progress.status
  );
  const isFailed = progress.status === "failed";
  const isReview = progress.status === "needs_review";

  return (
    <div className="space-y-6">
      {/* Status badge + platform */}
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "inline-flex rounded-full px-3 py-1 text-xs font-medium",
            STATUS_COLORS[progress.status] || STATUS_COLORS.queued
          )}
        >
          {progress.status.replace("_", " ")}
        </span>
        {progress.platform && (
          <span className="text-sm text-[hsl(var(--muted-foreground))]">
            Platform: <strong>{progress.platform}</strong>
          </span>
        )}
        {progress.extraction_tier && (
          <span className="text-sm text-[hsl(var(--muted-foreground))]">
            Tier: <strong>{progress.extraction_tier}</strong>
          </span>
        )}
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-1">
        {PIPELINE_STEPS.map((step, idx) => {
          const isActive = idx === currentIdx;
          const isComplete = idx < currentIdx && !isFailed && !isReview;
          return (
            <div key={step.key} className="flex flex-1 flex-col items-center gap-1">
              <div
                className={cn(
                  "h-2 w-full rounded-full transition-colors",
                  isComplete
                    ? "bg-[hsl(var(--primary))]"
                    : isActive
                      ? isFailed
                        ? "bg-red-500"
                        : "bg-[hsl(var(--primary))] animate-pulse"
                      : "bg-[hsl(var(--muted))]"
                )}
              />
              <span
                className={cn(
                  "text-[10px]",
                  isActive
                    ? "font-semibold text-[hsl(var(--foreground))]"
                    : "text-[hsl(var(--muted-foreground))]"
                )}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Progress bar */}
      {progress.total > 0 && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-[hsl(var(--muted-foreground))]">
            <span>
              {progress.processed} / {progress.total}
            </span>
            <span>{progress.percentage.toFixed(1)}%</span>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-[hsl(var(--muted))]">
            <div
              className="h-full rounded-full bg-[hsl(var(--primary))] transition-all"
              style={{ width: `${progress.percentage}%` }}
            />
          </div>
        </div>
      )}

      {/* Current step */}
      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        {progress.current_step}
      </p>

      {/* Error message */}
      {progress.error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          {progress.error}
        </div>
      )}

      {/* Products count on completion */}
      {progress.status === "completed" && progress.products_count != null && (
        <div className="rounded-md bg-green-50 p-4 text-center dark:bg-green-900/20">
          <span className="text-2xl font-bold text-green-700 dark:text-green-400">
            {progress.products_count}
          </span>
          <p className="text-sm text-green-600 dark:text-green-500">
            products ingested
          </p>
          {progress.shop_url && progress.products_count > 0 && (
            <Link
              href={`/products?shop_id=${encodeURIComponent(progress.shop_url)}`}
              className="mt-3 inline-block rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 dark:bg-green-700 dark:hover:bg-green-600"
            >
              View Products
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
