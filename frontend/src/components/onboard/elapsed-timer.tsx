"use client";

import { useEffect, useState } from "react";

interface ElapsedTimerProps {
  startedAt?: string;
  completedAt?: string;
}

export function ElapsedTimer({ startedAt, completedAt }: ElapsedTimerProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) return;

    const start = new Date(startedAt).getTime();

    if (completedAt) {
      const end = new Date(completedAt).getTime();
      setElapsed(Math.floor((end - start) / 1000));
      return;
    }

    const tick = () => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt, completedAt]);

  if (!startedAt) return null;

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;

  return (
    <span className="tabular-nums text-xs text-[hsl(var(--muted-foreground))]">
      {mins}:{secs.toString().padStart(2, "0")}
    </span>
  );
}
