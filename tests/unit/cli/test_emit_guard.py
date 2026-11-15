"""Regression: emit() success inside the mutating-command try/except
must NOT become a phantom failure (found in live AWS testing, pass 3).

`emit()` raises typer.Exit(0) after printing results. The mutating
command bodies wrap emit() in `except Exception` — without the
`except typer.Exit: raise` guard, EVERY successful mutation reported:
    Failures (1): ... Exit: 0
plus a false success=False audit row, and exit code 2 instead of 0.
"""

import sqlite3
from unittest.mock import MagicMock, patch

import yaml
from typer.testing import CliRunner

from harness_cli.main import app

runner = CliRunner()


def _config(tmp_path):
    cfg = {
        "inventory": {"sqlite_path": str(tmp_path / "inv.db")},
        "audit": {"sqlite_path": str(tmp_path / "audit.db")},
        "accounts": {
            "discovery": "manual",
            "manual": [{"id": "111111111111", "name": "test-acct"}],
            "defaults": {"profile": "nonexistent-profile"},
        },
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


class TestEmitSuccessNotFailure:
    def test_rotate_keys_success_exits_zero_with_single_audit_row(self, tmp_path):
        """Successful mutating command: exit 0, no 'Failures' block,
        exactly ONE audit row with success=1."""
        conf = _config(tmp_path)
        fake_rotate = MagicMock(return_value={
            "username": "alice",
            "new_access_key": "AKIANEW",
            "secret_location": "/tmp/x.secret",
            "deactivated_count": 1,
            "message": "ok",
        })
        with patch.object(
                __import__("harness_plugins.iam.plugin", fromlist=["IAMPlugin"]).IAMPlugin,
                "rotate_keys", fake_rotate):
            result = runner.invoke(app, [
                "--config", str(conf),
                "iam", "rotate-keys", "alice",
                "--account", "111111111111",
            ])

        assert result.exit_code == 0, result.output
        assert "Failures" not in result.output
        assert "Exit: 0" not in result.output          # the phantom failure
        assert "AKIANEW" in result.output             # the success data

        conn = sqlite3.connect(tmp_path / "audit.db")
        rows = conn.execute(
            "SELECT action, success, dry_run FROM audit_events").fetchall()
        assert rows == [("rotate-keys", 1, 0)]          # one success row

    def test_rotate_keys_failure_still_classified(self, tmp_path):
        """Real failures still work: exit 1/2, failure block present,
        ONE audit row with success=0."""
        conf = _config(tmp_path)

        def boom(self, session, username, **kw):
            raise RuntimeError("simulated AWS failure")

        with patch.object(
                __import__("harness_plugins.iam.plugin", fromlist=["IAMPlugin"]).IAMPlugin,
                "rotate_keys", boom):
            result = runner.invoke(app, [
                "--config", str(conf),
                "iam", "rotate-keys", "alice",
                "--account", "111111111111",
            ])

        assert result.exit_code in (1, 2)
        assert "simulated AWS failure" in result.output
        conn = sqlite3.connect(tmp_path / "audit.db")
        rows = conn.execute(
            "SELECT action, success FROM audit_events").fetchall()
        assert rows == [("rotate-keys", 0)]

    def test_ec2_safe_op_success_exits_zero(self, tmp_path):
        """Same guard in the EC2 runner (start/stop share _run_safe_op)."""
        conf = _config(tmp_path)
        fake_op = MagicMock(return_value={
            "status": "stopped",
            "instances": [{"id": "i-123", "current": "stopping"}],
        })
        with patch.object(
                __import__("harness_plugins.ec2.plugin", fromlist=["EC2Plugin"]).EC2Plugin,
                "safe_op", fake_op):
            result = runner.invoke(app, [
                "--config", str(conf),
                "ec2", "stop", "i-123",
                "--account", "111111111111",
                "--region", "us-east-1",
            ])
        assert result.exit_code == 0, result.output
        assert "Failures" not in result.output
        assert "stopping" in result.output
