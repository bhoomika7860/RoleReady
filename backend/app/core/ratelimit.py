"""In-process sliding-window rate limiter (single instance; SRS 2.6 allows in-memory limits)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.config import get_settings
from app.core.errors import RateLimited

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def check(bucket: str, key: str, limit: int, window_s: int) -> None:
    if not get_settings().rate_limit_enabled:
        return
    now = time.monotonic()
    with _lock:
        q = _hits[(bucket, key)]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, int(window_s - (now - q[0])) + 1)
            raise RateLimited(f"Too many attempts. Try again in {retry} s.", headers={"Retry-After": str(retry)},
                              details={"retry_after_seconds": retry})
        q.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()
