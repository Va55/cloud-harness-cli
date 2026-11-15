"""Tests for the audit fixes: role assumption, profile precedence,
region detection, IAM pipeline migration."""

from unittest.mock import MagicMock, patch

import pytest

from harness_primitives.config import AccountDefaults
from harness_primitives.session import FALLBACK_REGION, HarnessSession


class TestRoleArnTemplate:
    """Audit fix #1: assumed roles — org accounts need a role-name convention."""

    def test_template_expands_account_id(self):
        defaults = AccountDefaults(
            role_arn="arn:aws:iam::{account_id}:role/HarnessAccess"
        )
        assert defaults.role_arn_for("123456789012") == \
            "arn:aws:iam::123456789012:role/HarnessAccess"

    def test_static_arn_unchanged(self):
        defaults = AccountDefaults(role_arn="arn:aws:iam::999:role/Fixed")
        assert defaults.role_arn_for("123456789012") == "arn:aws:iam::999:role/Fixed"

    def test_no_arn_returns_none(self):
        assert AccountDefaults().role_arn_for("123456789012") is None

    def test_template_without_account_returns_none(self):
        defaults = AccountDefaults(
            role_arn="arn:aws:iam::{account_id}:role/HarnessAccess"
        )
        assert defaults.role_arn_for(None) is None


class TestSessionRoleAssumption:
    """Audit fix #1: assume_role must actually be wired into get_session."""

    def test_no_role_uses_base_session(self):
        sess = HarnessSession(profile="default")
        assert sess.is_cross_account() is False

    def test_role_flag_reports_cross_account(self):
        sess = HarnessSession(role_arn="arn:aws:iam::123:role/X")
        assert sess.is_cross_account() is True

    def test_get_session_assumes_role_when_configured(self):
        """get_session() must call STS AssumeRole — this was the critical gap."""
        sess = HarnessSession(profile="default",
                              role_arn="arn:aws:iam::123:role/X",
                              external_id="harness-123",
                              account_id="123456789012",
                              region="eu-west-1")

        fake_sts = MagicMock()
        fake_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA_TEMP",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
                "Expiration": __import__("datetime").datetime.now(),
            }
        }
        # No AWS profile exists in CI — patch the base session lookup
        with patch.object(HarnessSession, "get_base_session",
                          return_value=MagicMock(region_name="eu-west-1")), \
             patch("harness_primitives.session.create_botocore_client",
                   return_value=fake_sts):
            effective = sess.get_session()

        # AssumeRole must have been called with full attribution
        assert fake_sts.assume_role.called
        kwargs = fake_sts.assume_role.call_args.kwargs
        assert kwargs["RoleArn"] == "arn:aws:iam::123:role/X"
        assert kwargs["ExternalId"] == "harness-123"
        assert "SourceIdentity" in kwargs
        assert kwargs["SourceIdentity"].startswith("harness-")
        # STS-valid: only [\w+=,.@-] (no colons — pass-3 live fix)
        import re as _re
        assert _re.fullmatch(r"[\w+=,.@-]{2,64}", kwargs["SourceIdentity"])
        assert kwargs["RoleSessionName"].startswith("harness-123456789012")
        # Must be a real session with temp creds
        assert effective is not None

    def test_role_session_name_under_sts_limit(self):
        sess = HarnessSession(account_id="1" * 12, profile="x")
        assert len(sess._role_session_name()) <= 64

    def test_get_sts_client_uses_base_session(self):
        """Assuming a role must not require an already-assumed session."""
        sess = HarnessSession(role_arn="arn:aws:iam::123:role/X")
        base = MagicMock(region_name="us-east-1")
        with patch.object(HarnessSession, "get_base_session", return_value=base), \
             patch("harness_primitives.session.create_botocore_client") as mk:
            mk.return_value = MagicMock()
            sess.get_sts_client()
        # Called with the BASE session, not the effective one
        assert mk.call_args.args[0] is base

    def test_region_fallback_when_session_has_none(self):
        """Audit fix #13: missing region must not raise NoRegionError."""
        sess = HarnessSession(profile="default")
        assert sess._resolve_region(MagicMock(region_name=None)) == FALLBACK_REGION

    def test_explicit_region_wins(self):
        sess = HarnessSession(region="eu-central-1")
        assert sess._resolve_region(MagicMock(region_name="us-east-2")) == "eu-central-1"


class TestProfilePrecedence:
    """Audit fix #4: --profile default must be None so config profile is used."""

    def test_cli_option_defaults_to_none(self):
        import inspect

        from harness_cli.main import main_callback
        sig = inspect.signature(main_callback)
        default = sig.parameters["profile"].default
        # typer.OptionInfo with default None
        assert getattr(default, "default", "missing") is None


class TestRegionDetectionWiring:
    """Audit fix #3: detect_enabled must default ON."""

    def test_regions_for_detects_by_default(self):
        import inspect

        from harness_cli import runtime
        sig = inspect.signature(runtime.regions_for)
        assert sig.parameters["detect_enabled"].default is True

    def test_no_fallback_regions_constant(self):
        """Audit fix #5/#9: silent hardcoded fallbacks were removed."""
        from harness_primitives import regions
        assert not hasattr(regions, "FALLBACK_REGIONS")

    def test_region_detection_filters_by_optin_status(self):
        from harness_primitives.regions import get_enabled_regions

        fake_ec2 = MagicMock()
        fake_ec2.describe_regions.return_value = {"Regions": [
            {"RegionName": "us-east-1", "OptInStatus": "opt-in-not-required"},
            {"RegionName": "eu-west-1", "OptInStatus": "opted-in"},
            {"RegionName": "af-south-1", "OptInStatus": "not-opted-in"},
        ]}
        session = MagicMock()
        session.get_client.return_value = fake_ec2
        enabled = get_enabled_regions(session, "123456789012")
        assert enabled == ["us-east-1", "eu-west-1"]

    def test_region_detection_raises_on_denied(self):
        from botocore.exceptions import ClientError

        from harness_primitives.failure import HarnessError
        from harness_primitives.regions import get_enabled_regions

        fake_ec2 = MagicMock()
        fake_ec2.describe_regions.side_effect = ClientError(
            {"Error": {"Code": "UnauthorizedOperation", "Message": "denied"}},
            "DescribeRegions",
        )
        session = MagicMock()
        session.get_client.return_value = fake_ec2
        with pytest.raises(HarnessError, match="Not authorized"):
            get_enabled_regions(session, "123456789012")

    def test_region_detection_raises_on_timeout(self):
        from botocore.exceptions import ReadTimeoutError

        from harness_primitives.failure import HarnessError
        from harness_primitives.regions import get_enabled_regions

        fake_ec2 = MagicMock()
        fake_ec2.describe_regions.side_effect = ReadTimeoutError(endpoint_url="x")
        session = MagicMock()
        session.get_client.return_value = fake_ec2
        with pytest.raises(HarnessError, match="Timed out"):
            get_enabled_regions(session, "123456789012")


class TestIAMPipelineMigration:
    """Audit fix #2: IAM must use the runtime pipeline (--account honoured)."""

    def test_iam_has_all_accounts_option(self):
        from typer.testing import CliRunner

        from harness_cli.main import app
        result = CliRunner().invoke(app, ["iam", "list-users", "--help"])
        assert result.exit_code == 0
        assert "--all-accounts" in result.output

    def test_iam_uses_runtime_pipeline(self):
        """The command body must go through run/resolve/executor, not a bare session."""
        import inspect

        from harness_plugins.iam.plugin import IAMPlugin
        src = inspect.getsource(IAMPlugin.create_app)
        assert "resolve_accounts" in src
        assert "execute_across_accounts" in src
        # The old bypass must be gone
        assert 'HarnessSession(profile=ctx["profile"])' not in src

    def test_iam_is_global(self):
        from harness_plugins.iam.plugin import IAMPlugin
        assert IAMPlugin.CAPABILITIES.is_global_service is True

    def test_iam_audit_detects_missing_mfa(self):
        from harness_plugins.iam.plugin import IAMPlugin

        plugin = IAMPlugin()
        session = MagicMock()
        session.get_client.return_value.list_users.return_value = {
            "Users": [{"UserName": "alice"}], "IsTruncated": False,
        }
        session.get_client.return_value.list_mfa_devices.return_value = {
            "MFADevices": [],
        }
        audit = plugin.audit(session)
        assert audit["compliant"] is False
        assert audit["findings"][0]["type"] == "user_without_mfa"


class TestAccountCommandGroup:
    """Audit fix #11: the account command group must exist."""

    def test_account_commands_registered(self):
        from typer.testing import CliRunner

        from harness_cli.main import app
        result = CliRunner().invoke(app, ["account", "--help"])
        assert result.exit_code == 0
        for cmd in ("list", "show", "regions", "assume"):
            assert cmd in result.output


class TestDeadCodeRemoved:
    def test_run_account_sweep_removed(self):
        """Audit fix #8: dead helper deleted."""
        from harness_cli import runtime
        assert not hasattr(runtime, "run_account_sweep")

    def test_get_runtime_returns_config_only(self):
        """Audit fix #10: the always-None second element is gone."""
        import inspect

        from harness_cli import runtime
        # No tuple annotation in the signature
        assert "tuple" not in str(inspect.signature(runtime.get_runtime))


class TestAttributionFallback:
    """Live-found (pass 3): some orgs (AWS account-access advanced mode)
    deny sts:TagSession/SetSourceIdentity org-wide. The session must
    degrade to RoleSessionName attribution instead of failing."""

    def test_falls_back_when_tags_denied(self):
        from botocore.exceptions import ClientError

        from harness_primitives.session import HarnessSession

        sess = HarnessSession(
            profile="p", role_arn="arn:aws:iam::1:role/X",
            external_id="ext", session_tags={"k": "v"},
            account_id="111111111111")

        calls = []

        def assume_role(**kwargs):
            calls.append(kwargs)
            if "Tags" in kwargs:
                raise ClientError(
                    {"Error": {"Code": "AccessDenied",
                               "Message": "not authorized to perform: "
                                          "sts:TagSession"}},
                    "AssumeRole")
            return {"Credentials": {"AccessKeyId": "A",
                                    "SecretAccessKey": "s",
                                    "SessionToken": "t"}}

        base = MagicMock()
        base.region_name = "eu-north-1"
        fake_sts = MagicMock()
        fake_sts.assume_role.side_effect = assume_role
        with patch.object(HarnessSession, "get_base_session",
                          return_value=base), \
             patch("harness_primitives.session.create_botocore_client",
                   return_value=fake_sts):
            creds = sess.assume_role_credentials()

        assert creds["AccessKeyId"] == "A"
        assert len(calls) == 2                    # retried without tags
        assert "Tags" not in calls[1]
        assert "SourceIdentity" not in calls[1]
        assert calls[1]["RoleSessionName"].startswith("harness-111111111111")

    def test_other_errors_still_raise(self):
        from botocore.exceptions import ClientError

        from harness_primitives.session import HarnessSession

        sess = HarnessSession(profile="p", role_arn="arn:aws:iam::1:role/X")
        base = MagicMock()
        base.region_name = "eu-north-1"
        fake_sts = MagicMock()
        fake_sts.assume_role.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "not the org"}},
            "AssumeRole")
        with patch.object(HarnessSession, "get_base_session",
                          return_value=base), \
             patch("harness_primitives.session.create_botocore_client",
                   return_value=fake_sts):
            import pytest
            with pytest.raises(ClientError):
                sess.assume_role_credentials()


class TestGlobalAllAccounts:
    """Live-found (pass 3): `harness --all-accounts iam list-users` swept
    ONE account — plugin commands read only their own per-command flag;
    the global flag was dead. resolve_accounts must OR the two."""

    def test_global_flag_alone_sweeps_all(self, tmp_path):
        from harness_cli.runtime import resolve_accounts
        from harness_primitives.accounts import AccountResolver
        from harness_primitives.config import AccountsConfig, HarnessConfig, ManualAccount
        from harness_store import database
        config = HarnessConfig(accounts=AccountsConfig(
            manual=[ManualAccount(id="111111111111", name="a"),
                    ManualAccount(id="222222222222", name="b")]))
        store = database.connect(tmp_path / "s.db")
        database.migrate(store)
        resolver = AccountResolver(config, MagicMock(), store=store)
        resolver.discover()

        import harness_cli.main as cli_main
        cli_main._CTX.clear()
        cli_main._CTX.update({"all_accounts": True, "account": None,
                              "business": None})
        accounts = resolve_accounts(resolver, None, all_accounts=False)
        assert {a.id for a in accounts} == {"111111111111", "222222222222"}
        cli_main._CTX.clear()


class TestFindUnusedNormalizedRows:
    """Bug #12 — found by an LLM (Qwen via pi + serve-mcp, pass 5):
    find_unused read user['UserName'] from list_users' NORMALIZED rows
    → KeyError on every account. Same class as the audit() fix (#6);
    now uses user['name'] like every other consumer."""

    def test_find_unused_consumes_normalized_rows(self):
        import boto3 as _boto3
        from moto import mock_aws as _mock

        from harness_plugins.iam.plugin import IAMPlugin

        with _mock():
            client = _boto3.Session(region_name="us-east-1").client("iam")
            client.create_user(UserName="alice")
            client.create_access_key(UserName="alice")

            class S:
                def get_client(self, service, region=None):
                    return client

            result = IAMPlugin().find_unused(S(), days=90)
        # must not raise; fresh key ⇒ no findings
        assert result == []
