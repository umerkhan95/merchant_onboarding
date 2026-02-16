import { formatDuration } from "@/lib/utils";
import type { AnalyticsSummary } from "@/lib/types";

export function StatCards({ data }: { data: AnalyticsSummary }) {
  const cards = [
    {
      label: "Total Jobs",
      value: data.total_jobs.toLocaleString(),
    },
    {
      label: "Total Products",
      value: data.total_products.toLocaleString(),
    },
    {
      label: "Success Rate",
      value: `${data.success_rate}%`,
    },
    {
      label: "Avg Duration",
      value: formatDuration(data.avg_duration_seconds),
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {cards.map((card) => (
        <div
          key={card.label}
          className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4"
        >
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">
            {card.label}
          </p>
          <p className="mt-1 text-2xl font-bold text-[hsl(var(--foreground))]">
            {card.value}
          </p>
        </div>
      ))}
    </div>
  );
}
