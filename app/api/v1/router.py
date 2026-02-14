from fastapi import APIRouter

from app.api.v1.dlq import router as dlq_router
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.products import router as products_router

v1_router = APIRouter()

# Include all sub-routers
v1_router.include_router(onboarding_router)
v1_router.include_router(products_router)
v1_router.include_router(dlq_router)


@v1_router.get("/ping")
async def ping() -> dict:
    return {"pong": True}
