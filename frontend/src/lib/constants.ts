export const PIPELINE_STEPS = [
  { key: "queued", label: "Queued" },
  { key: "detecting", label: "Detecting Platform" },
  { key: "discovering", label: "Discovering URLs" },
  { key: "extracting", label: "Extracting Products" },
  { key: "normalizing", label: "Normalizing Data" },
  { key: "ingesting", label: "Ingesting to DB" },
  { key: "completed", label: "Completed" },
] as const;

export const STATUS_COLORS: Record<string, string> = {
  queued: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  detecting: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  discovering: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  extracting: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300",
  normalizing: "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300",
  ingesting: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300",
  completed: "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300",
  failed: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
  needs_review: "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300",
};

export const PLATFORM_COLORS: Record<string, string> = {
  shopify: "#96BF48",
  woocommerce: "#7B51AD",
  magento: "#F26322",
  bigcommerce: "#34313F",
  generic: "#6B7280",
};

export const TIER_LABELS: Record<string, string> = {
  api: "Platform API",
  schema_org: "Schema.org",
  opengraph: "OpenGraph",
  smart_css: "Smart CSS",
  llm: "LLM",
  deep_crawl: "CSS Crawl",
  sitemap_css: "Sitemap CSS",
};

export const CHART_COLORS = [
  "#3B82F6",
  "#10B981",
  "#F59E0B",
  "#EF4444",
  "#8B5CF6",
  "#EC4899",
  "#06B6D4",
];
