"""Tests for the HarnessExecutor — fan-out, concurrency, rate limiting.

Uses fake sessions/accounts; no AWS calls.
"""

import threading
import time
from dataclasses import dataclass

from harness_primitives.config import HarnessConfig
from harness_primitives.executor import HarnessExecutor


@dataclass
class FakeAccount:
    """Mirrors the Account contract from harness_primitives.accounts."""
    id: str
    name: str = "test"
    ou_path: str | None = None
    status: str = "ACTIVE"
    profile: str | None = None
    role_arn: str | None = None
    regions: list | None = None
    discovery_source: str = "organizations"
    business: str | None = None   # Phase 18: multi-business support


class FakeSession:
    pass


def make_executor(**exec_overrides) -> HarnessExecutor:
    cfg = HarnessConfig()
    for k, v in exec_overrides.items():
        setattr(cfg.execution, k, v)
    return HarnessExecutor(cfg)


def make_accounts(n):
    return [FakeAccount(id=f"{111111111111 + i}", name=f"acct{i}") for i in range(n)]


class TestExecuteAcrossAccounts:
    def test_all_success(self):
        ex = make_executor()

        def func(session, account):
            return {"id": account.id}

        result = ex.execute_across_accounts(make_accounts(3), func)
        assert result.is_all_success
        assert result.success_count == 3
        assert result.success["111111111111"] == {"id": "111111111111"}
        ex.shutdown()

    def test_partial_failure_captured(self):
        ex = make_executor()

        def func(session, account):
            if account.id == "111111111112":
                raise PermissionError(f"AccessDenied: SCP denied {account.id}")
            return "ok"

        result = ex.execute_across_accounts(make_accounts(3), func)
        assert result.failure_count == 1
        assert "111111111112" not in result.success
        assert result.failures[0].error_code == "PermissionError"
        assert result.exit_code == 1
        ex.shutdown()

    def test_per_account_semaphore_bounds_concurrency(self):
        """per_account_limit must bound concurrent calls per account."""
        ex = make_executor(per_account_limit=2, max_workers=10)
        concurrent = []
        peak = []
        lock = threading.Lock()

        def func(session, account):
            with lock:
                concurrent.append(1)
                peak.append(len(concurrent))
            time.sleep(0.05)
            with lock:
                concurrent.pop()
            return "ok"

        # 8 tasks for the SAME account → bounded by semaphore(2)
        result = ex.execute_across_accounts(
            [FakeAccount(id="111111111111")] * 8, func
        )
        assert result.is_all_success
        assert max(peak) <= 2, f"Concurrency exceeded per-account limit: {max(peak)}"
        ex.shutdown()

    def test_session_cached_per_account(self):
        """Repeated calls for the same account reuse the session factory result."""
        ex = make_executor()
        result = ex.execute_across_accounts(make_accounts(3), lambda s, a: "ok")
        assert result.is_all_success

        # Direct cache check: same account → same session object
        acct = FakeAccount(id="111111111111")
        s1 = ex.session_for(acct)
        s2 = ex.session_for(acct)
        assert s1 is s2
        ex.shutdown()


class TestExecuteAcrossRegions:
    def test_regional_fanout(self):
        ex = make_executor()
        result = ex.execute_across_regions(
            ["us-east-1", "eu-west-1", "eu-central-1"],
            lambda session, region: {"region": region},
        )
        assert result.is_all_success
        assert set(result.success) == {"us-east-1", "eu-west-1", "eu-central-1"}
        ex.shutdown()

    def test_global_short_circuit_single_call(self):
        """Global services must NOT fan out — exactly one call."""
        ex = make_executor()
        calls = []

        def func(session, region):
            calls.append(region)
            return {"global": True}

        result = ex.execute_across_regions(
            ["us-east-1", "eu-west-1", "eu-central-1"],
            func, is_global=True,
        )
        assert result.is_all_success
        assert len(calls) == 1, f"Global service called {len(calls)} times!"
        assert "_global" in result.success
        ex.shutdown()

    def test_region_failure_isolated(self):
        ex = make_executor()

        def func(session, region):
            if region == "eu-west-1":
                raise TimeoutError("read timeout")
            return "ok"

        result = ex.execute_across_regions(
            ["us-east-1", "eu-west-1", "eu-central-1"], func
        )
        assert result.failure_count == 1
        assert result.failures[0].region == "eu-west-1"
        assert result.success_count == 2
        ex.shutdown()


class TestRateLimiting:
    def test_rate_limiter_engaged_per_call(self):
        """With service set, the rate limiter must gate calls.

        Uses a tight rate via a custom limiter stub.
        """
        ex = make_executor()
        acquired = []

        class SpyLimiter:
            def acquire(self, service, account_id, region=None):
                acquired.append((service, account_id, region))

        ex._rate_limiter = SpyLimiter()

        ex.execute_across_accounts(
            make_accounts(2),
            lambda s, a: "ok",
            service="ec2",
        )
        assert len(acquired) == 2
        assert all(a[0] == "ec2" for a in acquired)
        ex.shutdown()

    def test_region_limiter_gets_region_key(self):
        ex = make_executor()
        acquired = []

        class SpyLimiter:
            def acquire(self, service, account_id, region=None):
                acquired.append(region)

        ex._rate_limiter = SpyLimiter()
        ex.execute_across_regions(
            ["us-east-1", "eu-west-1"],
            lambda s, r: "ok",
            account_id="111111111111",
            service="ec2",
        )
        assert sorted(a for a in acquired if a) == ["eu-west-1", "us-east-1"]
        ex.shutdown()


class TestSweep:
    def test_accounts_times_regions(self):
        """Sweep: 2 accounts × 2 regions → 4 keyed results."""
        ex = make_executor()

        accounts = make_accounts(2)
        regions_by_account = {a.id: ["us-east-1", "eu-west-1"] for a in accounts}

        def func(session, account, region):
            return f"{account.id}@{region}"

        result = ex.execute_sweep(
            accounts=accounts,
            regions_for=lambda a: regions_by_account[a.id],
            func=func,
        )
        assert result.is_all_success
        assert result.success_count == 4
        first, second = accounts[0].id, accounts[1].id
        assert result.success[f"{first}:us-east-1"] == f"{first}@us-east-1"
        assert result.success[f"{second}:eu-west-1"] == f"{second}@eu-west-1"
        ex.shutdown()

    def test_sweep_global_single_call_per_account(self):
        ex = make_executor()
        calls = []

        def func(session, account, region):
            calls.append((account.id, region))
            return "ok"

        result = ex.execute_sweep(
            accounts=make_accounts(2),
            regions_for=lambda a: ["us-east-1", "eu-west-1"],  # ignored for global
            func=func,
            is_global=True,
        )
        assert result.is_all_success
        assert len(calls) == 2, f"Global sweep made {len(calls)} calls (expected 2)"
        ex.shutdown()
