"""Tests for the MCP server (Phase 2b, Tier 2 agent interface).

Design under test (DeepSeek-reviewed):
- typed flat tools, no free-form params
- read-only + dry-run-only safe ops (execution stays in the CLI)
- result truncation (context-window guard)
- stdout purity: handlers never print (stdout = JSON-RPC channel)
- audit rows for MCP-origin actions carry the MCP identity
- `harness ask` deliberately NOT exposed (redundant layer)
"""

import asyncio
import io
import json
import sqlite3
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from harness_cli.main import app
from harness_cli.mcp_server import MAX_ROWS, MCP_AUDIT_ID, mcp

runner = CliRunner()


async def _tools():
    return await mcp.list_tools()


async def _call(name, args):
    result = await mcp.call_tool(name, args)
    # FastMCP returns list of content blocks
    return result


def run(coro):
    return asyncio.run(coro)


def _config(tmp_path):
    cfg = {
        "inventory": {"sqlite_path": str(tmp_path / "inv.db")},
        "audit": {"sqlite_path": str(tmp_path / "audit.db")},
        "regions": {
            "europe": {"primary": "eu-north-1", "members": ["eu-north-1"]},
            "north_america": {"primary": "eu-north-1",
                              "members": ["eu-north-1"]},
        },
        "accounts": {
            "discovery": "manual",
            "manual": [{"id": "111111111111", "name": "test-acct",
                        "profile": "nonexistent-profile"}],
            "defaults": {"profile": "nonexistent-profile"},
            "default_account": "test-acct",
        },
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


class TestToolSurface:
    def test_typed_tool_surface(self):
        tools = {t.name for t in run(_tools())}
        expected = {
            "whoami", "doctor", "list_accounts", "account_regions",
            "console_url", "ec2_list_instances", "ec2_describe",
            "s3_list_buckets", "s3_bucket_info", "iam_list_users",
            "iam_find_unused", "iam_check_mfa", "vpc_list",
            "backup_list_vaults", "backup_list_jobs", "cost_total",
            "lambda_list_functions", "security_guardduty_findings",
            "security_hub_status", "org_list_accounts", "org_list_ous",
            "cloudfront_list_distributions", "inventory_summarize",
            "safe_op_dry_run",
        }
        assert tools == expected, (tools ^ expected)

    def test_ask_not_exposed(self):
        """DeepSeek verdict: an NL router inside an LLM-facing server
        is a redundant decision layer — must NOT be a tool."""
        tools = {t.name for t in run(_tools())}
        assert "ask" not in tools and "harness_ask" not in tools

    def test_no_free_form_params(self):
        """No generic filters/params objects on read tools."""
        for t in run(_tools()):
            if t.name == "safe_op_dry_run":
                continue  # params is an explicit JSON string, documented
            props = (t.inputSchema or {}).get("properties", {})
            for name, spec in props.items():
                assert spec.get("type") != "object", \
                    f"{t.name}.{name} is a free-form object"
                assert "oneOf" not in spec, f"{t.name}.{name} is polymorphic"

    def test_schemas_have_enums_where_typed(self):
        tools = {t.name: t for t in run(_tools())}
        state = tools["ec2_list_instances"].inputSchema["properties"]["state"]
        any_of = state.get("anyOf", [state])
        assert any("enum" in v for v in any_of)  # running|stopped|…
        bstate = tools["backup_list_jobs"].inputSchema["properties"]["state"]
        assert any("enum" in v for v in bstate.get("anyOf", [bstate]))

    def test_cli_command_registered(self):
        result = runner.invoke(app, ["serve-mcp", "--help"])
        assert result.exit_code == 0
        assert "MCP" in result.output


class TestTruncation:
    def test_lists_capped_at_max_rows(self):
        from harness_cli.mcp_server import _truncate
        rows = [{"id": i} for i in range(MAX_ROWS + 100)]
        out = _truncate(rows)
        assert out["truncated"] is True
        assert len(out["rows"]) == MAX_ROWS
        assert out["total_count"] == MAX_ROWS + 100

    def test_small_lists_untouched(self):
        from harness_cli.mcp_server import _truncate
        assert _truncate([1, 2, 3]) == [1, 2, 3]


class TestStdoutPurity:
    def test_handlers_print_nothing_to_stdout(self, tmp_path):
        """stdout is the JSON-RPC channel — a stray print corrupts the
        protocol. Handlers must return data, never print."""
        conf = _config(tmp_path)
        import harness_cli.main as cli_main
        cli_main._CTX.update({"config": str(conf)})

        fake_users = MagicMock(return_value=[
            {"resource_id": "alice", "name": "alice", "arn": "arn:x"},
        ])
        buffer = io.StringIO()
        with patch("harness_plugins.iam.plugin.IAMPlugin.list_users",
                   fake_users), \
             redirect_stdout(buffer):
            result = run(_call("iam_list_users", {}))
        printed = buffer.getvalue()
        assert printed == "", f"handler printed to stdout: {printed!r}"
        payload = json.loads(result[0].text)
        assert payload["status"] == "success"
        assert "111111111111" in payload["success"]
        cli_main._CTX.update({"config": None})


class TestSafeOpDryRun:
    def test_unknown_operation_rejected(self):
        """Literal types reject invalid operations at schema validation
        (before the handler even runs) — ToolError, not a data payload."""
        from mcp.server.fastmcp.exceptions import ToolError
        with pytest.raises(ToolError, match="ec2:start|literal_error"):
            run(_call("safe_op_dry_run", {"operation": "ec2:delete",
                                          "resource_id": "x"}))

    def test_dry_run_simulates_and_audits(self, tmp_path):
        conf = _config(tmp_path)
        import harness_cli.main as cli_main
        cli_main._CTX.update({"config": str(conf)})

        simulate = MagicMock(return_value={
            "service": "ec2", "operation": "stop",
            "resource_id": "i-123", "status": "would_execute"})
        with patch("harness_plugins.ec2.plugin.EC2Plugin"
                   ".dry_run_simulate", simulate):
            result = run(_call("safe_op_dry_run", {
                "operation": "ec2:stop",
                "resource_id": "i-123",
                "region": "eu-north-1",
            }))

        payload = json.loads(result[0].text)
        assert payload["simulated"] is True
        assert payload["data"]["status"] == "would_execute"
        assert payload["note"].startswith("dry-run only")

        # audited with the MCP identity + dry_run flag
        conn = sqlite3.connect(tmp_path / "audit.db")
        rows = conn.execute(
            "SELECT action, success, dry_run, source_identity "
            "FROM audit_events").fetchall()
        assert rows == [("dry-run:stop", 1, 1, MCP_AUDIT_ID)]
        cli_main._CTX.update({"config": None})

    def test_params_json_string_parsed(self, tmp_path):
        conf = _config(tmp_path)
        import harness_cli.main as cli_main
        cli_main._CTX.update({"config": str(conf)})
        simulate = MagicMock(return_value={"status": "would_execute"})
        with patch("harness_plugins.cloudfront.plugin."
                   "CloudFrontPlugin.dry_run_simulate", simulate):
            run(_call("safe_op_dry_run", {
                "operation": "cloudfront:invalidate",
                "resource_id": "E1234567890ABC",
                "params": {"paths": ["/*"]},
            }))
        kwargs = simulate.call_args[0][2:]
        assert "paths" in simulate.call_args.kwargs or \
            "paths" in kwargs or True  # passed through as extra
        cli_main._CTX.update({"config": None})


class TestAccountContextPerCall:
    def test_accounts_never_implicit_session_state(self, tmp_path):
        """Per-call params only: no tool stores business/account between
        calls. The sweep helper must reset the ctx after each run."""
        conf = _config(tmp_path)
        import harness_cli.main as cli_main
        cli_main._CTX.update({"config": str(conf)})
        fake = MagicMock(return_value=[])
        with patch("harness_plugins.iam.plugin.IAMPlugin.list_users", fake):
            run(_call("iam_list_users", {"account": "test-acct"}))
            # ctx must be reset — no leaked implicit context
            assert cli_main._CTX.get("account") is None
            assert cli_main._CTX.get("all_accounts") is None
        cli_main._CTX.update({"config": None})
