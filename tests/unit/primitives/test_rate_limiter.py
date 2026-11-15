"""Tests for the token bucket rate limiter — safety critical.

Verifies:
- CE rate: 0.5 TPS (1 call / 2 seconds)
- Regional services: distinct buckets per region
- Global services: shared bucket regardless of region
- Thread safety: concurrent acquires don't exceed rate
"""

import threading
import time

from harness_primitives.rate_limiter import (
    GLOBAL_SERVICES,
    SERVICE_LIMITS,
    RateLimiter,
    TokenBucket,
)


class TestTokenBucket:
    def test_burst_allows_immediate_first_call(self):
        bucket = TokenBucket(rate=0.5, burst=1)
        start = time.monotonic()
        bucket.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1, "First acquire with burst=1 should be immediate"

    def test_ce_rate_enforces_two_second_gap(self):
        """CE is 0.5 TPS — the 2nd call must take ~2 seconds."""
        bucket = TokenBucket(rate=0.5, burst=1)
        bucket.acquire()  # consume burst
        start = time.monotonic()
        bucket.acquire()
        elapsed = time.monotonic() - start
        assert 1.8 <= elapsed <= 2.5, f"Expected ~2s, got {elapsed:.2f}s"

    def test_burst_capacity_allows_initial_burst(self):
        bucket = TokenBucket(rate=1.0, burst=3)
        start = time.monotonic()
        for _ in range(3):
            bucket.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1, "Burst of 3 should be immediate with capacity 3"

    def test_thread_safety_concurrent_acquires(self):
        """16 threads acquiring — total time must respect rate."""
        rate = 10.0  # 10 TPS
        bucket = TokenBucket(rate=rate, burst=1)
        results = []
        lock = threading.Lock()

        def worker():
            bucket.acquire()
            with lock:
                results.append(time.monotonic())

        start = time.monotonic()
        threads = [threading.Thread(target=worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        total = time.monotonic() - start

        # 16 acquires at 10 TPS ≈ 1.5s minimum
        assert total >= 1.4, f"16 acquires at 10 TPS should take >=1.4s, got {total:.2f}s"
        assert total <= 3.0, f"Should not take absurdly long, got {total:.2f}s"


class TestRateLimiter:
    def test_ce_has_strictest_limit(self):
        assert SERVICE_LIMITS["ce"]["rate"] == 0.5
        assert SERVICE_LIMITS["ce"]["strict"] is True

    def test_regional_services_get_distinct_buckets(self):
        rl = RateLimiter()
        key1 = rl._get_bucket_key("ec2", "123456789012", "eu-west-1")
        key2 = rl._get_bucket_key("ec2", "123456789012", "us-east-1")
        assert key1 != key2

    def test_global_services_share_bucket_across_regions(self):
        rl = RateLimiter()
        key1 = rl._get_bucket_key("iam", "123456789012", "eu-west-1")
        key2 = rl._get_bucket_key("iam", "123456789012", "us-east-1")
        assert key1 == key2

    def test_accounts_get_distinct_buckets(self):
        rl = RateLimiter()
        key1 = rl._get_bucket_key("iam", "111111111111")
        key2 = rl._get_bucket_key("iam", "222222222222")
        assert key1 != key2

    def test_is_global(self):
        rl = RateLimiter()
        assert rl.is_global("iam") is True
        assert rl.is_global("cloudfront") is True
        assert rl.is_global("ec2") is False
        assert rl.is_global("s3") is False

    def test_unknown_service_uses_default_limit(self):
        rl = RateLimiter()
        limit = rl.get_limit("unknown-service")
        assert limit["rate"] == 10.0

    def test_global_service_set_matches_design(self):
        assert "iam" in GLOBAL_SERVICES
        assert "cloudfront" in GLOBAL_SERVICES
        assert "sts" in GLOBAL_SERVICES
        assert "route53" in GLOBAL_SERVICES
        assert "organizations" in GLOBAL_SERVICES
        assert "ec2" not in GLOBAL_SERVICES
