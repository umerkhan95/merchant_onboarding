"use client";

import { useCallback, useRef, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { getApiKey } from "@/lib/api";
import type { JobProgress } from "@/lib/types";

export function useSSE() {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ctrlRef = useRef<AbortController | null>(null);

  const start = useCallback((jobId: string) => {
    setProgress(null);
    setDone(false);
    setError(null);

    const ctrl = new AbortController();
    ctrlRef.current = ctrl;

    // SSE must bypass the Next.js rewrite proxy (it buffers responses).
    // Connect directly to the backend for streaming.
    const baseUrl = process.env.NEXT_PUBLIC_SSE_URL || "http://localhost:8000";
    fetchEventSource(`${baseUrl}/api/v1/onboard/${jobId}/progress`, {
      method: "GET",
      headers: { "X-API-Key": getApiKey() },
      signal: ctrl.signal,

      onmessage(ev) {
        if (ev.event === "progress" || ev.event === "done") {
          const data: JobProgress = JSON.parse(ev.data);
          setProgress(data);
          if (ev.event === "done") {
            setDone(true);
            ctrl.abort();
          }
        }
        if (ev.event === "error") {
          setError(ev.data);
          ctrl.abort();
        }
      },

      onerror(err) {
        setError(String(err));
        ctrl.abort();
        throw err; // stop retries
      },
    });
  }, []);

  const stop = useCallback(() => {
    ctrlRef.current?.abort();
  }, []);

  return { progress, done, error, start, stop };
}
