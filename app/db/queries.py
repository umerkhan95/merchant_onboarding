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

# --- RBAC & Auth Tables ---

CREATE_MERCHANT_ACCOUNTS_TABLE = """
CREATE TABLE IF NOT EXISTS merchant_accounts (
    id UUID PRIMARY KEY,
    email_hash TEXT NOT NULL UNIQUE,
    email_encrypted BYTEA NOT NULL,
    password_hash TEXT NOT NULL,
    account_status VARCHAR(20) NOT NULL DEFAULT 'active',
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_merchant_accounts_email_hash ON merchant_accounts(email_hash);
"""

CREATE_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

SEED_ROLES = """
INSERT INTO roles (name, description) VALUES
    ('admin', 'Full system access'),
    ('merchant', 'Standard merchant access'),
    ('viewer', 'Read-only access')
ON CONFLICT (name) DO NOTHING;
"""

CREATE_PERMISSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS permissions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(100) NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

SEED_PERMISSIONS = """
INSERT INTO permissions (code, description) VALUES
    ('products:read', 'View products'),
    ('products:write', 'Create/update products'),
    ('products:delete', 'Delete products'),
    ('exports:read', 'View/download exports'),
    ('exports:write', 'Create exports'),
    ('settings:read', 'View merchant settings'),
    ('settings:write', 'Update merchant settings'),
    ('oauth:read', 'View OAuth connections'),
    ('oauth:write', 'Manage OAuth connections'),
    ('onboard:write', 'Start onboarding jobs'),
    ('onboard:read', 'View onboarding status'),
    ('analytics:read', 'View analytics'),
    ('api_keys:manage', 'Create/revoke API keys'),
    ('admin:manage', 'Full admin access')
ON CONFLICT (code) DO NOTHING;
"""

CREATE_ROLE_PERMISSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);
"""

SEED_ROLE_PERMISSIONS = """
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'merchant' AND p.code NOT IN ('admin:manage', 'products:delete')
ON CONFLICT DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'viewer' AND p.code IN ('products:read', 'exports:read', 'settings:read', 'oauth:read', 'onboard:read', 'analytics:read')
ON CONFLICT DO NOTHING;
"""

CREATE_MERCHANT_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS merchant_roles (
    merchant_id UUID NOT NULL REFERENCES merchant_accounts(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (merchant_id, role_id)
);
"""

CREATE_API_KEYS_TABLE = """
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY,
    merchant_id UUID NOT NULL REFERENCES merchant_accounts(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix VARCHAR(12) NOT NULL,
    name VARCHAR(100) NOT NULL DEFAULT '',
    scopes TEXT DEFAULT '',
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_api_keys_merchant ON api_keys(merchant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
"""

CREATE_REFRESH_TOKENS_TABLE = """
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY,
    merchant_id UUID NOT NULL REFERENCES merchant_accounts(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    token_family UUID NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    user_agent TEXT DEFAULT '',
    ip_address VARCHAR(45) DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_merchant ON refresh_tokens(merchant_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_family ON refresh_tokens(token_family);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires ON refresh_tokens(expires_at)
    WHERE revoked = FALSE;
"""

CREATE_AUDIT_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    merchant_id UUID,
    event_type VARCHAR(100) NOT NULL,
    ip_address VARCHAR(45) DEFAULT '',
    user_agent TEXT DEFAULT '',
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_merchant ON audit_log(merchant_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_event ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
"""

# --- Merchant Account DML ---

INSERT_MERCHANT_ACCOUNT = """
INSERT INTO merchant_accounts (id, email_hash, email_encrypted, password_hash)
VALUES ($1, $2, $3, $4)
RETURNING id, account_status, created_at;
"""

SELECT_MERCHANT_BY_EMAIL_HASH = """
SELECT * FROM merchant_accounts WHERE email_hash = $1;
"""

SELECT_MERCHANT_BY_ID = """
SELECT * FROM merchant_accounts WHERE id = $1;
"""

UPDATE_MERCHANT_FAILED_LOGIN = """
UPDATE merchant_accounts
SET failed_login_attempts = failed_login_attempts + 1,
    locked_until = CASE
        WHEN failed_login_attempts + 1 >= $2
        THEN NOW() + ($3 || ' minutes')::INTERVAL
        ELSE locked_until
    END,
    updated_at = NOW()
WHERE id = $1;
"""

RESET_MERCHANT_FAILED_LOGIN = """
UPDATE merchant_accounts
SET failed_login_attempts = 0, locked_until = NULL, updated_at = NOW()
WHERE id = $1;
"""

# --- Merchant Roles DML ---

INSERT_MERCHANT_ROLE = """
INSERT INTO merchant_roles (merchant_id, role_id)
SELECT $1, id FROM roles WHERE name = $2
ON CONFLICT DO NOTHING;
"""

SELECT_MERCHANT_PERMISSIONS = """
SELECT DISTINCT p.code
FROM merchant_roles mr
JOIN role_permissions rp ON rp.role_id = mr.role_id
JOIN permissions p ON p.id = rp.permission_id
WHERE mr.merchant_id = $1;
"""

# --- API Keys DML ---

INSERT_API_KEY = """
INSERT INTO api_keys (id, merchant_id, key_hash, key_prefix, name, scopes, expires_at)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING id, key_prefix, name, scopes, expires_at, created_at;
"""

SELECT_API_KEY_BY_HASH = """
SELECT ak.*, ma.account_status
FROM api_keys ak
JOIN merchant_accounts ma ON ma.id = ak.merchant_id
WHERE ak.key_hash = $1 AND ak.revoked = FALSE
  AND (ak.expires_at IS NULL OR ak.expires_at > NOW());
"""

SELECT_API_KEYS_BY_MERCHANT = """
SELECT id, key_prefix, name, scopes, expires_at, last_used_at, revoked, created_at
FROM api_keys
WHERE merchant_id = $1
ORDER BY created_at DESC;
"""

REVOKE_API_KEY = """
UPDATE api_keys SET revoked = TRUE WHERE id = $1 AND merchant_id = $2;
"""

UPDATE_API_KEY_LAST_USED = """
UPDATE api_keys SET last_used_at = NOW() WHERE id = $1;
"""

# --- Refresh Tokens DML ---

INSERT_REFRESH_TOKEN = """
INSERT INTO refresh_tokens (id, merchant_id, token_hash, token_family, expires_at, user_agent, ip_address)
VALUES ($1, $2, $3, $4, $5, $6, $7);
"""

SELECT_REFRESH_TOKEN_BY_HASH = """
SELECT * FROM refresh_tokens WHERE token_hash = $1;
"""

REVOKE_REFRESH_TOKEN = """
UPDATE refresh_tokens SET revoked = TRUE WHERE id = $1;
"""

REVOKE_REFRESH_TOKEN_FAMILY = """
UPDATE refresh_tokens SET revoked = TRUE WHERE token_family = $1;
"""

REVOKE_ALL_MERCHANT_REFRESH_TOKENS = """
UPDATE refresh_tokens SET revoked = TRUE WHERE merchant_id = $1;
"""

SELECT_ACTIVE_SESSIONS = """
SELECT id, token_family, user_agent, ip_address, created_at, expires_at
FROM refresh_tokens
WHERE merchant_id = $1 AND revoked = FALSE AND expires_at > NOW()
ORDER BY created_at DESC;
"""

# --- Audit Log DML ---

INSERT_AUDIT_LOG = """
INSERT INTO audit_log (merchant_id, event_type, ip_address, user_agent, details)
VALUES ($1, $2, $3, $4, $5);
"""
