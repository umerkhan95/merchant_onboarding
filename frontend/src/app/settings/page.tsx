"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { MerchantSettingsResponse, ValidationResponse } from "@/lib/types";

export default function SettingsPage() {
  const [shopId, setShopId] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [deliveryTime, setDeliveryTime] = useState("");
  const [deliveryCosts, setDeliveryCosts] = useState("");
  const [paymentCosts, setPaymentCosts] = useState("");
  const [brandFallback, setBrandFallback] = useState("");
  const [defaultCondition, setDefaultCondition] = useState("NEW");
  const [validation, setValidation] = useState<ValidationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const fetchSettings = useCallback(async () => {
    if (!shopId) return;
    setLoading(true);
    setError(null);
    setSuccess(false);
    try {
      const [settingsRes, valRes] = await Promise.all([
        apiFetch<MerchantSettingsResponse>(
          `/api/v1/merchants/settings?shop_id=${encodeURIComponent(shopId)}`
        ),
        apiFetch<ValidationResponse>(
          `/api/v1/exports/idealo/validate?shop_id=${encodeURIComponent(shopId)}`
        ).catch(() => null),
      ]);
      const s = settingsRes.settings;
      if (s) {
        setDeliveryTime(s.delivery_time || "");
        setDeliveryCosts(s.delivery_costs || "");
        setPaymentCosts(s.payment_costs || "");
        setBrandFallback(s.brand_fallback || "");
        setDefaultCondition(s.default_condition || "NEW");
      } else {
        setDeliveryTime("");
        setDeliveryCosts("");
        setPaymentCosts("");
        setBrandFallback("");
        setDefaultCondition("NEW");
      }
      setValidation(valRes);
      setLoaded(true);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [shopId]);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setShopId(searchInput);
    setLoaded(false);
  }

  async function handleSave() {
    if (!shopId) return;
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await apiFetch(`/api/v1/merchants/settings?shop_id=${encodeURIComponent(shopId)}`, {
        method: "PUT",
        body: JSON.stringify({
          delivery_time: deliveryTime,
          delivery_costs: deliveryCosts,
          payment_costs: paymentCosts,
          brand_fallback: brandFallback,
          default_condition: defaultCondition,
        }),
      });
      setSuccess(true);
      // Refresh validation
      const valRes = await apiFetch<ValidationResponse>(
        `/api/v1/exports/idealo/validate?shop_id=${encodeURIComponent(shopId)}`
      ).catch(() => null);
      setValidation(valRes);
    } catch (err) {
      setError(String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-[hsl(var(--foreground))]">Merchant Settings</h2>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Configure delivery, shipping, and payment settings for idealo export
        </p>
      </div>

      {/* Shop search */}
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
          Load
        </button>
      </form>

      {loading && (
        <div className="py-4 text-center text-sm text-[hsl(var(--muted-foreground))]">Loading settings...</div>
      )}

      {/* Export readiness banner */}
      {validation && loaded && (
        <div
          className={`rounded-lg border p-4 ${
            validation.ready
              ? "border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-900/20"
              : "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-900/20"
          }`}
        >
          <p className={`text-sm font-medium ${validation.ready ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}`}>
            {validation.ready ? "Ready to export to idealo" : `${validation.issue_count} issue${validation.issue_count !== 1 ? "s" : ""} blocking export`}
          </p>
          {validation.issues.length > 0 && (
            <ul className="mt-2 space-y-1">
              {validation.issues.map((issue, i) => (
                <li key={i} className="text-xs text-red-600 dark:text-red-400">- {issue}</li>
              ))}
            </ul>
          )}
          {validation.warnings.length > 0 && (
            <ul className="mt-2 space-y-1">
              {validation.warnings.map((w, i) => (
                <li key={i} className="text-xs text-orange-600 dark:text-orange-400">- {w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Settings form */}
      {loaded && !loading && (
        <div className="space-y-4 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6">
          <h3 className="text-base font-semibold text-[hsl(var(--foreground))]">Delivery & Payment</h3>

          <div>
            <label className="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">
              Delivery Time <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={deliveryTime}
              onChange={(e) => setDeliveryTime(e.target.value)}
              placeholder="e.g. 1-3 working days"
              className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">
                Delivery Costs <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={deliveryCosts}
                onChange={(e) => setDeliveryCosts(e.target.value)}
                placeholder="e.g. 4.95 or DHL:4.95;DPD:5.95"
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">
                Payment Costs <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={paymentCosts}
                onChange={(e) => setPaymentCosts(e.target.value)}
                placeholder="e.g. 0.00 or PayPal:0.35"
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
              />
            </div>
          </div>

          <h3 className="pt-2 text-base font-semibold text-[hsl(var(--foreground))]">Defaults</h3>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">
                Brand Fallback
              </label>
              <input
                type="text"
                value={brandFallback}
                onChange={(e) => setBrandFallback(e.target.value)}
                placeholder="Used when product has no brand"
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-[hsl(var(--foreground))]">
                Default Condition
              </label>
              <select
                value={defaultCondition}
                onChange={(e) => setDefaultCondition(e.target.value)}
                className="w-full rounded-md border border-[hsl(var(--input))] bg-[hsl(var(--background))] px-3 py-2 text-sm text-[hsl(var(--foreground))]"
              >
                <option value="NEW">New</option>
                <option value="REFURBISHED">Refurbished</option>
                <option value="USED">Used</option>
              </select>
            </div>
          </div>

          {/* Save */}
          <div className="flex items-center justify-between pt-4">
            <div className="text-sm">
              {error && <span className="text-red-500">{error}</span>}
              {success && <span className="text-green-600">Settings saved!</span>}
            </div>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded-md bg-[hsl(var(--primary))] px-6 py-2 text-sm font-medium text-[hsl(var(--primary-foreground))] hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save Settings"}
            </button>
          </div>
        </div>
      )}

      {!loaded && !loading && !shopId && (
        <div className="rounded-md border border-[hsl(var(--border))] p-8 text-center text-sm text-[hsl(var(--muted-foreground))]">
          Enter a shop URL above to load or create merchant settings.
        </div>
      )}
    </div>
  );
}
