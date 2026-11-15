"""Tests for the read_only hard safety rail (Phase 26).

The production-rollout guarantee: businesses flagged read_only in
config CANNOT be mutated — not by the CLI, not by a typo, not by a
mis-routed `ask`, not by an eager LLM via MCP. Reads and dry-runs
stay available.
"""

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from harness_cli.main import app
from harness_primitives.failure import HarnessError

runner = CliRunner()


def _config(tmp_path, read_only_at=None, *, level=None, biz="alpha",
            acct_id="111111111111"):
    """Build a config with read_only set at a given level.
    level: 'defaults' | 'business' | 'account' | None"""
    defaults = {"profile": "nonexistent-profile"}
    business = {"name": biz, "profile": biz,
                "discovery": "manual", "accounts": []}
    account = {"id": acct_id, "name": "prod"}
    if level == "defaults":
        defaults["read_only"] = read_only_at
    if level == "business":
        business["read_only"] = read_only_at
    if level == "account":
        account["read_only"] = read_only_at
    business["accounts"].append(account)
    cfg = {
        "inventory": {"sqlite_path": str(tmp_path / "inv.db")},
        "audit": {"sqlite_path": str(tmp_path / "audit.db")},
        "accounts": {
            "discovery": "manual",
            "defaults": defaults,
            "businesses": [business],
            "default_account": "prod",
        },
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


class TestReadOnlyResolution:
    def test_defaults_level(self, tmp_path):
        from harness_cli.runtime import build_stack, get_runtime
        config = get_runtime(str(_config(tmp_path, True, level="defaults")))
        store, session, resolver, executor = build_stack(config)
        try:
            acct = resolver.resolve("prod")
            assert acct.read_only is True
        finally:
            executor.shutdown()

    def test_business_level(self, tmp_path):
        from harness_cli.runtime import build_stack, get_runtime
        config = get_runtime(str(_config(tmp_path, True, level="business")))
        store, session, resolver, executor = build_stack(config)
        try:
            acct = resolver.resolve("prod")
            assert acct.read_only is True
        finally:
            executor.shutdown()

    def test_account_level(self, tmp_path):
        from harness_cli.runtime import build_stack, get_runtime
        config = get_runtime(str(_config(tmp_path, True, level="account")))
        store, session, resolver, executor = build_stack(config)
        try:
            acct = resolver.resolve("prod")
            assert acct.read_only is True
        finally:
            executor.shutdown()

    def test_off_by_default(self, tmp_path):
        from harness_cli.runtime import build_stack, get_runtime
        config = get_runtime(str(_config(tmp_path)))
        store, session, resolver, executor = build_stack(config)
        try:
            acct = resolver.resolve("prod")
            assert acct.read_only is False
        finally:
            executor.shutdown()

    def test_account_override_wins_over_business(self, tmp_path):
        from harness_cli.runtime import build_stack, get_runtime
        # business read_only=True, one account explicitly False
        p = tmp_path / "config.yaml"
        p.write_text(yaml.safe_dump({
            "inventory": {"sqlite_path": str(tmp_path / "i.db")},
            "accounts": {"defaults": {"profile": "x"},
                "businesses": [{
                    "name": "alpha", "profile": "alpha", "read_only": True,
                    "discovery": "manual",
                    "accounts": [
                        {"id": "111111111111", "name": "locked"},
                        {"id": "222222222222", "name": "unlocked",
                         "read_only": False}]}],
                "default_account": "unlocked"}}))
        config = get_runtime(str(p))
        store, session, resolver, executor = build_stack(config)
        try:
            assert resolver.resolve("locked").read_only is True
            assert resolver.resolve("unlocked").read_only is False
        finally:
            executor.shutdown()

    def test_survives_store_roundtrip(self, tmp_path):
        from harness_cli.runtime import build_stack, get_runtime
        config = get_runtime(str(_config(tmp_path, True, level="business")))
        store, session, resolver, executor = build_stack(config)
        try:
            resolver.discover()   # persist
            acct = resolver.resolve("prod")  # read path: store rebuild
            assert acct.read_only is True
        finally:
            executor.shutdown()


class TestReadOnlyEnforcement:
    """Every mutating command must REFUSE with the clear error."""

    def test_ec2_stop_refused(self, tmp_path):
        conf = _config(tmp_path, True, level="business")
        safe_op = MagicMock()
        with patch("harness_plugins.ec2.plugin.EC2Plugin.safe_op", safe_op):
            result = runner.invoke(app, [
                "--config", str(conf),
                "ec2", "stop", "i-123",
                "--account", "prod", "--region", "eu-north-1",
            ])
        assert isinstance(result.exception, HarnessError)
        assert "READ-ONLY" in str(result.exception)
        assert safe_op.call_count == 0       # AWS was never touched

    def test_iam_rotate_keys_refused(self, tmp_path):
        conf = _config(tmp_path, True, level="business")
        rotate = MagicMock()
        with patch("harness_plugins.iam.plugin.IAMPlugin.rotate_keys", rotate):
            result = runner.invoke(app, [
                "--config", str(conf),
                "iam", "rotate-keys", "alice", "--account", "prod",
            ])
        assert isinstance(result.exception, HarnessError)
        assert "READ-ONLY" in str(result.exception)
        assert rotate.call_count == 0

    def test_backup_start_refused(self, tmp_path):
        conf = _config(tmp_path, True, level="account")
        start = MagicMock()
        with patch("harness_plugins.backup.plugin.BackupPlugin.safe_op",
                   start):
            result = runner.invoke(app, [
                "--config", str(conf),
                "backup", "start-backup", "arn:aws:ec2:us-east-1:1:instance/i-1",
                "--vault", "v", "--iam-role", "r",
                "--account", "prod",
            ])
        assert isinstance(result.exception, HarnessError)
        assert start.call_count == 0

    def test_no_audit_row_for_refusal(self, tmp_path):
        """The refusal blocks BEFORE the action — and records nothing
        (nothing happened)."""
        conf = _config(tmp_path, True, level="business")
        with patch("harness_plugins.ec2.plugin.EC2Plugin.safe_op",
                   MagicMock()):
            runner.invoke(app, [
                "--config", str(conf),
                "ec2", "stop", "i-123", "--account", "prod",
                "--region", "eu-north-1",
            ])
        db = tmp_path / "audit.db"
        if db.exists():
            conn = sqlite3.connect(db)
            rows = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()
            assert rows[0] == 0

    def test_reads_still_work(self, tmp_path):
        conf = _config(tmp_path, True, level="business")
        users = MagicMock(return_value=[{"resource_id": "a", "name": "a"}])
        with patch("harness_plugins.iam.plugin.IAMPlugin.list_users", users):
            result = runner.invoke(app, [
                "--config", str(conf),
                "iam", "list-users", "--account", "prod",
            ])
        assert result.exit_code == 0, result.output
        assert users.call_count == 1        # reads unaffected

    def test_dry_run_also_refused_for_ec2_real_ops(self, tmp_path):
        """Even --dry-run is refused for the REAL op commands: the lock
        is unconditional (dry-runs through `ask`/MCP simulations are
        separate and remain available)."""
        conf = _config(tmp_path, True, level="business")
        with patch("harness_plugins.ec2.plugin.EC2Plugin.safe_op",
                   MagicMock()) as m:
            result = runner.invoke(app, [
                "--config", str(conf),
                "ec2", "stop", "i-123", "--account", "prod",
                "--region", "eu-north-1", "--dry-run",
            ])
        assert isinstance(result.exception, HarnessError)
        assert m.call_count == 0


class TestRealCLIExitCode:
    def test_refusal_exits_2_with_clean_stderr(self, tmp_path):
        """The REAL cli path: main() wraps HarnessError → 2-line error,
        exit code 2 (scripts can rely on it)."""
        import shutil
        import subprocess
        harness = shutil.which("harness")
        if not harness:
            pytest.skip("harness console script not installed")
        conf = _config(tmp_path, True, level="business")
        proc = subprocess.run(
            [harness,
             "--config", str(conf),
             "ec2", "stop", "i-123", "--account", "prod",
             "--region", "eu-north-1"],
            capture_output=True, text=True, timeout=60)
        assert proc.returncode == 2
        assert "READ-ONLY" in proc.stderr
        assert "Traceback" not in proc.stderr   # clean error, no stack


class TestReadOnlyViaAsk:
    def test_ask_routes_but_execution_refuses(self, tmp_path):
        """A natural-language request to mutate a locked business is
        routed — and then REFUSED by the same wall."""
        conf = _config(tmp_path, True, level="business")
        with patch("harness_plugins.ec2.plugin.EC2Plugin.safe_op",
                   MagicMock()) as m:
            result = runner.invoke(app, [
                "--config", str(conf),
                "ask", "stop instance i-0abc123456789def0 in prod in eu-north-1",
            ])
        assert isinstance(result.exception, HarnessError)
        assert "READ-ONLY" in str(result.exception)
        assert m.call_count == 0


class TestReadOnlyMcp:
    def test_mcp_dry_run_simulations_still_available(self, tmp_path):
        """MCP safe_op_dry_run SIMULATES only — allowed on read-only
        businesses (it touches nothing; execution is CLI-only anyway)."""
        import asyncio

        import harness_cli.main as cli_main
        from harness_cli.mcp_server import mcp
        cli_main._CTX.update({"config": str(_config(
            tmp_path, True, level="business"))})

        async def call():
            return await mcp.call_tool("safe_op_dry_run", {
                "operation": "ec2:stop", "resource_id": "i-123"})

        simulate = MagicMock(return_value={
            "service": "ec2", "operation": "stop",
            "resource_id": "i-123", "status": "would_execute"})
        with patch("harness_plugins.ec2.plugin.EC2Plugin"
                   ".dry_run_simulate", simulate):
            result = asyncio.run(call())
        payload = json.loads(result[0].text)
        assert payload["simulated"] is True
        cli_main._CTX.update({"config": None})
