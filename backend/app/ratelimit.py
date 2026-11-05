import hashlib
import math
import time
from collections import deque
from typing import Deque, Dict
from fastapi import HTTPException, Request

# Above this many tracked keys, acquire() drops every key whose window has emptied.
SWEEP_THRESHOLD = 10_000

class FailureLimiter:
    """In-memory sliding window over failed attempts, keyed by an arbitrary string.

    State lives in this process only, so limits reset on restart and are per worker.
    """

    def __init__(self, max_failures: int, window_seconds: int):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: Dict[str, Deque[float]] = {}

    def _prune(self, key: str, now: float) -> Deque[float]:
        q = self._failures.get(key)
        if q is None:
            return deque()
        while q and now - q[0] >= self.window_seconds:
            q.popleft()
        if not q:
            del self._failures[key]
        return q

    def _sweep(self, now: float) -> None:
        for key in list(self._failures):
            self._prune(key, now)

    def acquire(self, key: str) -> float:
        """Reserve one attempt slot before the attempt runs; raise 429 if the window is full.

        Synchronous, so requests interleaved on one event loop cannot all pass the check
        before any of them is recorded. Keep the slot on failure; call release() with the
        returned stamp only when the attempt turns out not to be a guess.
        """
        now = time.monotonic()
        if len(self._failures) > SWEEP_THRESHOLD:
            self._sweep(now)
        q = self._prune(key, now)
        if len(q) >= self.max_failures:
            retry_after = max(1, math.ceil(self.window_seconds - (now - q[0])))
            raise HTTPException(
                status_code=429,
                detail="auth.too_many_attempts",
                headers={"Retry-After": str(retry_after)},
            )
        self._failures.setdefault(key, deque()).append(now)
        return now

    def release(self, key: str, stamp: float) -> None:
        q = self._failures.get(key)
        if q is None:
            return
        try:
            q.remove(stamp)
        except ValueError:
            return
        if not q:
            del self._failures[key]

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def clear(self) -> None:
        self._failures.clear()

def client_ip(request: Request) -> str:
    # The backend is reachable only via nginx, which sets X-Real-IP, or from localhost.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")

def account_key(ip: str, username: str) -> str:
    # Hashed so attacker-chosen usernames cannot make the key space grow with string length.
    return hashlib.sha256(f"{ip}:{username.lower()}".encode("utf-8", "surrogatepass")).hexdigest()

account_limiter = FailureLimiter(5, 900)
ip_limiter = FailureLimiter(30, 900)
