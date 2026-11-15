"""
Thread-safe token bucket rate limiter.

Per-account-per-region-per-API limiting for AWS API calls.
Cost Explorer: 0.5 TPS (one request every 2 seconds)
Regional services: per-account + per-region + per-API
Global services: per-account + per-API
"""

import threading
import time


class TokenBucket:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, rate: float, burst: int = 1):
        self.rate = rate               # tokens per second
        self.capacity = burst
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self):
        """Acquire a token, blocking if necessary."""
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.rate
            time.sleep(wait)


SERVICE_LIMITS = {
    "ce": {"rate": 0.5, "burst": 1, "strict": True},  # Cost Explorer — 0.5 TPS!
    "organizations": {"rate": 10.0, "burst": 5},
    "guardduty": {"rate": 15.0, "burst": 5},
    "ec2": {"rate": 5.0, "burst": 3},
    "iam": {"rate": 5.0, "burst": 3},
    "s3": {"rate": 5.0, "burst": 3},
    "lambda": {"rate": 5.0, "burst": 3},
    "cloudfront": {"rate": 2.0, "burst": 1},  # Global service
    "default": {"rate": 10.0, "burst": 5},
}

GLOBAL_SERVICES = {
    "iam", "cloudfront", "sts", "route53", "organizations",
    "budget", "pricing", "waf", "guardduty",
}


class RateLimiter:
    """Per-account-per-region-per-API rate limiting."""

    def __init__(self, default_rps: float = 10.0):
        self.default_rps = default_rps
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()  # guards bucket creation

    def _get_bucket_key(self, service: str, account_id: str,
                        region: str | None = None) -> str:
        """Build unique key: global services use account+service; regional use account+region+service."""
        is_global = service in GLOBAL_SERVICES
        if is_global or region is None:
            return f"{account_id}:{service}"
        return f"{account_id}:{region}:{service}"

    def get_limit(self, service: str) -> dict:
        """Get rate limit config for a service."""
        return SERVICE_LIMITS.get(service, SERVICE_LIMITS["default"])

    def is_global(self, service: str) -> bool:
        """Check if service is global (breaks region fan-out)."""
        return service in GLOBAL_SERVICES

    def acquire(self, service: str, account_id: str, region: str | None = None):
        """Acquire a rate limit token for this service+account+region."""
        key = self._get_bucket_key(service, account_id, region)
        limit = self.get_limit(service)

        bucket = self._buckets.get(key)
        if bucket is None:
            with self._lock:  # no race: two threads can't both create
                bucket = self._buckets.get(key)
                if bucket is None:
                    bucket = TokenBucket(
                        rate=limit["rate"],
                        burst=limit["burst"]
                    )
                    self._buckets[key] = bucket

        bucket.acquire()

    def acquire_for_ce(self, account_id: str):
        """Acquire for Cost Explorer — serialized per account at 0.5 TPS."""
        # CE is always serialized per account
        return self.acquire("ce", account_id)
