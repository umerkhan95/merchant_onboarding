from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import v1_router
from app.config import settings
from app.db.queries import (
    ALTER_PRODUCTS_ADD_IDEALO_FIELDS,
    CREATE_API_KEYS_TABLE,
    CREATE_AUDIT_LOG_TABLE,
    CREATE_MERCHANT_ACCOUNTS_TABLE,
    CREATE_MERCHANT_PROFILES_TABLE,
    CREATE_MERCHANT_ROLES_TABLE,
    CREATE_MERCHANT_SETTINGS_TABLE,
    CREATE_OAUTH_CONNECTIONS_TABLE,
    CREATE_PERMISSIONS_TABLE,
    CREATE_PRODUCTS_TABLE,
    CREATE_REFRESH_TOKENS_TABLE,
    CREATE_ROLE_PERMISSIONS_TABLE,
    CREATE_ROLES_TABLE,
    SEED_PERMISSIONS,
    SEED_ROLE_PERMISSIONS,
    SEED_ROLES,
)
from app.db.supabase_client import DatabaseClient
from app.exceptions.handlers import register_exception_handlers
from app.infra.perf_middleware import PerfMiddleware
from app.infra.security_headers import SecurityHeadersMiddleware
from app.api.deps import limiter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup — Redis
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    # Startup — PostgreSQL (retry up to 5 times with exponential backoff)
    db: DatabaseClient | None = None
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            db = DatabaseClient(settings.database_url)
            await db.connect()
            async with db.pool.acquire() as conn:
                # Non-RBAC tables (no inter-dependencies)
                await conn.execute(CREATE_PRODUCTS_TABLE)
                await conn.execute(ALTER_PRODUCTS_ADD_IDEALO_FIELDS)
                await conn.execute(CREATE_MERCHANT_PROFILES_TABLE)
                await conn.execute(CREATE_OAUTH_CONNECTIONS_TABLE)
                await conn.execute(CREATE_MERCHANT_SETTINGS_TABLE)
                # RBAC tables + seed data in a transaction so partial seed
                # failures don't leave the schema in an inconsistent state.
                # CREATE TABLE IF NOT EXISTS is idempotent, and all SEED
                # statements use ON CONFLICT DO NOTHING, so re-runs are safe.
                async with conn.transaction():
                    # 1. Independent tables (no FKs to other RBAC tables)
                    await conn.execute(CREATE_MERCHANT_ACCOUNTS_TABLE)
                    await conn.execute(CREATE_ROLES_TABLE)
                    await conn.execute(CREATE_PERMISSIONS_TABLE)
                    # 2. Seed reference data
                    await conn.execute(SEED_ROLES)
                    await conn.execute(SEED_PERMISSIONS)
                    # 3. FK-dependent tables
                    await conn.execute(CREATE_ROLE_PERMISSIONS_TABLE)
                    await conn.execute(SEED_ROLE_PERMISSIONS)
                    await conn.execute(CREATE_MERCHANT_ROLES_TABLE)
                    await conn.execute(CREATE_API_KEYS_TABLE)
                    await conn.execute(CREATE_REFRESH_TOKENS_TABLE)
                    await conn.execute(CREATE_AUDIT_LOG_TABLE)
            logger.info("PostgreSQL connected and tables ensured")
            break
        except Exception:
            if attempt < max_retries:
                delay = min(2 ** attempt, 30)
                logger.warning(
                    "PostgreSQL connection attempt %d/%d failed, retrying in %ds",
                    attempt, max_retries, delay, exc_info=True,
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(
                    "PostgreSQL not available after %d attempts — running without database",
                    max_retries, exc_info=True,
                )
                db = None
    app.state.db = db

    yield

    # Shutdown
    if app.state.db is not None:
        await app.state.db.close()
    await app.state.redis.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["X-API-Key", "Authorization", "Content-Type"],
    )

    if settings.jwt_secret_key == "change-me-in-production":
        logger.warning("JWT_SECRET_KEY is using default value — change in production!")

    app.state.limiter = limiter
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(PerfMiddleware)
    app.include_router(v1_router, prefix="/api/v1")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "healthy"}

    @app.get("/readiness")
    async def readiness() -> dict:
        checks: dict[str, bool] = {}

        # Check Redis
        try:
            await app.state.redis.ping()
            checks["redis"] = True
        except Exception:
            checks["redis"] = False

        # Check PostgreSQL
        try:
            if app.state.db is not None:
                async with app.state.db.pool.acquire() as conn:
                    await conn.execute("SELECT 1")
                checks["postgres"] = True
            else:
                checks["postgres"] = False
        except Exception:
            checks["postgres"] = False

        ready = all(checks.values())
        return {"ready": ready, "checks": checks}

    register_exception_handlers(app)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    return app


app = create_app()
