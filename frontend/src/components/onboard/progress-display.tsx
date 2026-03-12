"use client";

import { useRef } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "motion/react";
import NumberFlow from "@number-flow/react";
import { cn } from "@/lib/utils";
import { STATUS_COLORS, TIER_LABELS } from "@/lib/constants";
import type { JobProgress } from "@/lib/types";
import { PipelineFlow } from "./pipeline-flow";
import { ProductStream } from "./product-stream";
import { ElapsedTimer } from "./elapsed-timer";
import { Confetti } from "./confetti";

interface ProgressDisplayProps {
  progress: JobProgress;
}

export function ProgressDisplay({ progress }: ProgressDisplayProps) {
  const isFailed = progress.status === "failed";
  const isCompleted = progress.status === "completed";
  const isExtracting = progress.status === "extracting";
  const confettiShown = useRef(false);

  const showConfetti = isCompleted && !confettiShown.current;
  if (isCompleted) confettiShown.current = true;

  const audit = progress.extraction_audit;
  const tierLabel =
    progress.extraction_tier && TIER_LABELS[progress.extraction_tier]
      ? TIER_LABELS[progress.extraction_tier]
      : progress.extraction_tier;

  return (
    <div className="space-y-6">
      {showConfetti && <Confetti />}

      {/* Top row: status badge + platform + tier + timer */}
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "inline-flex rounded-full px-3 py-1 text-xs font-medium capitalize",
            STATUS_COLORS[progress.status] || STATUS_COLORS.queued
          )}
        >
          {progress.status.replace("_", " ")}
        </span>
        {progress.platform && (
          <span className="text-sm text-[hsl(var(--muted-foreground))]">
            Platform: <strong className="capitalize">{progress.platform}</strong>
          </span>
        )}
        {tierLabel && (
          <span className="text-sm text-[hsl(var(--muted-foreground))]">
            Tier: <strong>{tierLabel}</strong>
          </span>
        )}
        <div className="ml-auto">
          <ElapsedTimer
            startedAt={progress.started_at}
            completedAt={progress.completed_at}
          />
        </div>
      </div>

      {/* Animated pipeline flow */}
      <PipelineFlow currentStatus={progress.status} isFailed={isFailed} />

      {/* Progress bar with NumberFlow counters */}
      {progress.total > 0 && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs text-[hsl(var(--muted-foreground))]">
            <span className="tabular-nums">
              <NumberFlow value={progress.processed} /> /{" "}
              <NumberFlow value={progress.total} />
            </span>
            <span className="tabular-nums">
              <NumberFlow
                value={Math.round(progress.percentage * 10) / 10}
                format={{ minimumFractionDigits: 1, maximumFractionDigits: 1 }}
              />
              %
            </span>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-[hsl(var(--muted))]">
            <motion.div
              className="h-full rounded-full bg-[hsl(var(--primary))]"
              initial={{ width: 0 }}
              animate={{ width: `${progress.percentage}%` }}
              transition={{ duration: 0.5, ease: "easeOut" }}
            />
          </div>
        </div>
      )}

      {/* Live stats during extraction */}
      {isExtracting && audit && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4"
        >
          <div className="mb-3 text-center">
            <span className="text-3xl font-bold text-[hsl(var(--foreground))]">
              <NumberFlow value={audit.total_products} />
            </span>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              products found
            </p>
          </div>
          <div className="grid grid-cols-4 gap-2 text-center text-xs">
            <div>
              <span className="font-semibold text-green-600 dark:text-green-400">
                <NumberFlow value={audit.urls_success} />
              </span>
              <p className="text-[hsl(var(--muted-foreground))]">success</p>
            </div>
            <div>
              <span className="font-semibold text-yellow-600 dark:text-yellow-400">
                <NumberFlow value={audit.urls_empty} />
              </span>
              <p className="text-[hsl(var(--muted-foreground))]">empty</p>
            </div>
            <div>
              <span className="font-semibold text-red-600 dark:text-red-400">
                <NumberFlow value={audit.urls_error} />
              </span>
              <p className="text-[hsl(var(--muted-foreground))]">errors</p>
            </div>
            <div>
              <span className="font-semibold text-gray-500">
                <NumberFlow value={audit.urls_not_product} />
              </span>
              <p className="text-[hsl(var(--muted-foreground))]">skipped</p>
            </div>
          </div>
        </motion.div>
      )}

      {/* Product stream during extraction */}
      {isExtracting && (
        <div>
          <p className="mb-2 text-xs font-medium text-[hsl(var(--muted-foreground))]">
            Recent products
          </p>
          <ProductStream products={progress.recent_products} />
        </div>
      )}

      {/* Current step */}
      <p className="text-sm text-[hsl(var(--muted-foreground))]">
        {progress.current_step}
      </p>

      {/* Error message */}
      <AnimatePresence>
        {progress.error && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400"
          >
            {progress.error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Completion card */}
      {isCompleted && progress.products_count != null && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="rounded-lg border border-green-200 bg-green-50 p-6 text-center dark:border-green-800 dark:bg-green-900/20"
        >
          <span className="text-4xl font-bold text-green-700 dark:text-green-400">
            <NumberFlow value={progress.products_count} />
          </span>
          <p className="mt-1 text-sm text-green-600 dark:text-green-500">
            products ingested
          </p>
          {progress.coverage_percentage != null && (
            <p className="mt-1 text-xs text-green-600/70 dark:text-green-500/70">
              <NumberFlow
                value={Math.round(progress.coverage_percentage * 10) / 10}
                format={{
                  minimumFractionDigits: 1,
                  maximumFractionDigits: 1,
                }}
              />
              % URL coverage
            </p>
          )}
          {progress.shop_url && progress.products_count > 0 && (
            <Link
              href={`/products?shop_id=${encodeURIComponent(progress.shop_url)}`}
              className="mt-4 inline-block rounded-md bg-green-600 px-5 py-2 text-sm font-medium text-white hover:bg-green-700 dark:bg-green-700 dark:hover:bg-green-600"
            >
              View Products
            </Link>
          )}
        </motion.div>
      )}
    </div>
  );
}
