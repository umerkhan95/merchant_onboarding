"use client";

import { AnimatePresence, motion } from "motion/react";
import type { RecentProduct } from "@/lib/types";

interface ProductStreamProps {
  products?: RecentProduct[] | null;
}

function ProductCard({ product, index }: { product: RecentProduct; index: number }) {
  const price =
    typeof product.price === "number"
      ? `$${product.price.toFixed(2)}`
      : product.price
        ? `$${product.price}`
        : "";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ delay: index * 0.08, duration: 0.3 }}
      className="flex w-40 shrink-0 flex-col overflow-hidden rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))]"
    >
      <div className="relative h-24 w-full bg-[hsl(var(--muted))]">
        {product.image_url ? (
          <img
            src={product.image_url}
            alt={product.title}
            className="h-full w-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-[hsl(var(--muted-foreground))]">
            No image
          </div>
        )}
      </div>
      <div className="space-y-0.5 p-2">
        <p className="line-clamp-2 text-xs font-medium text-[hsl(var(--foreground))]">
          {product.title || "Untitled"}
        </p>
        {price && (
          <p className="text-xs font-semibold text-[hsl(var(--primary))]">
            {price}
          </p>
        )}
      </div>
    </motion.div>
  );
}

export function ProductStream({ products }: ProductStreamProps) {
  if (!products || products.length === 0) {
    return (
      <div className="flex gap-3 overflow-x-auto py-1">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="w-40 shrink-0 animate-pulse rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]"
          >
            <div className="h-24 bg-[hsl(var(--muted))]" />
            <div className="space-y-1.5 p-2">
              <div className="h-3 w-3/4 rounded bg-[hsl(var(--border))]" />
              <div className="h-3 w-1/2 rounded bg-[hsl(var(--border))]" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex gap-3 overflow-x-auto py-1">
      <AnimatePresence mode="popLayout">
        {products.map((product, i) => (
          <ProductCard
            key={`${product.title}-${i}`}
            product={product}
            index={i}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}
