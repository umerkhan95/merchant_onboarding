"use client";

import Link from "next/link";
import type { MerchantProfile } from "@/lib/types";
import { PLATFORM_COLORS } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";

interface StoresTableProps {
  stores: MerchantProfile[];
}

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 70
      ? "text-green-700 bg-green-100 dark:text-green-300 dark:bg-green-900/40"
      : pct >= 40
        ? "text-yellow-700 bg-yellow-100 dark:text-yellow-300 dark:bg-yellow-900/40"
        : "text-red-700 bg-red-100 dark:text-red-300 dark:bg-red-900/40";
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {pct}%
    </span>
  );
}

export function StoresTable({ stores }: StoresTableProps) {
  if (stores.length === 0) {
    return (
      <div className="rounded-md border border-[hsl(var(--border))] p-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
        No stores extracted yet. Onboard a store to see its profile here.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-[hsl(var(--border))]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[hsl(var(--border))] bg-[hsl(var(--muted))]">
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Store
            </th>
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Platform
            </th>
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Industry
            </th>
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Currency
            </th>
            <th className="px-4 py-3 text-center font-medium text-[hsl(var(--muted-foreground))]">
              Confidence
            </th>
            <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
              Extracted
            </th>
          </tr>
        </thead>
        <tbody>
          {stores.map((store) => {
            const domain = store.shop_url
              ? new URL(store.shop_url.startsWith("http") ? store.shop_url : `https://${store.shop_url}`).hostname.replace("www.", "")
              : store.shop_id;
            const platformColor = PLATFORM_COLORS[store.platform] || PLATFORM_COLORS.generic;

            return (
              <tr
                key={store.shop_id}
                className="border-b border-[hsl(var(--border))] last:border-b-0 hover:bg-[hsl(var(--accent))] transition-colors"
              >
                <td className="px-4 py-3">
                  <Link
                    href={`/stores/${encodeURIComponent(store.shop_id)}`}
                    className="flex items-center gap-3 group"
                  >
                    {store.logo_url || store.favicon_url ? (
                      <img
                        src={store.logo_url || store.favicon_url || ""}
                        alt=""
                        className="h-8 w-8 rounded-md object-contain bg-white border border-[hsl(var(--border))]"
                        onError={(e) => {
                          (e.target as HTMLImageElement).style.display = "none";
                        }}
                      />
                    ) : (
                      <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[hsl(var(--muted))] text-xs font-bold text-[hsl(var(--muted-foreground))]">
                        {(store.company_name || domain).charAt(0).toUpperCase()}
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="font-medium text-[hsl(var(--foreground))] group-hover:text-[hsl(var(--primary))] truncate">
                        {store.company_name || domain}
                      </div>
                      <div className="text-xs text-[hsl(var(--muted-foreground))] truncate">
                        {domain}
                      </div>
                    </div>
                  </Link>
                </td>
                <td className="px-4 py-3">
                  <span
                    className="inline-block rounded-full px-2 py-0.5 text-xs font-medium text-white capitalize"
                    style={{ backgroundColor: platformColor }}
                  >
                    {store.platform}
                  </span>
                </td>
                <td className="px-4 py-3 text-[hsl(var(--muted-foreground))]">
                  {store.industry || "-"}
                </td>
                <td className="px-4 py-3 font-mono text-xs">
                  {store.currency || "-"}
                </td>
                <td className="px-4 py-3 text-center">
                  <ConfidenceBadge value={store.extraction_confidence} />
                </td>
                <td className="px-4 py-3 text-[hsl(var(--muted-foreground))]">
                  {timeAgo(store.scraped_at)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
