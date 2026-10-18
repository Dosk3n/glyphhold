from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field


@dataclass
class FailureBucket:
    attempts: deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    expires_at: float = 0


class FailureRateLimiter:
    """Bounded process-local failure budgets; the public proxy adds global traffic limits."""

    def __init__(self, max_keys: int = 4096) -> None:
        self._attempts: OrderedDict[str, FailureBucket] = OrderedDict()
        self._lock = threading.Lock()
        self.max_keys = max_keys
        self._next_prune = 0.0

    def _prune(self, now: float) -> None:
        if now >= self._next_prune:
            for key in list(self._attempts):
                if self._attempts[key].expires_at <= now:
                    del self._attempts[key]
            self._next_prune = now + 30

    def retry_after(self, key: str, *, limit: int, window_seconds: int) -> int:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            bucket = self._attempts.get(key)
            if bucket is None:
                return 0
            while bucket.attempts and bucket.attempts[0] <= now - window_seconds:
                bucket.attempts.popleft()
            if not bucket.attempts:
                del self._attempts[key]
                return 0
            if len(bucket.attempts) < limit:
                return 0
            return max(1, int(window_seconds - (now - bucket.attempts[0])))

    def add_failure(self, key: str, *, window_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            bucket = self._attempts.get(key)
            if bucket is None:
                if len(self._attempts) >= self.max_keys:
                    self._attempts.popitem(last=False)
                bucket = FailureBucket()
                self._attempts[key] = bucket
            while bucket.attempts and bucket.attempts[0] <= now - window_seconds:
                bucket.attempts.popleft()
            bucket.attempts.append(now)
            bucket.expires_at = now + window_seconds
            self._attempts.move_to_end(key)

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)
