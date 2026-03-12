"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { motion } from "motion/react";
import {
  Clock,
  Search,
  Globe,
  Download,
  ShieldCheck,
  Layers,
  CheckCircle,
} from "lucide-react";
import { PIPELINE_STEPS } from "@/lib/constants";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Clock,
  Search,
  Globe,
  Download,
  ShieldCheck,
  Layers,
  CheckCircle,
};

interface PipelineFlowProps {
  currentStatus: string;
  isFailed: boolean;
}

interface BeamPath {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export function PipelineFlow({ currentStatus, isFailed }: PipelineFlowProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const nodeRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [beams, setBeams] = useState<BeamPath[]>([]);

  const currentIdx = PIPELINE_STEPS.findIndex((s) => s.key === currentStatus);

  const computeBeams = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const containerRect = container.getBoundingClientRect();
    const newBeams: BeamPath[] = [];

    for (let i = 0; i < PIPELINE_STEPS.length - 1; i++) {
      const from = nodeRefs.current[i];
      const to = nodeRefs.current[i + 1];
      if (!from || !to) continue;

      const fromRect = from.getBoundingClientRect();
      const toRect = to.getBoundingClientRect();

      newBeams.push({
        x1: fromRect.left + fromRect.width / 2 - containerRect.left,
        y1: fromRect.top + fromRect.height / 2 - containerRect.top,
        x2: toRect.left + toRect.width / 2 - containerRect.left,
        y2: toRect.top + toRect.height / 2 - containerRect.top,
      });
    }

    setBeams(newBeams);
  }, []);

  useEffect(() => {
    computeBeams();
    const observer = new ResizeObserver(computeBeams);
    if (containerRef.current) observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [computeBeams]);

  return (
    <div ref={containerRef} className="relative">
      {/* SVG beams */}
      <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible">
        <defs>
          <linearGradient id="beam-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.8" />
            <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.3" />
          </linearGradient>
        </defs>
        {beams.map((beam, i) => {
          const isComplete = i < currentIdx;
          const isActive = i === currentIdx - 1;
          return (
            <g key={i}>
              {/* Background line */}
              <line
                x1={beam.x1}
                y1={beam.y1}
                x2={beam.x2}
                y2={beam.y2}
                stroke="hsl(var(--border))"
                strokeWidth={2}
              />
              {/* Filled line */}
              {isComplete && (
                <motion.line
                  x1={beam.x1}
                  y1={beam.y1}
                  x2={beam.x2}
                  y2={beam.y2}
                  stroke="hsl(var(--primary))"
                  strokeWidth={2}
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
                  transition={{ duration: 0.5, ease: "easeOut" }}
                />
              )}
              {/* Traveling dot */}
              {isActive && !isFailed && (
                <motion.circle
                  r={3}
                  fill="hsl(var(--primary))"
                  initial={{ cx: beam.x1, cy: beam.y1 }}
                  animate={{ cx: beam.x2, cy: beam.y2 }}
                  transition={{
                    duration: 1.5,
                    repeat: Infinity,
                    ease: "linear",
                  }}
                />
              )}
            </g>
          );
        })}
      </svg>

      {/* Nodes */}
      <div className="relative flex items-center justify-between">
        {PIPELINE_STEPS.map((step, idx) => {
          const Icon = ICON_MAP[step.icon];
          const isComplete = idx < currentIdx && !isFailed;
          const isActive = idx === currentIdx;
          const isCurrent = isActive && !isFailed;

          return (
            <div
              key={step.key}
              className="flex flex-col items-center gap-1.5"
              ref={(el) => { nodeRefs.current[idx] = el; }}
            >
              <motion.div
                className={cn(
                  "relative flex h-10 w-10 items-center justify-center rounded-full border-2 transition-colors",
                  isComplete
                    ? "border-[hsl(var(--primary))] bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                    : isCurrent
                      ? "border-[hsl(var(--primary))] bg-[hsl(var(--background))] text-[hsl(var(--primary))]"
                      : isActive && isFailed
                        ? "border-red-500 bg-red-50 text-red-500 dark:bg-red-900/20"
                        : "border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))]"
                )}
                animate={
                  isCurrent
                    ? { scale: [1, 1.08, 1] }
                    : { scale: 1 }
                }
                transition={
                  isCurrent
                    ? { duration: 1.5, repeat: Infinity, ease: "easeInOut" }
                    : undefined
                }
              >
                {Icon && <Icon className="h-4 w-4" />}
              </motion.div>
              <span
                className={cn(
                  "text-[10px] leading-tight",
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
    </div>
  );
}
