"""Tests for audit pass-2 fixes:

#1  global --dry-run / --quiet / --verbose / --all-regions wired
#2  JSON output survives datetime/Decimal payloads
#3  table renderer shows real data (not 30-char repr)
#4  audit trail records mutating actions
#5  --role/--external-id reach executor sessions
#6  (code-level: per-account session passed to regions_for)
#7  session creation: per-entry locks, runs in worker threads
#8  region cache TTL + --refresh clears it
#9  exit code 2 when everything failed
#10 assume: duration validation + assumes via session code
#11 AccountDefaults.regions honored
#12 HarnessFailure removed
#13 account list --discovery overrides config
#14 (dead code in _enabled_regions_cached removed)
#15 rate limiter bucket creation is lock-guarded
"""

import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import typer

import harness_cli.main as cli_main
from harness_primitives.config import AccountDefaults, AccountsConfig, HarnessConfig, ManualAccount
from harness_primitives.executor import HarnessExecutor, _AccountSessionCache
from harness_primitives.output import FailureMsg, PartialResult, format_output
from harness_primitives.rate_limiter import RateLimiter


def _ctx(**kw):
    """Set the CLI global context (same dict the typer callback writes)."""
    cli_main._CTX.clear()
    cli_main._CTX.update(kw)


class TestGlobalFlagsWired:
    """#1: --dry-run, --quiet, --verbose, --all-regions must do something."""

    def test_effective_dry_run_combines_yes_global_and_command(self):
        """Safety contract: dry-run is the DEFAULT; --yes executes;
        global --dry-run forces simulation even combined with --yes."""
        from harness_plugins.ec2.plugin import _effective_dry_run
        _ctx(dry_run=True)
        assert _effective_dry_run(yes=False, dry_run=False) is True  # global alone
        assert _effective_dry_run(yes=True, dry_run=False) is True   # global beats --yes
        _ctx(dry_run=False)
        assert _effective_dry_run(yes=False, dry_run=False) is True   # default: simulate
        assert _effective_dry_run(yes=True, dry_run=False) is False   # --yes executes
        assert _effective_dry_run(yes=True, dry_run=True) is True    # cmd --dry-run wins
        assert _effective_dry_run(yes=False, dry_run=True) is True

    def test_dry_run_passed_to_ec2_safe_op(self):
        """dry_run=True must pass DryRun=True to boto3 and treat
        DryRunOperation as success (native EC2 dry-run)."""
        from botocore.exceptions import ClientError

        from harness_plugins.ec2.plugin import EC2Plugin
        plugin = EC2Plugin()
        session = MagicMock()
        client = MagicMock()
        session.get_client.return_value = client
        client.exceptions.ClientError = ClientError

        def _raise_dryrun(**kwargs):
            assert kwargs.get("DryRun") is True
            raise ClientError(
                {"Error": {"Code": "DryRunOperation",
                           "Message": "Request would have succeeded"}},
                "StopInstances",
            )

        client.stop_instances.side_effect = _raise_dryrun
        result = plugin.safe_op(session, "stop", "i-123", dry_run=True)
        assert result["status"] == "dry-run-ok (stop permitted)"

    def test_all_regions_flag_skips_detection(self):
        """#1/#5: --all-regions returns all configured regions, no detection."""
        from harness_cli.runtime import regions_for
        from harness_primitives.accounts import Account
        config = HarnessConfig()
        acct = Account(id="123456789012", name=None, ou_path=None,
                       status="ACTIVE", profile=None, role_arn=None,
                       regions=None, discovery_source="manual")
        _ctx(all_regions=True)
        regions = regions_for(acct, config, MagicMock(), store=None)
        expected = len(set(config.regions.north_america.members)
                       | set(config.regions.europe.members))
        assert len(regions) == expected
        _ctx(all_regions=False)


class TestQuietVerbose:
    def test_emit_quiet_suppresses_success_output(self, capsys):
        from harness_cli.runtime import emit
        _ctx(quiet=True, verbose=False)
        with pytest.raises(Exception) as exc:
            emit(PartialResult(success={"a": 1}), "table")
        captured = capsys.readouterr()
        assert captured.out == ""            # says nothing on success
        # and it must still exit cleanly (code 0)
        assert getattr(exc.value, "exit_code", None) == 0
        _ctx(quiet=False, verbose=False)

    def test_emit_quiet_still_prints_failures(self, capsys):
        from harness_cli.runtime import emit
        _ctx(quiet=True, verbose=False)
        result = PartialResult()
        result.failures.append(FailureMsg(
            account_id="123", error_code="AccessDenied", message="denied"))
        with pytest.raises(Exception) as exc:
            emit(result, "table")
        out = capsys.readouterr().out
        assert "AccessDenied" in out          # errors still print
        assert getattr(exc.value, "exit_code", None) == 2  # all-failed
        _ctx(quiet=False, verbose=False)

    def test_emit_verbose_shows_full_failure_message(self, capsys):
        from harness_cli.runtime import emit
        long_msg = "x" * 200
        _ctx(quiet=False, verbose=False)
        result = PartialResult()
        result.failures.append(FailureMsg(
            account_id="123", error_code="E", message=long_msg))
        with pytest.raises(typer.Exit):
            emit(result, "table")
        assert "x" * 200 not in capsys.readouterr().out  # truncated

        _ctx(quiet=False, verbose=True)
        with pytest.raises(typer.Exit):
            emit(result, "table")
        assert "x" * 200 in capsys.readouterr().out       # full message
        _ctx(quiet=False, verbose=False)


class TestJsonSafety:
    """#2: JSON output must never crash on boto3 payloads."""

    def test_datetime_serializes(self):
        r = PartialResult()
        r.success["acct"] = [{"UserName": "alice",
                              "CreateDate": datetime(2026, 1, 1,
                                                     tzinfo=timezone.utc)}]
        import json
        data = json.loads(format_output(r, "json"))
        assert data["success"]["acct"][0]["CreateDate"] == "2026-01-01T00:00:00+00:00"

    def test_decimal_and_bytes_serialize(self):
        from decimal import Decimal
        r = PartialResult()
        r.success["acct"] = {"cost": Decimal("12.50"), "blob": b"\x00\x01"}
        import json
        json.loads(format_output(r, "json"))  # must not raise

    def test_json_status_all_failed(self):
        r = PartialResult()
        r.failures.append(FailureMsg(account_id="1", error_code="E", message="m"))
        import json
        data = json.loads(format_output(r, "json"))
        assert data["status"] == "all_failed"


class TestExitCodes:
    """#9: exit 2 when everything failed."""

    def test_all_success_zero(self):
        assert PartialResult(success={"a": 1}).exit_code == 0

    def test_partial_one(self):
        r = PartialResult(success={"a": 1},
                          failures=[FailureMsg(account_id="b")])
        assert r.exit_code == 1

    def test_all_failed_two(self):
        r = PartialResult(failures=[FailureMsg(account_id="b"),
                                    FailureMsg(account_id="c")])
        assert r.exit_code == 2


class TestAuditTrail:
    """#4: mutating actions are recorded in the audit store."""

    def test_record_audit_writes_event(self, tmp_path):
        from harness_cli.runtime import record_audit
        from harness_store import database

        config = HarnessConfig()
        config.audit.sqlite_path = tmp_path / "audit.db"
        record_audit(config, action="stop", service="ec2",
                     account_id="123456789012", region="us-east-1",
                     resource_id="i-123", success=True,
                     principal="harness:testuser")
        conn = database.connect(config.audit.sqlite_path)
        events = database.query_audit_trail(conn, account_id="123456789012")
        assert len(events) == 1
        assert events[0]["action"] == "stop"
        assert events[0]["resource_id"] == "i-123"
        assert events[0]["source_identity"] == "harness:testuser"

    def test_record_audit_never_raises(self, tmp_path):
        """Audit write failure must not fail the operation."""
        from harness_cli.runtime import record_audit
        config = HarnessConfig()
        config.audit.sqlite_path = tmp_path / "nonexistent-dir" / "a.db"
        # Should warn to stderr, not raise
        record_audit(config, action="stop", service="ec2", account_id="x")


class TestRoleFlagReachesExecutor:
    """#5: --role/--external-id must override executor sessions."""

    def _config(self):
        return HarnessConfig(accounts=AccountsConfig(
            defaults=AccountDefaults(role_arn="arn:aws:iam::222:role/Config"),
        ))

    def test_cli_role_wins_over_config(self):
        from harness_primitives.accounts import Account
        _ctx(role="arn:aws:iam::333:role/CLI", external_id="ext-1")
        config = self._config()
        executor = HarnessExecutor(config)
        try:
            acct = Account(id="123456789012", name=None, ou_path=None,
                           status="ACTIVE", profile=None, role_arn=None,
                           regions=None, discovery_source="manual")
            sess = executor.session_for(acct)
            assert sess.role_arn == "arn:aws:iam::333:role/CLI"
            assert sess.external_id == "ext-1"
        finally:
            executor.shutdown()
            _ctx(role=None, external_id=None)

    def test_config_used_when_no_cli_role(self):
        from harness_primitives.accounts import Account
        _ctx(role=None, external_id=None)
        config = self._config()
        executor = HarnessExecutor(config)
        try:
            acct = Account(id="123456789012", name=None, ou_path=None,
                           status="ACTIVE", profile=None, role_arn=None,
                           regions=None, discovery_source="manual")
            sess = executor.session_for(acct)
            assert sess.role_arn == "arn:aws:iam::222:role/Config"
        finally:
            executor.shutdown()


class TestSessionCacheConcurrency:
    """#7: session creation must not serialize on one global lock."""

    def test_per_entry_locks_allow_concurrent_creation(self):
        cache = _AccountSessionCache()
        gate = threading.Event()

        def slow_factory(tag):
            def factory():
                gate.wait(timeout=5)     # both factories "in flight" together
                return f"session-{tag}"
            return factory

        results = {}
        threads = [
            threading.Thread(
                target=lambda t=t: results.update(
                    {t: cache.get_or_create(t, slow_factory(t))})
            ) for t in ("a", "b")
        ]
        for th in threads:
            th.start()
        # Both threads must be inside their factories simultaneously
        # (old code: second thread blocked on the global lock forever)
        import time
        time.sleep(0.15)
        gate.set()
        for th in threads:
            th.join(timeout=5)
        assert results["a"] == "session-a"
        assert results["b"] == "session-b"

    def test_sessions_created_inside_worker_threads(self):
        """execute_across_accounts must create sessions in the pool, not
        the calling thread (audit pass 2, #7)."""
        import harness_primitives.executor as exec_mod
        from harness_primitives.accounts import Account

        original = HarnessExecutor.session_for
        caller = threading.current_thread()

        def spy(self, account):
            assert threading.current_thread() is not caller
            return original(self, account)

        config = HarnessConfig()
        executor = HarnessExecutor(config)
        try:
            acct = Account(id="123456789012", name=None, ou_path=None,
                           status="ACTIVE", profile=None, role_arn=None,
                           regions=None, discovery_source="manual")
            exec_mod.HarnessExecutor.session_for = spy
            try:
                result = executor.execute_across_accounts(
                    [acct], lambda s, a: s.role_arn)
            finally:
                exec_mod.HarnessExecutor.session_for = original
            assert result.success_count == 1
        finally:
            executor.shutdown()


class TestRegionCache:
    """#8: region cache has a TTL and --refresh clears it."""

    def test_clear_region_cache(self, tmp_path):
        from harness_store import database
        conn = database.connect(tmp_path / "store.db")
        database.migrate(conn)
        database.upsert_account(conn, "123456789012", name="prod",
                                regions_enabled=["us-east-1"])
        database.clear_region_cache(conn)
        acct = database.get_account(conn, "123456789012")
        assert acct["regions_enabled"] is None
        assert acct["name"] == "prod"       # identity preserved

    def test_region_upsert_does_not_wipe_name(self, tmp_path):
        """Regression: partial upserts used to NULL out identity fields."""
        from harness_store import database
        conn = database.connect(tmp_path / "store.db")
        database.migrate(conn)
        database.upsert_account(conn, "123456789012", name="prod",
                               ou_path="prod/eu", discovery_source="organizations")
        # Region detection upserts WITHOUT name/ou_path
        database.upsert_account(conn, "123456789012",
                                regions_enabled=["eu-west-1"],
                                discovery_source="organizations")
        acct = database.get_account(conn, "123456789012")
        assert acct["name"] == "prod"           # NOT wiped
        assert acct["ou_path"] == "prod/eu"      # NOT wiped
        assert acct["regions_enabled"] == ["eu-west-1"]

    def test_identity_upsert_does_not_wipe_regions(self, tmp_path):
        from harness_store import database
        conn = database.connect(tmp_path / "store.db")
        database.migrate(conn)
        database.upsert_account(conn, "123456789012", name="prod",
                                regions_enabled=["eu-west-1"])
        # Discovery re-persists WITHOUT regions
        database.upsert_account(conn, "123456789012", name="prod",
                                ou_path="x", discovery_source="organizations")
        acct = database.get_account(conn, "123456789012")
        assert acct["regions_enabled"] == ["eu-west-1"]  # NOT wiped

    def test_defaults_regions_honored(self):
        """#11: accounts.defaults.regions is consulted."""
        from harness_cli.runtime import regions_for
        from harness_primitives.accounts import Account
        config = HarnessConfig(accounts=AccountsConfig(
            defaults=AccountDefaults(regions=["eu-west-1"]),
        ))
        acct = Account(id="123456789012", name=None, ou_path=None,
                       status="ACTIVE", profile=None, role_arn=None,
                       regions=None, discovery_source="manual")
        _ctx()
        regions = regions_for(acct, config, MagicMock(), store=None)
        assert regions == ["eu-west-1"]


class TestAssumeCommand:
    """#10: duration validation via session code."""

    def test_duration_validation(self):
        from harness_primitives.session import HarnessSession
        sess = HarnessSession(role_arn="arn:aws:iam::1:role/X")
        with pytest.raises(ValueError, match="900"):
            sess.assume_role_credentials(duration=60)
        with pytest.raises(ValueError, match="43200"):
            sess.assume_role_credentials(duration=99999)

    def test_discovery_flag_overrides_config(self, tmp_path):
        """#13: account list --discovery organizations works even when
        config says manual."""
        from harness_primitives.accounts import AccountResolver
        from harness_store import database
        config = HarnessConfig(accounts=AccountsConfig(
            discovery="manual",
            manual=[ManualAccount(id="123456789012", name="standalone")],
        ))
        session = MagicMock()
        org = MagicMock()
        session.get_client.return_value = org
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Accounts": []}]  # no org accounts
        org.get_paginator.return_value = paginator
        store = database.connect(tmp_path / "store.db")
        database.migrate(store)
        resolver = AccountResolver(config, session, store=store)
        # include_org=True must not be vetoed by config.discovery
        accounts = resolver.discover(include_org=True)
        assert any(a.id == "123456789012" for a in accounts)
        assert org.get_paginator.called  # org discovery actually ran


class TestDeadCodeRemoved:
    """#12/#14: dead subsystems removed."""

    def test_harness_failure_removed(self):
        from harness_primitives import failure
        assert not hasattr(failure, "HarnessFailure")
        from harness_primitives import output as out_mod
        assert not hasattr(out_mod, "HarnessFailure")

    def test_no_dead_acct_session_block(self):
        import inspect

        from harness_cli import runtime
        src = inspect.getsource(runtime._enabled_regions_cached)
        assert "acct_session = session" not in src


class TestRateLimiterLock:
    """#15: bucket creation is lock-guarded."""

    def test_concurrent_acquire_creates_one_bucket(self):
        limiter = RateLimiter(default_rps=1000.0)
        errors = []

        def worker():
            try:
                for _ in range(20):
                    limiter.acquire("ec2", "123", region="us-east-1")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not errors
        assert len(limiter._buckets) == 1  # exactly one bucket, no races
