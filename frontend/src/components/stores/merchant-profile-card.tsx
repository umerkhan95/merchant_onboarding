"use client";

import type { MerchantProfile } from "@/lib/types";
import { PLATFORM_COLORS } from "@/lib/constants";

interface MerchantProfileCardProps {
  profile: MerchantProfile;
}

function SocialLink({ name, url }: { name: string; url: string | null }) {
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--border))] px-3 py-1 text-xs font-medium text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors capitalize"
    >
      {name}
    </a>
  );
}

function InfoRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (!value) return null;
  return (
    <div className="flex justify-between py-2 border-b border-[hsl(var(--border))] last:border-b-0">
      <span className="text-sm text-[hsl(var(--muted-foreground))]">{label}</span>
      <span className="text-sm font-medium text-[hsl(var(--foreground))]">{value}</span>
    </div>
  );
}

export function MerchantProfileCard({ profile }: MerchantProfileCardProps) {
  const domain = profile.shop_url
    ? new URL(profile.shop_url.startsWith("http") ? profile.shop_url : `https://${profile.shop_url}`).hostname.replace("www.", "")
    : profile.shop_id;

  const platformColor = PLATFORM_COLORS[profile.platform] || PLATFORM_COLORS.generic;

  const socialLinks = profile.social_links || {};
  const hasSocials = Object.values(socialLinks).some((v) => v);
  const contact = profile.contact || {};
  const hasContact = contact.email || contact.phone || contact.address;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-4">
        {profile.logo_url ? (
          <img
            src={profile.logo_url}
            alt={profile.company_name || domain}
            className="h-16 w-16 rounded-xl object-contain bg-white border border-[hsl(var(--border))] p-1"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        ) : profile.favicon_url ? (
          <img
            src={profile.favicon_url}
            alt=""
            className="h-16 w-16 rounded-xl object-contain bg-white border border-[hsl(var(--border))] p-2"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-[hsl(var(--muted))] text-2xl font-bold text-[hsl(var(--muted-foreground))]">
            {(profile.company_name || domain).charAt(0).toUpperCase()}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-bold text-[hsl(var(--foreground))]">
            {profile.company_name || domain}
          </h2>
          <a
            href={profile.shop_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-[hsl(var(--primary))] hover:underline"
          >
            {domain}
          </a>
          <div className="mt-2 flex items-center gap-2">
            <span
              className="inline-block rounded-full px-2.5 py-0.5 text-xs font-medium text-white capitalize"
              style={{ backgroundColor: platformColor }}
            >
              {profile.platform}
            </span>
            <span className="text-xs text-[hsl(var(--muted-foreground))]">
              Confidence: {Math.round(profile.extraction_confidence * 100)}%
            </span>
          </div>
        </div>
      </div>

      {/* Description */}
      {profile.description && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <h3 className="mb-2 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
            Description
          </h3>
          <p className="text-sm text-[hsl(var(--foreground))] leading-relaxed">
            {profile.description}
          </p>
        </div>
      )}

      {/* About */}
      {profile.about_text && profile.about_text !== profile.description && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <h3 className="mb-2 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
            About
          </h3>
          <p className="text-sm text-[hsl(var(--foreground))] leading-relaxed line-clamp-6">
            {profile.about_text}
          </p>
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {/* Business Details */}
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <h3 className="mb-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
            Business Details
          </h3>
          <div className="space-y-0">
            <InfoRow label="Industry" value={profile.industry} />
            <InfoRow label="Founded" value={profile.founding_year} />
            <InfoRow label="Language" value={profile.language} />
            <InfoRow label="Currency" value={profile.currency} />
          </div>
        </div>

        {/* Contact */}
        {hasContact && (
          <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
            <h3 className="mb-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
              Contact
            </h3>
            <div className="space-y-0">
              <InfoRow label="Email" value={contact.email} />
              <InfoRow label="Phone" value={contact.phone} />
              <InfoRow label="Address" value={contact.address} />
            </div>
          </div>
        )}
      </div>

      {/* Social Links */}
      {hasSocials && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <h3 className="mb-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
            Social Links
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(socialLinks).map(([name, url]) => (
              <SocialLink key={name} name={name} url={url} />
            ))}
          </div>
        </div>
      )}

      {/* Analytics Tags */}
      {profile.analytics_tags && profile.analytics_tags.length > 0 && (
        <div className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
          <h3 className="mb-3 text-xs font-medium tracking-wide uppercase text-[hsl(var(--muted-foreground))]">
            Analytics Tags
          </h3>
          <div className="flex flex-wrap gap-2">
            {profile.analytics_tags.map((tag, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1.5 rounded-full bg-[hsl(var(--muted))] px-3 py-1 text-xs font-mono"
              >
                <span className="font-medium text-[hsl(var(--foreground))]">{tag.provider}</span>
                <span className="text-[hsl(var(--muted-foreground))]">{tag.tag_id}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
