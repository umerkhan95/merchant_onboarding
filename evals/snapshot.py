"""Capture and manage HTML snapshots for offline evaluation."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

SNAPSHOTS_DIR = Path(__file__).parent / "fixtures" / "snapshots"


async def capture_snapshot(url: str, output_path: Path | None = None) -> Path:
    """Fetch a URL and save the HTML to a file.

    Args:
        url: URL to fetch
        output_path: Where to save. Defaults to SNAPSHOTS_DIR/{domain}_{path_slug}.html

    Returns:
        Path to the saved snapshot file
    """
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        slug = parsed.netloc.replace(".", "_") + parsed.path.replace("/", "_").rstrip("_")
        output_path = SNAPSHOTS_DIR / f"{slug}.html"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        output_path.write_text(response.text, encoding="utf-8")
        logger.info("Saved snapshot: %s (%d bytes)", output_path.name, len(response.text))

    return output_path


def get_snapshot_path(url: str) -> Path | None:
    """Check if a snapshot exists for a URL.

    Returns:
        Path to snapshot if it exists, None otherwise
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    slug = parsed.netloc.replace(".", "_") + parsed.path.replace("/", "_").rstrip("_")
    path = SNAPSHOTS_DIR / f"{slug}.html"
    return path if path.exists() else None
