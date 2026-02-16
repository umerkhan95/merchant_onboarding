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
  vendor: string | null;
  product_type: string | null;
  in_stock: boolean;
  variants: Variant[];
  tags: string[];
  scraped_at: string;
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
