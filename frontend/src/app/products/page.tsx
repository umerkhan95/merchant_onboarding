"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { Product, ProductListResponse, CompletenessResponse, ValidationResponse } from "@/lib/types";
import { ProductGrid } from "@/components/products/product-grid";

function ProductsContent() {
  const searchParams = useSearchParams();
  const initialShopId = searchParams.get("shop_id") || "";

  const [shopId, setShopId] = useState(initialShopId);
  const [searchInput, setSearchInput] = useState(initialShopId);
  const [page, setPage] = useState(1);
  const [perPage] = useState(24);
  const [data, setData] = useState<ProductListResponse | null>(null);
  const [completeness, setCompleteness] = useState<CompletenessResponse | null>(null);
  const [validation, setValidation] = useState<ValidationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProducts = useCallback(async () => {
    if (!shopId) return;
    setLoading(true);
    setError(null);
    try {
      const [res, compRes, valRes] = await Promise.all([
        apiFetch<ProductListResponse>(
          `/api/v1/products?shop_id=${encodeURIComponent(shopId)}&page=${page}&per_page=${perPage}`
        ),
        apiFetch<CompletenessResponse>(
          `/api/v1/products/completeness?shop_id=${encodeURIComponent(shopId)}&per_page=500`
        ).catch(() => null),
        apiFetch<ValidationResponse>(
          `/api/v1/exports/idealo/validate?shop_id=${encodeURIComponent(shopId)}`
        ).catch(() => null),
      ]);
      setData(res);
      setCompleteness(compRes);
      setValidation(valRes);
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

  function handleProductUpdated(updated: Product) {
    if (!data) return;
    setData({
      ...data,
      data: data.data.map((p) => (p.id === updated.id ? updated : p)),
    });
  }

  async function handleExportCSV() {
    if (!shopId) return;
    window.open(
      `/api/v1/exports/idealo/csv?shop_id=${encodeURIComponent(shopId)}`,
      "_blank"
    );
  }

  const pagination = data?.pagination;
  const summary = completeness?.summary;
  const readyPct = summary?.idealo_ready_pct ?? 0;
  const totalProducts = pagination?.total ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">Products</h2>
          <p className="text-sm text-[hsl(var(--muted-foreground))]">
            Browse, review, and edit product data for idealo export
          </p>
        </div>
        {data && shopId && (
          <button
            onClick={handleExportCSV}
            className="flex items-center gap-2 rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90"
          >
            Export idealo CSV
          </button>
        )}
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

      {/* Completeness + Validation Stats */}
      {data && shopId && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          {/* Total products */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">Total Products</p>
            <p className="mt-1 text-2xl font-bold text-[hsl(var(--foreground))]">{totalProducts}</p>
          </div>

          {/* Idealo Ready */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">idealo Ready</p>
            <p className="mt-1 text-2xl font-bold text-[hsl(var(--foreground))]">
              {summary?.idealo_ready ?? "—"}{" "}
              <span className="text-sm font-normal text-[hsl(var(--muted-foreground))]">
                ({readyPct.toFixed(0)}%)
              </span>
            </p>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[hsl(var(--muted))]">
              <div
                className={`h-full rounded-full transition-all ${readyPct >= 80 ? "bg-green-500" : readyPct >= 50 ? "bg-yellow-500" : "bg-red-500"}`}
                style={{ width: `${readyPct}%` }}
              />
            </div>
          </div>

          {/* Export Readiness */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">Export Status</p>
            {validation ? (
              validation.ready ? (
                <p className="mt-1 text-lg font-bold text-green-600">Ready to Export</p>
              ) : (
                <p className="mt-1 text-lg font-bold text-red-500">
                  {validation.issue_count} issue{validation.issue_count !== 1 ? "s" : ""}
                </p>
              )
            ) : (
              <p className="mt-1 text-lg text-[hsl(var(--muted-foreground))]">—</p>
            )}
            {validation && validation.warning_count > 0 && (
              <p className="mt-1 text-xs text-orange-500">
                {validation.warning_count} warning{validation.warning_count !== 1 ? "s" : ""}
              </p>
            )}
          </div>

          {/* Field Coverage */}
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <p className="text-xs font-medium text-[hsl(var(--muted-foreground))]">Field Coverage</p>
            {summary?.fields && Object.keys(summary.fields).length > 0 ? (
              <div className="mt-2 space-y-1">
                {Object.entries(summary.fields).slice(0, 4).map(([field, data]) => (
                  <div key={field} className="flex items-center gap-2 text-xs">
                    <span className="w-16 capitalize text-[hsl(var(--muted-foreground))]">{field}</span>
                    <div className="h-1 flex-1 overflow-hidden rounded-full bg-[hsl(var(--muted))]">
                      <div
                        className={`h-full rounded-full ${data.coverage_pct >= 80 ? "bg-green-500" : data.coverage_pct >= 50 ? "bg-yellow-500" : "bg-red-500"}`}
                        style={{ width: `${data.coverage_pct}%` }}
                      />
                    </div>
                    <span className="w-8 text-right text-[hsl(var(--foreground))]">{data.coverage_pct}%</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-1 text-lg text-[hsl(var(--muted-foreground))]">—</p>
            )}
          </div>
        </div>
      )}

      {/* Validation issues/warnings */}
      {validation && (validation.issues.length > 0 || validation.warnings.length > 0) && (
        <div className="space-y-2">
          {validation.issues.map((issue, i) => (
            <div key={i} className="flex items-center gap-2 rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
              <span className="font-medium">Blocker:</span> {issue}
            </div>
          ))}
          {validation.warnings.map((warning, i) => (
            <div key={i} className="flex items-center gap-2 rounded-md bg-orange-50 p-3 text-sm text-orange-700 dark:bg-orange-900/20 dark:text-orange-400">
              <span className="font-medium">Warning:</span> {warning}
            </div>
          ))}
        </div>
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

      {/* Click hint */}
      {data && !loading && data.data.length > 0 && (
        <p className="text-xs text-[hsl(var(--muted-foreground))]">
          Click any product card to edit GTIN, brand, condition, and other fields.
        </p>
      )}

      {data && !loading && (
        <ProductGrid products={data.data} onProductUpdated={handleProductUpdated} />
      )}

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
