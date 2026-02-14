from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import v1_router
from app.config import settings
from app.exceptions.handlers import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    yield
    # Shutdown
    await app.state.redis.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(v1_router, prefix="/api/v1")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "healthy"}

    @app.get("/readiness")
    async def readiness() -> dict:
        return {"ready": True}

    register_exception_handlers(app)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    return app


app = create_app()
