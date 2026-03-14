"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Product } from "@/lib/types";

interface ProductEditModalProps {
  product: Product;
  onClose: () => void;
  onSaved: (updated: Product) => void;
}

export function ProductEditModal({ product, onClose, onSaved }: ProductEditModalProps) {
  const [gtin, setGtin] = useState(product.gtin || "");
  const [brand, setBrand] = useState(product.vendor || "");
  const [mpn, setMpn] = useState(product.mpn || "");
  const [condition, setCondition] = useState(product.condition || "NEW");
  const [description, setDescription] = useState(product.description || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSuccess(false);

    const body: Record<string, string | string[]> = {};
    if (gtin !== (product.gtin || "")) body.gtin = gtin;
    if (brand !== (product.vendor || "")) body.brand = brand;
    if (mpn !== (product.mpn || "")) body.mpn = mpn;
    if (condition !== (product.condition || "NEW")) body.condition = condition;
    if (description !== (product.description || "")) body.description = description;

    if (Object.keys(body).length === 0) {
      setError("No changes to save");
      setSaving(false);
      return;
    }

    try {
      const updated = await apiFetch<Product>(
        `/api/v1/products/${product.id}`,
        { method: "PATCH", body: JSON.stringify(body) }
      );
      setSuccess(true);
      onSaved(updated);
      setTimeout(() => onClose(), 800);
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }

  // Missing field indicators
  const missingFields: string[] = [];
  if (!product.gtin && !gtin) missingFields.push("GTIN/EAN");
  if (!product.vendor && !brand) missingFields.push("Brand");
  if (!product.sku && !product.external_id) missingFields.push("SKU");
  if (product.price === 0) missingFields.push("Price");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="relative mx-4 flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl bg-[hsl(var(--card))] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start gap-4 border-b border-[hsl(var(--border))] p-5">
          {product.image_url ? (
            <img
              src={product.image_url}
              alt={product.title}
              className="h-20 w-20 shrink-0 rounded-lg object-cover"
            />
          ) : (
            <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-lg bg-[hsl(var(--muted))] text-xs text-[hsl(var(--muted-foreground))]">
              No img
            </div>
          )}
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-[hsl(var(--foreground))]">{product.title}</h2>
            <div className="mt-1 flex flex-wrap gap-2 text-sm text-[hsl(var(--muted-foreground))]">
              <span className="font-medium text-[hsl(var(--foreground))]">
                {new Intl.NumberFormat("en-US", { style: "currency", currency: product.currency || "USD" }).format(product.price)}
              </span>
              {product.sku && <span>SKU: {product.sku}</span>}
              <span className="capitalize">{product.platform}</span>
            </div>
            {missingFields.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {missingFields.map((f) => (
                  <span key={f} className="rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700 dark:bg-red-900/40 dark:text-red-400">
                    Missing {f}
                  </span>
                ))}
              </div>
            )}
          </div>
          <button onClick={onClose} className="shrink-0 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]" aria-label="Close">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>

        {/* Form */}
        <div className="flex-1 overflow-y-auto p-5">
          <div className="grid gap-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-[hsl(var(--muted-foreground))]">
                  GTIN / EAN {!product.gtin && <span className="text-red-500">*</span>}
                </label>
                <input
                  type="text"
                  value={gtin}
                  onChange={(e) => setGtin(e.target.value)}
                  placeholder="e.g. 4006381333931"
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-[hsl(var(--muted-foreground))]">
                  Brand {!product.vendor && <span className="text-red-500">*</span>}
                </label>
                <input
                  type="text"
                  value={brand}
                  onChange={(e) => setBrand(e.target.value)}
                  placeholder="e.g. Brooklinen"
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-[hsl(var(--muted-foreground))]">MPN</label>
                <input
                  type="text"
                  value={mpn}
                  onChange={(e) => setMpn(e.target.value)}
                  placeholder="Manufacturer Part Number"
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-[hsl(var(--muted-foreground))]">Condition</label>
                <select
                  value={condition}
                  onChange={(e) => setCondition(e.target.value)}
                  className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))]"
                >
                  <option value="NEW">New</option>
                  <option value="REFURBISHED">Refurbished</option>
                  <option value="USED">Used</option>
                </select>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-[hsl(var(--muted-foreground))]">Description</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
              />
            </div>

            {/* Read-only fields */}
            <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 p-3">
              <p className="mb-2 text-xs font-medium text-[hsl(var(--muted-foreground))]">Read-only (from extraction)</p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <span className="text-[hsl(var(--muted-foreground))]">External ID:</span>
                <span className="text-[hsl(var(--foreground))]">{product.external_id || "—"}</span>
                <span className="text-[hsl(var(--muted-foreground))]">SKU:</span>
                <span className="text-[hsl(var(--foreground))]">{product.sku || "—"}</span>
                <span className="text-[hsl(var(--muted-foreground))]">Price:</span>
                <span className="text-[hsl(var(--foreground))]">{product.price} {product.currency}</span>
                <span className="text-[hsl(var(--muted-foreground))]">Product URL:</span>
                <a href={product.product_url} target="_blank" rel="noopener noreferrer" className="truncate text-[hsl(var(--primary))] hover:underline">
                  {product.product_url || "—"}
                </a>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-[hsl(var(--border))] px-5 py-3">
          <div className="text-sm">
            {error && <span className="text-red-500">{error}</span>}
            {success && <span className="text-green-600">Saved!</span>}
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded-md border border-[hsl(var(--border))] px-4 py-2 text-sm text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-md bg-[hsl(var(--primary))] px-4 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
