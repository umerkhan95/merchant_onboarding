export interface RecentProduct {
  title: string;
  price: string | number;
  image_url: string;
}

export interface ExtractionAudit {
  urls_success: number;
  urls_empty: number;
  urls_error: number;
  urls_not_product: number;
  total_products: number;
}

export interface JobProgress {
  job_id: string;
  processed: number;
  total: number;
  percentage: number;
  status: string;
  current_step: string;
  error?: string | null;
  shop_url?: string;
  platform?: string;
  extraction_tier?: string;
  products_count?: number;
  started_at?: string;
  completed_at?: string;
  recent_products?: RecentProduct[] | null;
  extraction_audit?: ExtractionAudit | null;
  coverage_percentage?: number | null;
}

export interface JobSummary {
  job_id: string;
  shop_url?: string | null;
  platform?: string | null;
  status: string;
  extraction_tier?: string | null;
  products_count: number;
  started_at?: string | null;
  completed_at?: string | null;
  current_step: string;
  error?: string | null;
}

export interface JobListResponse {
  jobs: JobSummary[];
  total: number;
}

export interface OnboardingResponse {
  job_id: string;
  status: string;
  progress_url: string;
}

export interface StatusCount {
  status: string;
  count: number;
}

export interface PlatformCount {
  platform: string;
  count: number;
}

export interface TierCount {
  tier: string;
  count: number;
}

export interface AnalyticsSummary {
  total_jobs: number;
  total_products: number;
  success_rate: number;
  avg_duration_seconds: number | null;
  jobs_by_status: StatusCount[];
  jobs_by_platform: PlatformCount[];
  jobs_by_tier: TierCount[];
}

export interface Variant {
  title: string;
  price: number;
  sku?: string | null;
  in_stock?: boolean;
}

export interface Product {
  id: number;
  external_id: string;
  shop_id: string;
  platform: string;
  title: string;
  description: string;
  price: number;
  compare_at_price: number | null;
  currency: string;
  image_url: string;
  product_url: string;
  sku: string | null;
  gtin: string | null;
  mpn: string | null;
  vendor: string | null;
  product_type: string | null;
  in_stock: boolean;
  condition: string | null;
  variants: Variant[];
  tags: string[];
  category_path: string[];
  scraped_at: string;
}

export interface MerchantSettings {
  shop_id: string;
  delivery_time: string;
  delivery_costs: string;
  payment_costs: string;
  brand_fallback: string;
  default_condition: string;
}

export interface MerchantSettingsResponse {
  shop_id: string;
  settings: MerchantSettings | null;
}

export interface CompletenessProduct {
  id: number;
  title: string;
  sku: string;
  score: number;
  missing_fields: string[];
  idealo_ready: boolean;
}

export interface FieldCoverage {
  present: number;
  missing: number;
  coverage_pct: number;
}

export interface CompletenessSummary {
  total: number;
  fields: Record<string, FieldCoverage>;
  idealo_ready?: number;
  idealo_ready_pct?: number;
}

export interface CompletenessResponse {
  products: CompletenessProduct[];
  summary: CompletenessSummary;
  shop_id: string;
}

export interface ValidationResponse {
  shop_id: string;
  ready: boolean;
  issues: string[];
  warnings: string[];
  issue_count: number;
  warning_count: number;
}

export interface PaginationMeta {
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
}

export interface ProductListResponse {
  data: Product[];
  pagination: PaginationMeta;
  shop_id: string;
}

export interface ContactInfo {
  email: string | null;
  phone: string | null;
  address: string | null;
}

export interface SocialLinks {
  facebook: string | null;
  instagram: string | null;
  twitter: string | null;
  youtube: string | null;
  tiktok: string | null;
  pinterest: string | null;
  linkedin: string | null;
}

export interface AnalyticsTag {
  provider: string;
  tag_id: string;
}

export interface MerchantProfile {
  id: number;
  shop_id: string;
  platform: string;
  shop_url: string;
  company_name: string | null;
  logo_url: string | null;
  description: string | null;
  about_text: string | null;
  founding_year: number | null;
  industry: string | null;
  language: string | null;
  currency: string | null;
  contact: ContactInfo;
  social_links: SocialLinks;
  analytics_tags: AnalyticsTag[];
  favicon_url: string | null;
  pages_crawled: string[];
  extraction_confidence: number;
  scraped_at: string;
  created_at: string;
  updated_at: string;
}

export interface EndpointPerf {
  endpoint: string;
  method: string;
  count: number;
  avg_ms: number;
  p95_ms: number;
}

export interface PerfStats {
  total_requests: number;
  requests_per_minute: number;
  error_rate: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  uptime_seconds: number;
  endpoints: EndpointPerf[];
}

export interface TierPerf {
  tier: string;
  jobs: number;
  avg_duration_seconds: number;
  avg_products: number;
  products_per_second: number;
}

export interface CrawlJobPerf {
  job_id: string;
  shop_url: string;
  platform: string;
  tier: string;
  products: number;
  duration_seconds: number;
  products_per_second: number;
}

export interface CrawlerStats {
  by_tier: TierPerf[];
  recent_crawls: CrawlJobPerf[];
  total_crawl_time_seconds: number;
  avg_products_per_second: number;
}
