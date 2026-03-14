"use client";

import { useState } from "react";
import type { Product } from "@/lib/types";
import { PLATFORM_COLORS } from "@/lib/constants";
import { ProductEditModal } from "./product-edit-modal";

interface ProductGridProps {
  products: Product[];
  onProductUpdated?: (updated: Product) => void;
}

function formatPrice(price: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency || "USD",
    }).format(price);
  } catch {
    return `${currency} ${price.toFixed(2)}`;
  }
}

export function ProductGrid({ products, onProductUpdated }: ProductGridProps) {
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);

  if (products.length === 0) {
    return (
      <div className="rounded-md border border-[hsl(var(--border))] p-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
        No products found for this shop.
      </div>
    );
  }

  function getMissingCount(p: Product): number {
    let missing = 0;
    if (!p.gtin) missing++;
    if (!p.vendor) missing++;
    if (!p.sku && !p.external_id) missing++;
    if (p.price === 0) missing++;
    if (!p.image_url) missing++;
    if (!p.condition) missing++;
    return missing;
  }

  function getCompletenessColor(p: Product): string {
    const missing = getMissingCount(p);
    if (missing === 0) return "border-l-green-500";
    if (missing <= 2) return "border-l-yellow-500";
    return "border-l-red-500";
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {products.map((product) => (
          <div
            key={product.id}
            onClick={() => setEditingProduct(product)}
            className={`flex cursor-pointer flex-col overflow-hidden rounded-lg border border-l-4 border-[hsl(var(--border))] ${getCompletenessColor(product)} bg-[hsl(var(--card))] transition-shadow hover:shadow-lg`}
          >
            {/* Product image */}
            <div className="relative aspect-square bg-[hsl(var(--muted))]">
              {product.image_url ? (
                <img
                  src={product.image_url}
                  alt={product.title}
                  className="h-full w-full object-cover"
                  loading="lazy"
                />
              ) : (
                <div className="flex h-full items-center justify-center text-[hsl(var(--muted-foreground))]">
                  No image
                </div>
              )}

              {/* Stock badge */}
              <span
                className={`absolute right-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                  product.in_stock
                    ? "bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-400"
                    : "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-400"
                }`}
              >
                {product.in_stock ? "In Stock" : "Out of Stock"}
              </span>

              {/* Edit hint */}
              <div className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition-all hover:bg-black/30 hover:opacity-100">
                <span className="rounded-md bg-white/90 px-3 py-1 text-xs font-medium text-gray-900">
                  Click to edit
                </span>
              </div>
            </div>

            {/* Product info */}
            <div className="flex flex-1 flex-col gap-2 p-3">
              <h3
                className="line-clamp-2 text-sm font-medium text-[hsl(var(--foreground))]"
                title={product.title}
              >
                {product.title}
              </h3>

              <div className="flex items-baseline gap-2">
                <span className="text-lg font-bold text-[hsl(var(--foreground))]">
                  {formatPrice(product.price, product.currency)}
                </span>
                {product.compare_at_price != null &&
                  product.compare_at_price > product.price && (
                    <span className="text-xs text-[hsl(var(--muted-foreground))] line-through">
                      {formatPrice(product.compare_at_price, product.currency)}
                    </span>
                  )}
              </div>

              {/* Missing field badges */}
              {getMissingCount(product) > 0 && (
                <div className="flex flex-wrap gap-1">
                  {!product.gtin && (
                    <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700 dark:bg-red-900/40 dark:text-red-400">
                      No GTIN
                    </span>
                  )}
                  {!product.vendor && (
                    <span className="rounded bg-orange-100 px-1.5 py-0.5 text-[10px] font-medium text-orange-700 dark:bg-orange-900/40 dark:text-orange-400">
                      No Brand
                    </span>
                  )}
                  {product.price === 0 && (
                    <span className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700 dark:bg-red-900/40 dark:text-red-400">
                      $0 Price
                    </span>
                  )}
                </div>
              )}

              {/* Meta row */}
              <div className="mt-auto flex flex-wrap items-center gap-2">
                <span
                  className="rounded px-1.5 py-0.5 text-[10px] font-medium text-white"
                  style={{
                    backgroundColor:
                      PLATFORM_COLORS[product.platform] || PLATFORM_COLORS.generic,
                  }}
                >
                  {product.platform}
                </span>

                {product.vendor && (
                  <span className="text-xs text-[hsl(var(--muted-foreground))]">
                    {product.vendor}
                  </span>
                )}

                {product.sku && (
                  <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
                    SKU: {product.sku}
                  </span>
                )}
              </div>

              {/* View on store link */}
              {product.product_url && (
                <a
                  href={product.product_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 text-xs text-[hsl(var(--primary))] hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  View on store &rarr;
                </a>
              )}
            </div>
          </div>
        ))}
      </div>

      {editingProduct && (
        <ProductEditModal
          product={editingProduct}
          onClose={() => setEditingProduct(null)}
          onSaved={(updated) => {
            setEditingProduct(null);
            onProductUpdated?.(updated);
          }}
        />
      )}
    </>
  );
}
