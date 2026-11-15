"""
HarnessExecutor — ThreadPoolExecutor fan-out across accounts and regions.

Per design §2.7:
- ThreadPoolExecutor (boto3 blocks; GIL released on socket I/O)
- max_workers=50 total, per_account_limit=10 bounded concurrency
- Global-service short-circuit: no region fan-out for global services
- Per-account-per-region-per-API rate limiting (botocore adaptive retry
  handles transient throttling; the token bucket prevents over-attempting)
- Session cache per account (avoids repeated AssumeRole — the #1
  scalability bottleneck per GLM review)
- PartialResult aggregation with failure classification

Thread safety: boto3 clients are thread-safe; resources are never used.
One HarnessSession per account (cached), clients created per service+region
inside the session (cached there too).
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from harness_primitives.failure import (
    FailureCategory,
    HarnessError,
)
from harness_primitives.output import (
    FailureMsg,
    PartialResult,
)
from harness_primitives.rate_limiter import RateLimiter


@dataclass
class _AccountSessionCache:
    """Per-account session cache with TTL. Avoids repeated AssumeRole.

    Concurrency: the bucket dict is guarded by a short lock, and each
    entry has its OWN lock so the AssumeRole network call happens under
    the per-entry lock only — creating sessions for N accounts never
    serializes on a single global lock (audit pass 2, #7).
    """
    ttl: int = 3600
    _cache: dict[str, tuple[Any, float]] = field(default_factory=dict)
    _entry_locks: dict[str, threading.Lock] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _entry_lock(self, key: str) -> threading.Lock:
        with self._lock:
            if key not in self._entry_locks:
                self._entry_locks[key] = threading.Lock()
            return self._entry_locks[key]

    def get_or_create(self, account_id: str,
                      factory: Callable[[], Any]) -> Any:
        entry = self._cache.get(account_id)
        now = time.monotonic()
        if entry and (now - entry[1]) < self.ttl:
            return entry[0]  # fast path, no lock
        with self._entry_lock(account_id):
            entry = self._cache.get(account_id)
            now = time.monotonic()
            if entry and (now - entry[1]) < self.ttl:
                return entry[0]  # another thread created it while we waited
            session = factory()
            self._cache[account_id] = (session, now)
            return session

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._entry_locks.clear()


def _classify_failure(exc: Exception, account_id: str,
                      region: Optional[str] = None) -> FailureMsg:
    """Classify an exception into a FailureMsg with error code."""
    err = getattr(exc, "response", {}).get("Error", {})
    code = err.get("Code", type(exc).__name__)
    message = err.get("Message", str(exc))
    return FailureMsg(
        account_id=account_id,
        region=region,
        error_code=code,
        message=message,
    )


class HarnessExecutor:
    """Fan-out executor with bounded concurrency and rate limiting."""

    def __init__(self, config: Any, rate_limiter: Optional[RateLimiter] = None):
        """
        config: harness_primitives.config.HarnessConfig
                (uses execution.* settings)
        """
        self.config = config
        exec_cfg = config.execution
        self._pool = ThreadPoolExecutor(max_workers=exec_cfg.max_workers)
        self._rate_limiter = rate_limiter or RateLimiter(
            default_rps=exec_cfg.rate_limit_rps
        )
        self._account_semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._semaphore_lock = threading.Lock()
        self._session_cache = _AccountSessionCache(ttl=exec_cfg.session_cache_ttl)

    # ─── Session access for workers ─────────────────────────────

    def session_for(self, account: Any) -> Any:
        """Get or create a cached HarnessSession for an account.

        `account` is an Account from harness_primitives.accounts.
        Role-ARN precedence (highest first):
          1. --role CLI flag (explicit user intent wins over config)
          2. Per-account override (config manual accounts)
          3. Config default template ({account_id} expansion)
        """
        def factory() -> Any:
            from harness_cli.main import get_ctx
            from harness_primitives.session import HarnessSession
            defaults = self.config.accounts.defaults
            ctx = get_ctx()
            ctx_role = ctx.get("role")
            ctx_external_id = ctx.get("external_id")
            role_arn = ctx_role or account.role_arn or defaults.role_arn_for(account.id)
            # Business external_id applies when the account belongs to one
            biz = (self.config.accounts.business(account.business)
                   if account.business else None)
            external_id = (
                ctx_external_id
                or (biz.external_id if biz else None)
                or defaults.external_id
            )
            return HarnessSession(
                profile=account.profile or defaults.profile,
                role_arn=role_arn,
                external_id=external_id,
                session_tags=defaults.session_tags,
                account_id=account.id,
                region=self.config.regions.north_america.primary,
            )

        return self._session_cache.get_or_create(account.id, factory)

    def _account_semaphore(self, account_id: str) -> threading.BoundedSemaphore:
        with self._semaphore_lock:
            if account_id not in self._account_semaphores:
                self._account_semaphores[account_id] = threading.BoundedSemaphore(
                    self.config.execution.per_account_limit
                )
            return self._account_semaphores[account_id]

    def shutdown(self):
        """Release thread pool and caches."""
        self._pool.shutdown(wait=True)
        self._session_cache.clear()

    # ─── Fan-out ─────────────────────────────────────────────────

    def execute_across_accounts(
        self,
        accounts: list[Any],
        func: Callable[..., Any],
        service: Optional[str] = None,
        **kwargs,
    ) -> PartialResult:
        """Run func(session, account, **kwargs) across accounts in parallel.

        func signature: (session, account) — session is the account's
        cached HarnessSession. `service` (when given) engages the rate
        limiter for (service, account) before each call.
        """
        result = PartialResult()

        futures = {}
        for acct in accounts:
            semaphore = self._account_semaphore(acct.id)
            future = self._pool.submit(
                self._run_for_account,
                semaphore, acct, func, service, kwargs,
            )
            futures[future] = acct

        for future in as_completed(futures):
            acct = futures[future]
            try:
                data = future.result()
                result.success[acct.id] = data
            except HarnessError as e:
                result.failures.append(_classify_failure(e, acct.id))
            except Exception as e:
                result.failures.append(_classify_failure(e, acct.id))
        return result

    def _run_for_account(self, semaphore: threading.BoundedSemaphore,
                         account: Any,
                         func: Callable, service: Optional[str],
                         kwargs: dict) -> Any:
        # Session creation happens INSIDE the worker (audit pass 2, #7):
        # AssumeRole calls for different accounts run concurrently,
        # bounded by the per-account semaphore, instead of serializing
        # in the submission thread.
        session = self.session_for(account)
        with semaphore:  # Bounded per-account concurrency
            if service:
                self._rate_limiter.acquire(service, account.id)
            return func(session, account, **kwargs)

    def execute_across_regions(
        self,
        regions: list[str],
        func: Callable[..., Any],
        session: Any = None,
        account_id: str = "unknown",
        service: Optional[str] = None,
        is_global: bool = False,
        **kwargs,
    ) -> PartialResult:
        """Run func(session, region, **kwargs) across regions.

        is_global=True short-circuits: one call with the first region
        (global services — IAM, CloudFront, Route53... — must not be
        fanned out; each regional endpoint would repeat the call).
        """
        result = PartialResult()

        if is_global:
            if not regions:
                raise HarnessError(
                    "No regions configured for a global service call",
                    FailureCategory.FATAL,
                )
            try:
                if service:
                    self._rate_limiter.acquire(service, account_id)
                result.success["_global"] = func(session, regions[0], **kwargs)
            except Exception as e:
                result.failures.append(_classify_failure(e, account_id, region=None))
            return result

        futures = {}
        for region in regions:
            future = self._pool.submit(
                self._run_for_region,
                session, region, func, service, account_id, kwargs,
            )
            futures[future] = region

        for future in as_completed(futures):
            region = futures[future]
            try:
                result.success[region] = future.result()
            except Exception as e:
                result.failures.append(_classify_failure(e, account_id, region=region))
        return result

    def _run_for_region(self, session: Any, region: str,
                       func: Callable, service: Optional[str],
                       account_id: str, kwargs: dict) -> Any:
        if service:
            self._rate_limiter.acquire(service, account_id, region=region)
        return func(session, region, **kwargs)

    # ─── Combined sweep (accounts × regions) ─────────────────────

    def execute_sweep(
        self,
        accounts: list[Any],
        regions_for: Callable[[Any], list[str]],
        func: Callable[..., Any],
        service: Optional[str] = None,
        is_global: bool = False,
        **kwargs,
    ) -> PartialResult:
        """Run func(session, account, region, **kwargs) across accounts × regions.

        regions_for(account) returns the enabled regions for that account
        (caller composes config regions with region-enablement detection).
        Global services call func once per account (no region fan-out).
        """
        result = PartialResult()

        def per_account(session: Any, account: Any) -> Any:
            # Bind account into the per-region call: sweep func is
            # (session, account, region); regional executor calls
            # func(session, region).
            def region_func(s: Any, region: str) -> Any:
                return func(s, account, region)

            if is_global:
                regions = regions_for(account)[:1] or [None]
                local = PartialResult()
                try:
                    if service:
                        self._rate_limiter.acquire(service, account.id)
                    local.success["_global"] = region_func(session, regions[0])
                except Exception as e:
                    result.failures.append(
                        _classify_failure(e, account.id, region=None)
                    )
                return {"regions": local.success, "failures": len(result.failures)}
            return self.execute_across_regions(
                regions_for(account),
                region_func,
                session=session,
                account_id=account.id,
                service=service,
            )

        sweep = self.execute_across_accounts(
            accounts, per_account, service=None,  # rate-limited inside
        )
        # Flatten: account → region → data
        for account_id, data in sweep.success.items():
            if isinstance(data, PartialResult):
                regions_data = data.success  # regional path returns PartialResult
            elif isinstance(data, dict):
                regions_data = data.get("regions", data)  # global path wraps in dict
            else:
                continue
            for region, payload in regions_data.items():
                result.success[f"{account_id}:{region}"] = payload
        for f in sweep.failures:
            result.failures.append(f)
        return result
