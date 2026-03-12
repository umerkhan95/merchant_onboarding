"use client";

import { useState } from "react";
import { UrlForm } from "@/components/onboard/url-form";
import { ProgressDisplay } from "@/components/onboard/progress-display";
import { useSSE } from "@/hooks/use-sse";
import { apiFetch } from "@/lib/api";
import type { OnboardingResponse } from "@/lib/types";

type Phase = "idle" | "submitting" | "tracking" | "completed" | "failed";

export default function OnboardPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const { progress, done, error, start, stop } = useSSE();

  async function handleSubmit(url: string) {
    setPhase("submitting");
    try {
      const res = await apiFetch<OnboardingResponse>("/api/v1/onboard", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
      setJobId(res.job_id);
      setPhase("tracking");
      start(res.job_id);
    } catch (err) {
      setPhase("failed");
    }
  }

  // Update phase when SSE finishes
  if (done && phase === "tracking") {
    setPhase(progress?.status === "failed" ? "failed" : "completed");
  }

  function handleReset() {
    stop();
    setPhase("idle");
    setJobId(null);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">
          Onboard a Store
        </h2>
        <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
          Enter a store URL to detect the platform, discover products, and
          ingest the catalog.
        </p>
      </div>

      <UrlForm
        onSubmit={handleSubmit}
        disabled={phase === "submitting" || phase === "tracking"}
      />

      {jobId && (
        <p className="text-xs text-[hsl(var(--muted-foreground))]">
          Job ID: <code>{jobId}</code>
        </p>
      )}

      {progress && <ProgressDisplay progress={progress} />}

      {error && !progress?.error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          Connection error: {error}
        </div>
      )}

      {(phase === "completed" || phase === "failed") && (
        <button
          onClick={handleReset}
          className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]"
        >
          Onboard Another Store
        </button>
      )}
    </div>
  );
}
