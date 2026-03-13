"""TTL-expiring nonce store for OAuth CSRF protection.

For multi-worker deployments, replace with Redis-backed implementation.
"""

from __future__ import annotations

import time


_DEFAULT_TTL = 600  # 10 minutes


class TTLNonceStore:
    """In-memory nonce store that auto-expires entries older than TTL seconds."""

    def __init__(self, ttl: int = _DEFAULT_TTL):
        self._ttl = ttl
        self._data: dict[str, tuple[object, float]] = {}

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, ts) in self._data.items() if now - ts > self._ttl]
        for k in expired:
            del self._data[k]

    def __setitem__(self, nonce: str, value: object) -> None:
        self._cleanup()
        self._data[nonce] = (value, time.monotonic())

    def __contains__(self, nonce: object) -> bool:
        self._cleanup()
        return nonce in self._data

    def __getitem__(self, nonce: str) -> object:
        self._cleanup()
        return self._data[nonce][0]

    def pop(self, nonce: str, default: object = None) -> object:
        self._cleanup()
        entry = self._data.pop(nonce, None)
        if entry is None:
            return default
        return entry[0]

    def __len__(self) -> int:
        self._cleanup()
        return len(self._data)

    def keys(self):
        self._cleanup()
        return self._data.keys()

    def clear(self) -> None:
        self._data.clear()
