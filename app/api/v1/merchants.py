"""Merchant profile API endpoints."""

from __future__ import annotations

import json
import logging

import redis.asyncio
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.deps import get_db, get_redis, limiter, require_api_key, verify_api_key
from app.config import settings
from app.db.bulk_ingestor import BulkIngestor
from app.services.url_normalizer import normalize_shop_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/merchants", tags=["merchants"])


def _parse_jsonb_fields(row: dict) -> dict:
    """Parse JSONB fields that asyncpg may return as strings."""
    result = dict(row)
    for json_field in ("contact", "social_links", "analytics_tags", "pages_crawled"):
        if json_field in result:
            value = result[json_field]
            if isinstance(value, str):
                try:
                    result[json_field] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass
    return result


@router.get("/profiles")
async def list_merchant_profiles(
    db=Depends(get_db),
    _: str = Depends(verify_api_key),
) -> list[dict]:
    """List all extracted merchant profiles."""
    from app.db.merchant_profile_ingestor import MerchantProfileIngestor

    ingestor = MerchantProfileIngestor(db)
    profiles = await ingestor.list_all()
    return [_parse_jsonb_fields(p) for p in profiles]


@router.get("/profile")
async def get_merchant_profile(
    shop_id: str = Query(..., description="Shop URL identifier (e.g. https://example.com)"),
    db=Depends(get_db),
    _: str = Depends(verify_api_key),
) -> dict:
    """Get extracted merchant profile for a shop.

    Returns the merchant's business profile including company info,
    social links, contact details, and detected analytics tags.
    """
    from app.db.merchant_profile_ingestor import MerchantProfileIngestor

    ingestor = MerchantProfileIngestor(db)
    profile = await ingestor.get(shop_id)

    if not profile:
        raise HTTPException(
            status_code=404,
            detail=f"Merchant profile not found for shop_id: {shop_id}",
        )

    return _parse_jsonb_fields(profile)


@router.delete("/{shop_id:path}", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_onboard)
async def delete_merchant_data(
    request: Request,
    shop_id: str,
    db=Depends(get_db),
    redis_client: redis.asyncio.Redis = Depends(get_redis),
) -> dict:
    """Delete all data for a merchant (GDPR right to erasure).

    Cascades deletion across:
    - products table
    - merchant_profiles table
    - Redis progress keys
    - Redis DLQ entries
    """
    shop_id = normalize_shop_url(shop_id)

    result = {"shop_id": shop_id, "products_deleted": 0, "profiles_deleted": 0, "redis_keys_deleted": 0}

    # Delete from PostgreSQL
    if db is not None:
        ingestor = BulkIngestor(db)
        db_result = await ingestor.delete_merchant_data(shop_id)
        result.update(db_result)

    # Delete from Redis: scan progress keys for matching shop_url
    redis_deleted = 0
    cursor = 0
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match="progress:*", count=100)
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            shop_url = await redis_client.hget(key_str, "shop_url")
            if shop_url:
                shop_url_str = shop_url.decode() if isinstance(shop_url, bytes) else shop_url
                if normalize_shop_url(shop_url_str) == shop_id:
                    await redis_client.delete(key_str)
                    redis_deleted += 1
        if cursor == 0:
            break

    # Delete from DLQ
    dlq_entries = await redis_client.hgetall("dlq:jobs")
    for job_id, job_data in list(dlq_entries.items()):
        job_id_str = job_id.decode() if isinstance(job_id, bytes) else job_id
        job_data_str = job_data.decode() if isinstance(job_data, bytes) else job_data
        if shop_id in job_data_str:
            await redis_client.hdel("dlq:jobs", job_id_str)
            redis_deleted += 1

    result["redis_keys_deleted"] = redis_deleted

    return result
