"""The MCP SDK is an optional extra: its absence must be actionable.

Regression guard: `mcp` was not declared in pyproject at all, so a fresh
install produced a bare ImportError traceback for a headline feature. It
is now the `[mcp]` extra, pinned below 2.0 because this code imports
`mcp.server.fastmcp`, which the 2.x line does not provide.
"""

import sys

import pytest
import typer

import harness_cli.main as cli_main


def test_serve_mcp_without_sdk_exits_with_guidance(monkeypatch, capsys):
    """A missing SDK must say how to fix it, and exit 2 — not traceback."""
    monkeypatch.setitem(sys.modules, "harness_cli.mcp_server", None)

    with pytest.raises(typer.Exit) as excinfo:
        cli_main.serve_mcp()

    assert excinfo.value.exit_code == 2
    err = capsys.readouterr().err
    assert "cloud-harness-cli[mcp]" in err
    assert "optional dependency" in err


def test_mcp_extra_is_declared_with_pin():
    """pyproject must declare the extra and exclude the 2.x SDK line."""
    from pathlib import Path

    text = Path("pyproject.toml").read_text()
    assert "[project.optional-dependencies]" in text
    assert "mcp = [" in text
    assert "<2" in text, "the 2.x MCP SDK does not provide mcp.server.fastmcp"


def test_server_imports_and_registers_24_tools():
    """With the SDK present the surface is intact."""
    from harness_cli.mcp_server import mcp

    assert len(mcp._tool_manager.list_tools()) == 24
