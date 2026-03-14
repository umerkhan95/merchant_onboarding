"""SQL queries for product database operations."""

from __future__ import annotations

# Schema creation
CREATE_PRODUCTS_TABLE = """
CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    external_id TEXT NOT NULL,
    shop_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    price NUMERIC(12,2) NOT NULL,
    compare_at_price NUMERIC(12,2),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    image_url TEXT DEFAULT '',
    product_url TEXT DEFAULT '',
    sku TEXT,
    gtin TEXT,
    mpn TEXT,
    vendor TEXT,
    product_type TEXT,
    in_stock BOOLEAN DEFAULT TRUE,
    condition TEXT,
    variants JSONB DEFAULT '[]',
    tags JSONB DEFAULT '[]',
    additional_images JSONB DEFAULT '[]',
    category_path JSONB DEFAULT '[]',
    raw_data JSONB DEFAULT '{}',
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retention_expires_at TIMESTAMPTZ,
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_products_shop_id ON products(shop_id);
CREATE INDEX IF NOT EXISTS idx_products_platform ON products(platform);
CREATE INDEX IF NOT EXISTS idx_products_idempotency ON products(idempotency_key);
"""

# Staging table for bulk operations (INCLUDING DEFAULTS only — no constraints/indexes
# so COPY can load data without ON CONFLICT overhead; dedup handled by final upsert)
CREATE_STAGING_TABLE = """
CREATE TEMP TABLE IF NOT EXISTS staging_products (LIKE products INCLUDING DEFAULTS) ON COMMIT DROP;
"""

# Bulk upsert from staging
UPSERT_FROM_STAGING = """
INSERT INTO products (
    external_id, shop_id, platform, title, description, price, compare_at_price,
    currency, image_url, product_url, sku, gtin, mpn, vendor, product_type, in_stock,
    condition, variants, tags, additional_images, category_path,
    raw_data, scraped_at, idempotency_key, retention_expires_at
)
SELECT
    external_id, shop_id, platform, title, description, price, compare_at_price,
    currency, image_url, product_url, sku, gtin, mpn, vendor, product_type, in_stock,
    condition, variants, tags, additional_images, category_path,
    raw_data, scraped_at, idempotency_key, retention_expires_at
FROM staging_products
ON CONFLICT (idempotency_key)
DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    price = EXCLUDED.price,
    compare_at_price = EXCLUDED.compare_at_price,
    image_url = EXCLUDED.image_url,
    product_url = EXCLUDED.product_url,
    sku = EXCLUDED.sku,
    gtin = EXCLUDED.gtin,
    mpn = EXCLUDED.mpn,
    vendor = EXCLUDED.vendor,
    product_type = EXCLUDED.product_type,
    currency = EXCLUDED.currency,
    in_stock = EXCLUDED.in_stock,
    condition = EXCLUDED.condition,
    variants = EXCLUDED.variants,
    tags = EXCLUDED.tags,
    additional_images = EXCLUDED.additional_images,
    category_path = EXCLUDED.category_path,
    raw_data = EXCLUDED.raw_data,
    scraped_at = EXCLUDED.scraped_at,
    updated_at = NOW();
"""

# Read operations
SELECT_PRODUCTS_BY_SHOP = """
SELECT * FROM products WHERE shop_id = $1 ORDER BY (price > 0) DESC, created_at DESC LIMIT $2 OFFSET $3;
"""

SELECT_PRODUCTS_BY_DOMAIN = """
SELECT * FROM products
WHERE shop_id LIKE '%' || $1 || '%'
ORDER BY (price > 0) DESC, created_at DESC LIMIT $2 OFFSET $3;
"""

COUNT_PRODUCTS_BY_SHOP = """
SELECT COUNT(*) FROM products WHERE shop_id = $1;
"""

COUNT_PRODUCTS_BY_DOMAIN = """
SELECT COUNT(*) FROM products WHERE shop_id LIKE '%' || $1 || '%';
"""

SELECT_PRODUCT_BY_ID = """
SELECT * FROM products WHERE id = $1;
"""

COUNT_ALL_PRODUCTS = """
SELECT COUNT(*) FROM products;
"""

# Cleanup: remove invalid products (price=0, no image, no SKU, no external_id)
# Preserves legitimate free items that have images or SKUs.
DELETE_INVALID_PRODUCTS = """
DELETE FROM products
WHERE price = 0
  AND (image_url IS NULL OR image_url = '')
  AND (sku IS NULL OR sku = '')
  AND (external_id IS NULL OR external_id = '');
"""

# Count invalid products (for dry-run / preview)
COUNT_INVALID_PRODUCTS = """
SELECT COUNT(*) FROM products
WHERE price = 0
  AND (image_url IS NULL OR image_url = '')
  AND (sku IS NULL OR sku = '')
  AND (external_id IS NULL OR external_id = '');
"""

# --- Merchant Profiles ---

CREATE_MERCHANT_PROFILES_TABLE = """
CREATE TABLE IF NOT EXISTS merchant_profiles (
    id BIGSERIAL PRIMARY KEY,
    shop_id TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL,
    shop_url TEXT NOT NULL,

    -- Business identity
    company_name TEXT,
    logo_url TEXT,
    description TEXT,
    about_text TEXT,
    founding_year INTEGER,
    industry TEXT,
    language VARCHAR(10),
    currency VARCHAR(3),

    -- Contact (structured JSONB)
    contact JSONB DEFAULT '{}',

    -- Social links
    social_links JSONB DEFAULT '{}',

    -- Analytics/tracking tags
    analytics_tags JSONB DEFAULT '[]',

    -- Metadata
    favicon_url TEXT,
    pages_crawled JSONB DEFAULT '[]',
    extraction_confidence NUMERIC(3,2) DEFAULT 0.0,

    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retention_expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_merchant_profiles_shop_id
    ON merchant_profiles(shop_id);
"""

UPSERT_MERCHANT_PROFILE = """
INSERT INTO merchant_profiles (
    shop_id, platform, shop_url, company_name, logo_url, description,
    about_text, founding_year, industry, language, currency,
    contact, social_links, analytics_tags,
    favicon_url, pages_crawled, extraction_confidence, scraped_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
    $12, $13, $14, $15, $16, $17, $18
)
ON CONFLICT (shop_id) DO UPDATE SET
    platform = EXCLUDED.platform,
    shop_url = EXCLUDED.shop_url,
    company_name = EXCLUDED.company_name,
    logo_url = EXCLUDED.logo_url,
    description = EXCLUDED.description,
    about_text = EXCLUDED.about_text,
    founding_year = EXCLUDED.founding_year,
    industry = EXCLUDED.industry,
    language = EXCLUDED.language,
    currency = EXCLUDED.currency,
    contact = EXCLUDED.contact,
    social_links = EXCLUDED.social_links,
    analytics_tags = EXCLUDED.analytics_tags,
    favicon_url = EXCLUDED.favicon_url,
    pages_crawled = EXCLUDED.pages_crawled,
    extraction_confidence = EXCLUDED.extraction_confidence,
    scraped_at = EXCLUDED.scraped_at,
    updated_at = NOW();
"""

SELECT_MERCHANT_PROFILE = """
SELECT * FROM merchant_profiles WHERE shop_id = $1;
"""

SELECT_ALL_MERCHANT_PROFILES = """
SELECT * FROM merchant_profiles ORDER BY updated_at DESC;
"""

# GDPR: Delete all products for a merchant
DELETE_PRODUCTS_BY_SHOP = """
DELETE FROM products WHERE shop_id = $1;
"""

COUNT_PRODUCTS_BY_SHOP_FOR_DELETE = """
SELECT COUNT(*) FROM products WHERE shop_id = $1;
"""

# GDPR: Delete merchant profile
DELETE_MERCHANT_PROFILE = """
DELETE FROM merchant_profiles WHERE shop_id = $1;
"""

# GDPR: Data retention — add retention column
ALTER_PRODUCTS_ADD_RETENTION = """
ALTER TABLE products ADD COLUMN IF NOT EXISTS retention_expires_at TIMESTAMPTZ;
"""

ALTER_PROFILES_ADD_RETENTION = """
ALTER TABLE merchant_profiles ADD COLUMN IF NOT EXISTS retention_expires_at TIMESTAMPTZ;
"""

# GDPR: Delete expired records
DELETE_EXPIRED_PRODUCTS = """
DELETE FROM products
WHERE retention_expires_at IS NOT NULL
  AND retention_expires_at < NOW();
"""

DELETE_EXPIRED_PROFILES = """
DELETE FROM merchant_profiles
WHERE retention_expires_at IS NOT NULL
  AND retention_expires_at < NOW();
"""

COUNT_EXPIRED_PRODUCTS = """
SELECT COUNT(*) FROM products
WHERE retention_expires_at IS NOT NULL
  AND retention_expires_at < NOW();
"""

COUNT_EXPIRED_PROFILES = """
SELECT COUNT(*) FROM merchant_profiles
WHERE retention_expires_at IS NOT NULL
  AND retention_expires_at < NOW();
"""

# Set retention on existing records that don't have one
SET_DEFAULT_RETENTION_PRODUCTS = """
UPDATE products
SET retention_expires_at = created_at + ($1 || ' days')::INTERVAL
WHERE retention_expires_at IS NULL;
"""

SET_DEFAULT_RETENTION_PROFILES = """
UPDATE merchant_profiles
SET retention_expires_at = created_at + ($1 || ' days')::INTERVAL
WHERE retention_expires_at IS NULL;
"""

# --- OAuth Connections ---

CREATE_OAUTH_CONNECTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS oauth_connections (
    id BIGSERIAL PRIMARY KEY,
    platform VARCHAR(50) NOT NULL,
    shop_domain VARCHAR(255) NOT NULL,
    access_token_encrypted BYTEA,
    refresh_token_encrypted BYTEA,
    token_expires_at TIMESTAMPTZ,
    scopes TEXT,
    consumer_key_encrypted BYTEA,
    consumer_secret_encrypted BYTEA,
    access_token_secret_encrypted BYTEA,
    store_hash VARCHAR(100),
    extra_data JSONB DEFAULT '{}',
    connected_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'active',
    UNIQUE(platform, shop_domain)
);
CREATE INDEX IF NOT EXISTS idx_oauth_connections_domain ON oauth_connections(shop_domain);
CREATE INDEX IF NOT EXISTS idx_oauth_connections_platform ON oauth_connections(platform);
"""

UPSERT_OAUTH_CONNECTION = """
INSERT INTO oauth_connections (
    platform, shop_domain, access_token_encrypted,
    refresh_token_encrypted, token_expires_at, scopes,
    consumer_key_encrypted, consumer_secret_encrypted,
    access_token_secret_encrypted, store_hash, extra_data, status
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'active')
ON CONFLICT (platform, shop_domain) DO UPDATE SET
    access_token_encrypted = EXCLUDED.access_token_encrypted,
    refresh_token_encrypted = EXCLUDED.refresh_token_encrypted,
    token_expires_at = EXCLUDED.token_expires_at,
    scopes = EXCLUDED.scopes,
    consumer_key_encrypted = EXCLUDED.consumer_key_encrypted,
    consumer_secret_encrypted = EXCLUDED.consumer_secret_encrypted,
    access_token_secret_encrypted = EXCLUDED.access_token_secret_encrypted,
    store_hash = EXCLUDED.store_hash,
    extra_data = EXCLUDED.extra_data,
    status = 'active',
    connected_at = NOW();
"""

SELECT_OAUTH_CONNECTION = """
SELECT * FROM oauth_connections
WHERE platform = $1 AND shop_domain = $2 AND status = 'active';
"""

SELECT_OAUTH_CONNECTION_BY_DOMAIN = """
SELECT * FROM oauth_connections
WHERE shop_domain = $1 AND status = 'active';
"""

SELECT_ALL_OAUTH_CONNECTIONS = """
SELECT id, platform, shop_domain, scopes, store_hash,
       connected_at, last_used_at, status
FROM oauth_connections
ORDER BY connected_at DESC;
"""

DELETE_OAUTH_CONNECTION = """
UPDATE oauth_connections SET status = 'revoked'
WHERE platform = $1 AND shop_domain = $2;
"""

UPDATE_OAUTH_LAST_USED = """
UPDATE oauth_connections SET last_used_at = NOW()
WHERE platform = $1 AND shop_domain = $2;
"""

# Migration: add idealo-required columns to existing products table
ALTER_PRODUCTS_ADD_IDEALO_FIELDS = """
ALTER TABLE products ADD COLUMN IF NOT EXISTS gtin TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS mpn TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS condition TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS additional_images JSONB DEFAULT '[]';
ALTER TABLE products ADD COLUMN IF NOT EXISTS category_path JSONB DEFAULT '[]';
"""

# --- Product Updates ---

UPDATE_PRODUCT = """
UPDATE products
SET {set_clause},
    updated_at = NOW()
WHERE id = $1
RETURNING *;
"""

UPDATE_PRODUCTS_BULK = """
UPDATE products
SET {set_clause},
    updated_at = NOW()
WHERE shop_id = $1 AND ({match_clause})
RETURNING id, external_id, sku;
"""

# --- Merchant Settings ---

CREATE_MERCHANT_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS merchant_settings (
    id BIGSERIAL PRIMARY KEY,
    shop_id TEXT NOT NULL UNIQUE,
    delivery_time TEXT DEFAULT '',
    delivery_costs TEXT DEFAULT '',
    payment_costs TEXT DEFAULT '',
    brand_fallback TEXT DEFAULT '',
    default_condition TEXT DEFAULT 'NEW',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_merchant_settings_shop_id ON merchant_settings(shop_id);
"""

UPSERT_MERCHANT_SETTINGS = """
INSERT INTO merchant_settings (
    shop_id, delivery_time, delivery_costs, payment_costs,
    brand_fallback, default_condition
) VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (shop_id) DO UPDATE SET
    delivery_time = EXCLUDED.delivery_time,
    delivery_costs = EXCLUDED.delivery_costs,
    payment_costs = EXCLUDED.payment_costs,
    brand_fallback = EXCLUDED.brand_fallback,
    default_condition = EXCLUDED.default_condition,
    updated_at = NOW()
RETURNING *;
"""

SELECT_MERCHANT_SETTINGS = """
SELECT * FROM merchant_settings WHERE shop_id = $1;
"""

# --- Product Completeness ---

SELECT_PRODUCT_COMPLETENESS = """
SELECT id, title, sku, external_id, gtin, vendor, mpn, condition,
       image_url, product_url, price, description, category_path
FROM products
WHERE shop_id = $1
ORDER BY created_at DESC
LIMIT $2 OFFSET $3;
"""

SELECT_PRODUCT_COMPLETENESS_BY_DOMAIN = """
SELECT id, title, sku, external_id, gtin, vendor, mpn, condition,
       image_url, product_url, price, description, category_path
FROM products
WHERE shop_id LIKE '%' || $1 || '%'
ORDER BY created_at DESC
LIMIT $2 OFFSET $3;
"""

COUNT_PRODUCTS_MISSING_FIELD = """
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE gtin IS NOT NULL AND gtin != '') AS has_gtin,
    COUNT(*) FILTER (WHERE vendor IS NOT NULL AND vendor != '') AS has_brand,
    COUNT(*) FILTER (WHERE mpn IS NOT NULL AND mpn != '') AS has_mpn,
    COUNT(*) FILTER (WHERE condition IS NOT NULL AND condition != '') AS has_condition,
    COUNT(*) FILTER (WHERE image_url IS NOT NULL AND image_url != '') AS has_image,
    COUNT(*) FILTER (WHERE description IS NOT NULL AND description != '') AS has_description,
    COUNT(*) FILTER (WHERE category_path IS NOT NULL AND category_path != '[]'::jsonb) AS has_category
FROM products
WHERE shop_id = $1;
"""

COUNT_PRODUCTS_MISSING_FIELD_BY_DOMAIN = """
SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE gtin IS NOT NULL AND gtin != '') AS has_gtin,
    COUNT(*) FILTER (WHERE vendor IS NOT NULL AND vendor != '') AS has_brand,
    COUNT(*) FILTER (WHERE mpn IS NOT NULL AND mpn != '') AS has_mpn,
    COUNT(*) FILTER (WHERE condition IS NOT NULL AND condition != '') AS has_condition,
    COUNT(*) FILTER (WHERE image_url IS NOT NULL AND image_url != '') AS has_image,
    COUNT(*) FILTER (WHERE description IS NOT NULL AND description != '') AS has_description,
    COUNT(*) FILTER (WHERE category_path IS NOT NULL AND category_path != '[]'::jsonb) AS has_category
FROM products
WHERE shop_id LIKE '%' || $1 || '%';
"""

SELECT_MERCHANT_SETTINGS_BY_DOMAIN = """
SELECT * FROM merchant_settings WHERE shop_id LIKE '%' || $1 || '%';
"""
