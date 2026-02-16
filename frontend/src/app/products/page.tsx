"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { ProductListResponse } from "@/lib/types";
import { ProductGrid } from "@/components/products/product-grid";

function ProductsContent() {
  const searchParams = useSearchParams();
  const initialShopId = searchParams.get("shop_id") || "";

  const [shopId, setShopId] = useState(initialShopId);
  const [searchInput, setSearchInput] = useState(initialShopId);
  const [page, setPage] = useState(1);
  const [perPage] = useState(24);
  const [data, setData] = useState<ProductListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProducts = useCallback(async () => {
    if (!shopId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<ProductListResponse>(
        `/api/v1/products?shop_id=${encodeURIComponent(shopId)}&page=${page}&per_page=${perPage}`
      );
      setData(res);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [shopId, page, perPage]);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setShopId(searchInput);
  }

  const pagination = data?.pagination;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">
          Products
        </h2>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Browse extracted products by shop
        </p>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Enter shop URL (e.g. https://example.com)"
          className="flex-1 rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
        />
        <button
          type="submit"
          className="rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90"
        >
          Search
        </button>
      </form>

      {/* Results info */}
      {data && shopId && (
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          {pagination?.total ?? 0} products for{" "}
          <span className="font-medium text-[hsl(var(--foreground))]">{shopId}</span>
        </p>
      )}

      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}

      {loading && (
        <div className="py-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
          Loading products...
        </div>
      )}

      {data && !loading && <ProductGrid products={data.data} />}

      {/* Pagination */}
      {pagination && pagination.total_pages > 1 && (
        <div className="flex items-center justify-center gap-4">
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-sm text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-sm text-[hsl(var(--muted-foreground))]">
            Page {page} of {pagination.total_pages}
          </span>
          <button
            disabled={page >= pagination.total_pages}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-sm text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

export default function ProductsPage() {
  return (
    <Suspense
      fallback={
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Loading products...
        </p>
      }
    >
      <ProductsContent />
    </Suspense>
  );
}
