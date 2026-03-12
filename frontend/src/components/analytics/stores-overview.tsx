"use client";

import Link from "next/link";
import type { MerchantProfile } from "@/lib/types";
import { PLATFORM_COLORS } from "@/lib/constants";

interface StoresOverviewProps {
  stores: MerchantProfile[] | null;
}

export function StoresOverview({ stores }: StoresOverviewProps) {
  if (!stores || stores.length === 0) return null;

  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
          Extracted Stores ({stores.length})
        </h3>
        <Link
          href="/stores"
          className="text-xs text-[hsl(var(--primary))] hover:underline"
        >
          View all
        </Link>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {stores.slice(0, 6).map((store) => {
          const domain = store.shop_url
            ? new URL(store.shop_url.startsWith("http") ? store.shop_url : `https://${store.shop_url}`).hostname.replace("www.", "")
            : store.shop_id;
          const platformColor = PLATFORM_COLORS[store.platform] || PLATFORM_COLORS.generic;

          return (
            <Link
              key={store.shop_id}
              href={`/stores/${encodeURIComponent(store.shop_id)}`}
              className="flex items-center gap-3 rounded-lg border border-[hsl(var(--border))] p-3 transition-colors hover:bg-[hsl(var(--accent))]"
            >
              {store.logo_url || store.favicon_url ? (
                <img
                  src={store.logo_url || store.favicon_url || ""}
                  alt=""
                  className="h-10 w-10 rounded-md object-contain bg-white border border-[hsl(var(--border))]"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none";
                  }}
                />
              ) : (
                <div className="flex h-10 w-10 items-center justify-center rounded-md bg-[hsl(var(--muted))] text-sm font-bold text-[hsl(var(--muted-foreground))]">
                  {(store.company_name || domain).charAt(0).toUpperCase()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-[hsl(var(--foreground))]">
                  {store.company_name || domain}
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className="inline-block rounded px-1.5 py-0.5 text-[10px] font-medium text-white capitalize"
                    style={{ backgroundColor: platformColor }}
                  >
                    {store.platform}
                  </span>
                  <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
                    {Math.round(store.extraction_confidence * 100)}% confidence
                  </span>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
