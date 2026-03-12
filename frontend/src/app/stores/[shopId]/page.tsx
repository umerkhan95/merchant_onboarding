"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { MerchantProfile, ProductListResponse } from "@/lib/types";
import { MerchantProfileCard } from "@/components/stores/merchant-profile-card";
import { ProductGrid } from "@/components/products/product-grid";

export default function StoreDetailPage() {
  const params = useParams();
  const shopId = decodeURIComponent(params.shopId as string);

  const [profile, setProfile] = useState<MerchantProfile | null>(null);
  const [products, setProducts] = useState<ProductListResponse | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [profileRes, productsRes] = await Promise.allSettled([
        apiFetch<MerchantProfile>(`/api/v1/merchants/profile?shop_id=${encodeURIComponent(shopId)}`),
        apiFetch<ProductListResponse>(`/api/v1/products?shop_id=${encodeURIComponent(shopId)}&per_page=12`),
      ]);

      if (profileRes.status === "fulfilled") {
        setProfile(profileRes.value);
      } else {
        setProfileError("Profile not found");
      }

      if (productsRes.status === "fulfilled") {
        setProducts(productsRes.value);
      }
    } finally {
      setLoading(false);
    }
  }, [shopId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 w-48 rounded-md bg-[hsl(var(--muted))]" />
        <div className="h-64 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))]" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Back link */}
      <Link
        href="/stores"
        className="inline-flex items-center gap-1 text-sm text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
      >
        &larr; Back to Stores
      </Link>

      {/* Merchant Profile */}
      {profile ? (
        <MerchantProfileCard profile={profile} />
      ) : (
        profileError && (
          <div className="rounded-md border border-[hsl(var(--border))] p-6 text-center text-sm text-[hsl(var(--muted-foreground))]">
            {profileError}
          </div>
        )
      )}

      {/* Products Section */}
      {products && products.data.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-[hsl(var(--foreground))]">
              Products ({products.pagination.total})
            </h3>
            {products.pagination.total > 12 && (
              <Link
                href={`/products?shop_id=${encodeURIComponent(shopId)}`}
                className="text-sm text-[hsl(var(--primary))] hover:underline"
              >
                View all products
              </Link>
            )}
          </div>
          <ProductGrid products={products.data} />
        </div>
      )}
    </div>
  );
}
