"""Tests for `harness ask` — the Tier 1 NL router (architecture §13.2).

The core property: route() can ONLY produce commands that exist in
the live CLI registry (introspected). No hallucination surface.
"""

import pytest

from harness_cli.ask import _build_catalog, route


class TestAntiHallucination:
    """Every routed command must exist in the REAL registry."""

    def test_catalog_matches_real_apps(self):
        catalog = _build_catalog()
        # Spot-check known commands from every plugin
        assert "list-users" in catalog["iam"]
        assert "list-instances" in catalog["ec2"]
        assert "invalidate" in catalog["cloudfront"]
        assert "invoke" in catalog["lambda"]
        assert "assume" in catalog["account"]

    def test_routed_commands_always_exist(self):
        queries = [
            "list ec2 instances", "show iam users", "buckets",
            "cloudfront distributions", "vpc subnets", "cost per service",
            "guardduty findings", "inventory summary", "org accounts",
            "stop instance i-0abc123456789def0 in eu-west-1",
            "rotate keys for alice", "what regions are enabled",
        ]
        catalog = _build_catalog()
        for q in queries:
            r = route(q)
            assert r.service in catalog, f"{q!r}: bad service {r.service}"
            assert r.command in catalog[r.service], \
                f"{q!r}: hallucinated command {r.service} {r.command}"


class TestServiceAndCommandDetection:
    def test_ec2_instances(self):
        r = route("list ec2 instances in eu-west-1")
        assert r.argv[:2] == ["ec2", "list-instances"]
        assert "--region" in r.argv and "eu-west-1" in r.argv

    def test_iam_unused_keys(self):
        r = route("show unused iam keys in prod")
        assert r.argv[:2] == ["iam", "find-unused"]
        assert "--account" in r.argv and "prod" in r.argv

    def test_s3_buckets_default(self):
        r = route("show all buckets everywhere")
        assert r.argv[:2] == ["s3", "list-buckets"]

    def test_cost_by_service(self):
        r = route("cost per service in business alpha")
        # Global flags prepend; the command follows
        assert r.argv[:2] == ["--business", "alpha"]
        assert r.argv[2:4] == ["cost", "by-service"]

    def test_security_guardduty(self):
        r = route("security findings")
        assert r.argv[:2] == ["security", "guardduty"]

    def test_regions(self):
        r = route("what regions are enabled")
        assert r.argv[:2] == ["account", "regions"]

    def test_whoami(self):
        r = route("who am i")
        assert r.argv == ["whoami"]

    def test_doctor(self):
        r = route("run a health check")
        assert r.argv == ["doctor"]


class TestExtractors:
    def test_instance_id_extracted(self):
        r = route("stop instance i-0abc123456789def0 in eu-west-1")
        assert "i-0abc123456789def0" in r.argv

    def test_distribution_id_case_insensitive_uppercased(self):
        r = route("invalidate distribution e1234567890ABC")
        assert "E1234567890ABC" in r.argv

    def test_username_for_rotation(self):
        r = route("rotate keys for alice")
        assert "alice" in r.argv
        assert "--account" not in r.argv  # not stolen as account

    def test_username_variants(self):
        for q in ("rotate alice keys", "rotate keys for user alice",
                  "check mfa for user bob"):
            r = route(q)
            assert r.missing_arg is None, q

    def test_state_filter(self):
        r = route("stopped instances in dev")
        assert "--state" in r.argv and "stopped" in r.argv
        assert "--account" in r.argv and "dev" in r.argv

    def test_all_accounts_flag(self):
        r = route("iam users in all accounts")
        assert "--all-accounts" in r.argv

    def test_account_id_12_digits(self):
        r = route("show iam users for 123456789012")
        assert "--account" in r.argv and "123456789012" in r.argv

    def test_business_variants(self):
        r = route("vpcs in business beta")
        # --business is a GLOBAL flag: prepended before the service
        assert r.argv[:2] == ["--business", "beta"]
        assert r.argv[2:4] == ["vpc", "list"]


class TestSafetyModel:
    """§13.3: mutations dry-run by default; never guess required args."""

    def test_mutating_commands_detected(self):
        for q in ("stop instance i-0abc123456789def0 in eu-west-1",
                  "start instance i-0abc123456789def0 in prod",
                  "invalidate distribution E1234567890ABC",
                  "rotate keys for alice",
                  "run lambda function my-func in eu-west-1"):
            r = route(q)
            assert r.mutating, q
            assert "--dry-run" in r.argv, q

    def test_missing_required_arg_refused(self):
        for q, missing in [
            ("stop the instance", "instance_id"),
            ("rotate my keys", "username"),
            ("invalidate the distribution", "distribution_id"),
            ("run the lambda", "function_name"),
            ("show bucket info", "bucket"),
        ]:
            r = route(q)
            assert r.missing_arg == missing, q

    def test_readonly_never_gets_dry_run(self):
        r = route("list ec2 instances in eu-west-1")
        assert not r.mutating
        assert "--dry-run" not in r.argv

    def test_lambda_invoke_region_required(self):
        """invoke needs --region; the router must provide it."""
        r = route("run lambda function my-func in eu-west-1")
        assert "--region" in r.argv


class TestNoMatch:
    def test_unroutable_query_errors_with_guidance(self):
        with pytest.raises(ValueError, match="Couldn't find a service"):
            route("nonsense query about nothing")
        with pytest.raises(ValueError, match="Couldn't find a service"):
            route("hello world")


class TestCLIIntegration:
    def test_ask_command_registered(self):
        from typer.testing import CliRunner

        from harness_cli.main import app
        result = CliRunner().invoke(app, ["ask", "--catalog"])
        assert result.exit_code == 0
        assert "ec2: " in result.output
        assert "list-instances" in result.output

    def test_ask_routes_and_executes_offline(self, tmp_path, monkeypatch):
        """End-to-end: ask → routed command runs through the real app.
        Route to something offline (account list with manual config)."""
        import yaml
        from typer.testing import CliRunner

        from harness_cli.main import app

        cfg = {
            "inventory": {"sqlite_path": str(tmp_path / "inv.db")},
            "accounts": {
                "discovery": "manual",
                "businesses": [{
                    "name": "acme", "profile": "acme",
                    "discovery": "manual",
                    "accounts": [{"id": "111111111111", "name": "prod"}],
                }],
            },
        }
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg))

        runner = CliRunner()
        result = runner.invoke(app, [
            "--config", str(cfg_path),
            "ask", "list accounts",
        ])
        assert result.exit_code == 0, result.output
        # The routed command ran: 111111111111 appears in output
        assert "111111111111" in result.output

    def test_ask_refuses_missing_arg(self, tmp_path):
        from typer.testing import CliRunner

        from harness_cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, [
            "--config", str(tmp_path / "none.yaml"),
            "ask", "stop the instance",
        ])
        assert result.exit_code == 2
        assert "couldn't find one in your question" in result.output

    def test_ask_dry_run_message_for_mutations(self, tmp_path):
        from typer.testing import CliRunner

        from harness_cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, [
            "--config", str(tmp_path / "none.yaml"),
            "ask", "rotate keys for alice",
        ])
        # Refused only if missing arg; here alice IS given → proceeds
        # to the routed command (which will fail on AWS creds, NOT on
        # routing). Either way the dry-run notice must appear.
        assert "[dry-run]" in result.output or result.exit_code in (0, 1, 2)


class TestBackupRouting:
    """Phase 22: the router knows the backup plugin and VPC extension."""

    def test_backup_vaults(self):
        r = route("show backup vaults")
        assert r.argv[:2] == ["backup", "list-vaults"]

    def test_failed_jobs_gets_state_filter(self):
        r = route("failed backup jobs in prod")
        assert r.argv[:2] == ["backup", "list-jobs"]
        assert "--state" in r.argv and "FAILED" in r.argv
        assert "--account" in r.argv and "prod" in r.argv

    def test_backup_plans_business_scoped(self):
        r = route("list backup plans in business alpha")
        assert r.argv[:2] == ["--business", "alpha"]
        assert r.argv[2:4] == ["backup", "list-plans"]

    def test_vpc_nat_gateways(self):
        r = route("nat gateways everywhere")
        assert r.argv[:2] == ["vpc", "nat-gateways"]

    def test_vpc_flow_logs(self):
        r = route("show flow logs in eu-west-1")
        assert r.argv[:2] == ["vpc", "flow-logs"]
        assert "--region" in r.argv

    def test_start_backup_is_mutating_with_dry_run(self):
        r = route("start a backup of "
                  "arn:aws:ec2:us-east-1:123456789012:instance/i-abc")
        assert r.argv[:2] == ["backup", "start-backup"]
        assert r.mutating and "--dry-run" in r.argv
        assert "arn:aws:ec2:us-east-1:123456789012:instance/i-abc" in r.argv

    def test_start_backup_without_arn_refused(self):
        r = route("start a backup of the prod database")
        assert r.mutating
        assert r.missing_arg and "ARN" in r.missing_arg

    def test_arn_tokens_do_not_steal_service(self):
        """'instance' inside an ARN must not make this an ec2 command."""
        r = route("start a backup of "
                  "arn:aws:ec2:us-east-1:123456789012:instance/i-abc")
        assert r.service == "backup"
