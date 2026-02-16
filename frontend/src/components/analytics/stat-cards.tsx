"use client";

import { useEffect, useState } from "react";
import { formatDuration } from "@/lib/utils";
import type { AnalyticsSummary } from "@/lib/types";

function AnimatedNumber({ value, suffix = "" }: { value: number; suffix?: string }) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (value === 0) { setDisplay(0); return; }
    const duration = 800;
    const steps = 30;
    const increment = value / steps;
    let current = 0;
    let step = 0;
    const timer = setInterval(() => {
      step++;
      current = Math.min(Math.round(increment * step), value);
      setDisplay(current);
      if (step >= steps) clearInterval(timer);
    }, duration / steps);
    return () => clearInterval(timer);
  }, [value]);

  return <>{display.toLocaleString()}{suffix}</>;
}

export function StatCards({ data }: { data: AnalyticsSummary }) {
  const cards = [
    {
      label: "Total Jobs",
      value: data.total_jobs,
      display: <AnimatedNumber value={data.total_jobs} />,
      accent: "from-blue-500 to-blue-600",
      iconBg: "bg-blue-500/10",
    },
    {
      label: "Total Products",
      value: data.total_products,
      display: <AnimatedNumber value={data.total_products} />,
      accent: "from-emerald-500 to-emerald-600",
      iconBg: "bg-emerald-500/10",
    },
    {
      label: "Success Rate",
      value: data.success_rate,
      display: <AnimatedNumber value={Math.round(data.success_rate)} suffix="%" />,
      accent: data.success_rate >= 80 ? "from-green-500 to-green-600" : data.success_rate >= 50 ? "from-yellow-500 to-yellow-600" : "from-red-500 to-red-600",
      iconBg: data.success_rate >= 80 ? "bg-green-500/10" : data.success_rate >= 50 ? "bg-yellow-500/10" : "bg-red-500/10",
    },
    {
      label: "Avg Duration",
      value: 0,
      display: <>{formatDuration(data.avg_duration_seconds)}</>,
      accent: "from-purple-500 to-purple-600",
      iconBg: "bg-purple-500/10",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="group relative overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5 transition-all duration-200 hover:shadow-lg hover:shadow-black/5 hover:-translate-y-0.5"
        >
          <div className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${card.accent} opacity-0 transition-opacity duration-200 group-hover:opacity-100`} />
          <p className="text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
            {card.label}
          </p>
          <p className="mt-2 text-3xl font-bold text-[hsl(var(--foreground))]">
            {card.display}
          </p>
        </div>
      ))}
    </div>
  );
}
