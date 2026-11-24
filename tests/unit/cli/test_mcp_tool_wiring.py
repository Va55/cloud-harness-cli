"""Regression: every plugin method the MCP server calls must exist.

Bug class this guards: 'CostPlugin object has no attribute total_cost'
(report-harness-funk-20261115) — a registered MCP tool whose body
references a plugin method that doesn't exist. The registration test
(ToolRegistry / test_mcp_server) only checks tool NAMES, so this
test introspects the server source and validates every
XPlugin().method(...) call against the live plugin classes.

No AWS access needed: purely static, runs in milliseconds.
"""

import importlib
import re
from pathlib import Path

import pytest

# plugin class -> module (mirrors mcp_server's own imports)
PLUGIN_MODULES = {
    "EC2Plugin": "harness_plugins.ec2.plugin",
    "S3Plugin": "harness_plugins.s3.plugin",
    "IAMPlugin": "harness_plugins.iam.plugin",
    "VPCPlugin": "harness_plugins.vpc.plugin",
    "BackupPlugin": "harness_plugins.backup.plugin",
    "CostPlugin": "harness_plugins.cost.plugin",
    "InventoryPlugin": "harness_plugins.inventory.plugin",
    "SecurityPlugin": "harness_plugins.security.plugin",
    "OrgPlugin": "harness_plugins.org.plugin",
    "CloudFrontPlugin": "harness_plugins.cloudfront.plugin",
    "Route53Plugin": "harness_plugins.route53.plugin",
    "LambdaPlugin": "harness_plugins.aws_lambda.plugin",
}


def _mcp_server_source() -> str:
    src = Path("harness_cli/mcp_server.py")
    if not src.exists():  # run from repo root, or anywhere: try package path
        import harness_cli
        src = Path(harness_cli.__file__).parent / "mcp_server.py"
    return src.read_text()


def test_every_mcp_plugin_call_exists() -> None:
    """All XPlugin().method(...) references in mcp_server resolve."""
    source = _mcp_server_source()
    calls = set(re.findall(r"(\w+Plugin)\(\)\.(\w+)\(", source))
    assert calls, "no plugin calls found in mcp_server — regex rot?"

    missing = []
    for plugin_cls, method in sorted(calls):
        assert plugin_cls in PLUGIN_MODULES, (
            f"unknown plugin class {plugin_cls} in mcp_server — "
            "update PLUGIN_MODULES in this test")
        cls = getattr(importlib.import_module(PLUGIN_MODULES[plugin_cls]),
                      plugin_cls)
        if not hasattr(cls, method):
            available = sorted(m for m in dir(cls)
                               if not m.startswith("_"))
            missing.append(
                f"{plugin_cls}.{method} "
                f"(available: {', '.join(available)})")

    assert not missing, (
        "MCP server calls nonexistent plugin methods:\n  "
        + "\n  ".join(missing))


def test_mcp_server_imports_and_registers_24_tools() -> None:
    """The tool surface is live-importable and has exactly 26 tools."""
    import harness_cli.mcp_server as mcp_server

    server = mcp_server.mcp
    tools = server._tool_manager.list_tools()  # FastMCP internal API
    names = sorted(t.name for t in tools)

    assert len(names) == 26, f"expected 26 MCP tools, got {len(names)}"
    assert "cost_total" in names
    # the previously broken tool must be among them
    assert "safe_op_dry_run" in names


def test_cost_total_wiring_matches_plugin() -> None:
    """Direct guard on the fixed bug: cost_total -> CostPlugin.total."""

    from harness_plugins.cost.plugin import CostPlugin

    source = _mcp_server_source()
    m = re.search(r"def cost_total\(.*?\n(.*?)(?=\n\n|\n@|\Z)",
                 source, re.S)
    assert m, "cost_total not found in mcp_server source"
    body = m.group(1)
    referenced = re.findall(r"CostPlugin\(\)\.(\w+)\(", body)
    assert referenced, "cost_total no longer calls CostPlugin?"
    for method in referenced:
        assert hasattr(CostPlugin, method), (
            f"cost_total calls CostPlugin.{method} — does not exist "
            f"(available: "
            f"{sorted(x for x in dir(CostPlugin) if not x.startswith('_'))})"
            ")")


@pytest.mark.parametrize("plugin_cls,module", sorted(PLUGIN_MODULES.items()))
def test_plugin_classes_importable(plugin_cls: str, module: str) -> None:
    """Every plugin class the MCP server could reference imports cleanly."""
    mod = importlib.import_module(module)
    assert hasattr(mod, plugin_cls), (
        f"{module} has no class {plugin_cls}")
