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
from app.db.queries import ALTER_PRODUCTS_ADD_IDEALO_FIELDS, CREATE_OAUTH_CONNECTIONS_TABLE, CREATE_PRODUCTS_TABLE, CREATE_MERCHANT_PROFILES_TABLE
from app.db.supabase_client import DatabaseClient
from app.exceptions.handlers import register_exception_handlers
from app.infra.perf_middleware import PerfMiddleware
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
                await conn.execute(CREATE_PRODUCTS_TABLE)
                await conn.execute(ALTER_PRODUCTS_ADD_IDEALO_FIELDS)
                await conn.execute(CREATE_MERCHANT_PROFILES_TABLE)
                await conn.execute(CREATE_OAUTH_CONNECTIONS_TABLE)
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
        allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.limiter = limiter
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
