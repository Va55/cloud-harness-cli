"""Tests for output formatting and partial-failure semantics.

Verifies:
- Exit codes: 0 = all success, 1 = partial failure
- JSON structure for --output json
- Table rendering
- Failure/warning counting
"""

import json

import pytest

from harness_primitives.output import (
    FailureMsg,
    PartialResult,
    WarningMsg,
    format_output,
)


@pytest.fixture
def all_success():
    return PartialResult(success={"123456789012": {"count": 5}})


@pytest.fixture
def partial():
    return PartialResult(
        success={"123456789012": {"count": 5}},
        failures=[FailureMsg(
            account_id="987654321098",
            region="eu-west-1",
            service="ec2",
            error_code="AccessDenied",
            message="SCP denied",
        )],
        warnings=[WarningMsg(account_id="111", message="Region disabled")],
    )


class TestExitCodes:
    def test_all_success_exit_0(self, all_success):
        assert all_success.exit_code == 0
        assert all_success.is_all_success is True

    def test_partial_failure_exit_1(self, partial):
        assert partial.exit_code == 1
        assert partial.is_all_success is False

    def test_counts(self, partial):
        assert partial.success_count == 1
        assert partial.failure_count == 1


class TestJSONFormat:
    def test_json_is_valid_and_parsable(self, partial):
        out = format_output(partial, "json")
        data = json.loads(out)
        assert data["status"] == "partial_failure"
        assert data["success_count"] == 1
        assert data["failure_count"] == 1
        assert data["warning_count"] == 1

    def test_json_success_status(self, all_success):
        data = json.loads(format_output(all_success, "json"))
        assert data["status"] == "success"

    def test_json_failure_structure(self, partial):
        data = json.loads(format_output(partial, "json"))
        failure = data["failures"][0]
        assert failure["account_id"] == "987654321098"
        assert failure["region"] == "eu-west-1"
        assert failure["service"] == "ec2"
        assert failure["error_code"] == "AccessDenied"

    def test_json_contains_no_stderr_leakage(self, partial):
        """stdout must be pure data — no diagnostics mixed in."""
        out = format_output(partial, "json")
        # If it parses as JSON from char 0, stdout is clean
        json.loads(out)


class TestTableFormat:
    def test_table_shows_success_key_and_data(self, partial):
        """The old renderer truncated data to 30 chars of repr —
        table output must show the account key AND readable data."""
        out = format_output(partial, "table")
        assert "123456789012" in out          # success key
        assert "count" in out                # actual data, not a repr fragment

    def test_table_shows_failures(self, partial):
        out = format_output(partial, "table")
        assert "Failures (1):" in out
        assert "AccessDenied" in out
        assert "987654321098" in out          # failing account visible

    def test_table_renders_list_of_dicts_as_columns(self):
        from harness_primitives.output import PartialResult
        r = PartialResult()
        r.success["acct"] = [
            {"UserName": "alice", "Arn": "arn:aws:iam::1:user/alice"},
            {"UserName": "bob", "Arn": "arn:aws:iam::1:user/bob"},
        ]
        out = format_output(r, "table")
        assert "UserName" in out
        assert "alice" in out
        assert "bob" in out


class TestTextFormat:
    def test_text_fallback(self, partial):
        out = format_output(partial, "text")
        assert "Success: 1" in out
        assert "Failures: 1" in out
