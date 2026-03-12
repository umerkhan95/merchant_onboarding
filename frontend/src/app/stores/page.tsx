"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { MerchantProfile } from "@/lib/types";
import { StoresTable } from "@/components/stores/stores-table";

export default function StoresPage() {
  const [stores, setStores] = useState<MerchantProfile[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchStores = useCallback(async () => {
    try {
      const res = await apiFetch<MerchantProfile[]>("/api/v1/merchants/profiles");
      setStores(res);
      setError(null);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    fetchStores();
    const interval = setInterval(fetchStores, 15_000);
    return () => clearInterval(interval);
  }, [fetchStores]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">
          Stores
        </h2>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          {stores ? `${stores.length} extracted stores` : "Loading..."}
        </p>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}

      {stores && <StoresTable stores={stores} />}
    </div>
  );
}
