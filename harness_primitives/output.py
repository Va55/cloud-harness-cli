"""
Output formatting and partial-failure aggregation.

Exit code convention:
- 0 = all success
- 1 = partial success (some succeeded, some failed)
- 2 = fatal (config error) or ALL targets failed — scripts can tell
      "everything broke" apart from "one region failed"

stdout = data only, stderr = diagnostics/tracebacks (when --verbose)
Quiet mode suppresses success output entirely (errors still print).

Table rendering: success payloads are heterogeneous (lists of resource
dicts, key-value dicts, nested per-region results), so the renderer
auto-detects the shape:
- list[dict]        → auto columns from the union of keys
- dict              → key/value rows
- PartialResult     → recursive (region sweeps)
- anything else     → str()
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass
class WarningMsg:
    account_id: str
    message: str


@dataclass
class FailureMsg:
    account_id: str
    region: str | None = None
    service: str | None = None
    resource: str | None = None
    error_code: str = ""
    message: str = ""


@dataclass
class PartialResult:
    """Result of an operation across multiple accounts/regions."""
    success: dict[str, Any] = field(default_factory=dict)
    failures: list[FailureMsg] = field(default_factory=list)
    warnings: list[WarningMsg] = field(default_factory=list)

    @property
    def total_failure_count(self) -> int:
        """Failures here PLUS those nested in per-account/per-region
        sub-results. A region-level AccessDenied inside one account's
        sub-result is still a failure — it must not exit 0.
        """
        n = len(self.failures)
        for v in self.success.values():
            if isinstance(v, PartialResult):
                n += v.total_failure_count
        return n

    @property
    def is_all_success(self) -> bool:
        return self.total_failure_count == 0

    @property
    def failure_count(self) -> int:
        return len(self.failures)

    @property
    def success_count(self) -> int:
        return len(self.success)

    @property
    def exit_code(self) -> int:
        if self.is_all_success:
            return 0
        if self.success_count == 0:
            return 2  # everything failed — not a "partial" result
        return 1  # partial failure (incl. nested region failures)


# ─── JSON safety ─────────────────────────────────────────────

def _json_safe(obj: Any) -> Any:
    """Serializer for types json.dumps cannot handle natively."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(str(o) for o in obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)  # last resort: never crash on output


# ─── Table rendering ──────────────────────────────────────────

_CELL_WIDTH = 28          # max chars per table cell
_MAX_TABLE_ROWS = 200     # guard against 10k-instance dumps


def _cell(value: Any) -> str:
    """Render any value as a bounded table cell."""
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        s = json.dumps(value, default=_json_safe)
    else:
        s = str(value)
    s = s.replace("\n", " ").strip()
    return s if len(s) <= _CELL_WIDTH else s[:_CELL_WIDTH - 3] + "..."


def _table_from_rows(rows: list[dict], indent: str = "") -> list[str]:
    """Auto-column table from a list of dicts (union of keys)."""
    if not rows:
        return [f"{indent}(no results)"]
    keys: list[str] = []
    for row in rows:
        for k in row:
            if k != "raw" and k not in keys:
                # 'raw' = full API payload: stored for inventory/JSON,
                # never a table column (display noise, pass-3 fix)
                keys.append(k)
    if not keys:
        return [f"{indent}(no results)"]
    shown = rows[:_MAX_TABLE_ROWS]
    widths = {}
    for k in keys:
        cells = [_cell(r.get(k)) for r in shown]
        widths[k] = min(max(len(k), *(len(c) for c in cells)) if cells else len(k),
                        _CELL_WIDTH)
    lines = [indent + "  ".join(k.ljust(widths[k]) for k in keys)]
    lines.append(indent + "  ".join("-" * widths[k] for k in keys))
    for r in shown:
        lines.append(indent + "  ".join(
            _cell(r.get(k)).ljust(widths[k])[:widths[k]] for k in keys))
    if len(rows) > _MAX_TABLE_ROWS:
        lines.append(f"{indent}... ({len(rows) - _MAX_TABLE_ROWS} more rows)")
    return lines


def _render_value(value: Any, indent: str = "") -> list[str]:
    """Render one success payload as table lines."""
    if isinstance(value, PartialResult):
        lines = []
        for key, inner in value.success.items():
            lines.append(f"{indent}{key}:")
            lines.extend(_render_value(inner, indent + "  "))
        for f in value.failures:
            lines.append(f"{indent}FAIL [{f.region or '-'}]: "
                         f"{f.error_code} {f.message[:60]}")
        return lines or [f"{indent}(no results)"]
    if isinstance(value, list):
        if value and all(isinstance(v, dict) for v in value):
            return _table_from_rows(value, indent)
        return [f"{indent}{_cell(v)}" for v in value] or [f"{indent}(no results)"]
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if k == "raw":
                continue  # full API payload: stored for inventory/JSON,
                          # skipped in tables (display noise, pass-3 fix)
            if isinstance(v, (dict, list)) and v:
                out.append(f"{indent}{k}:")
                out.extend(_render_value(v, indent + "  "))
            else:
                out.append(f"{indent}{k:<20} {_cell(v)}")
        return out or [f"{indent}(no results)"]
    return [f"{indent}{_cell(value)}"]


def format_output(result: PartialResult, fmt: str = "table",
                  verbose: bool = False, max_rows: int = 1000) -> str:
    """Format partial result for display.

    verbose: full failure messages instead of truncated ones.
    """
    del max_rows  # row capping handled per-block in _render_value

    if fmt == "json":
        return json.dumps({
            "status": ("all_failed" if result.total_failure_count and
                       not result.success
                       else "partial_failure" if result.total_failure_count
                       else "success"),
            "success_count": result.success_count,
            "failure_count": result.total_failure_count,
            "warning_count": len(result.warnings),
            "success": result.success,
            "failures": [f.__dict__ for f in result.failures],
            "warnings": [w.message for w in result.warnings],
        }, indent=2, default=_json_safe)

    if fmt == "table":
        lines = []
        if result.success:
            for key, data in result.success.items():
                lines.append(key)
                lines.extend(_render_value(data, indent="  "))
        else:
            lines.append("(no results)")
        if result.failures:
            lines.append("")
            lines.append(f"Failures ({result.failure_count}):")
            for f in result.failures:
                loc = " @ ".join(x for x in (f.region, f.service) if x) or "-"
                msg = f.message if verbose else f.message[:70]
                lines.append(f"  {f.account_id} [{loc}] {f.error_code}: {msg}")
        for w in result.warnings:
            lines.append(f"  [WARN] {w.message}")
        return "\n".join(lines)

    if fmt == "yaml":
        try:
            import yaml
            return yaml.dump({
                "status": ("all_failed" if result.total_failure_count and
                           not result.success
                           else "partial_failure" if result.total_failure_count
                           else "success"),
                "success_count": result.success_count,
                "failure_count": result.total_failure_count,
                "success": result.success,
                "failures": [f.__dict__ for f in result.failures],
                "warnings": [w.message for w in result.warnings],
            }, default_flow_style=False)
        except ImportError:
            return format_output(result, "text", verbose=verbose)

    # text fallback
    return (f"Success: {result.success_count}, "
            f"Failures: {result.failure_count}")
