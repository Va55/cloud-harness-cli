"""Tests for the CLI — global options, account validation, command structure.

Uses typer.testing.CliRunner with mocked AWS (no real credentials needed).
"""

from typer.testing import CliRunner

from harness_cli.main import app

runner = CliRunner()


class TestGlobalOptions:
    def test_help_lists_all_commands(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in ["whoami", "doctor", "version", "plugins"]:
            assert cmd in result.output

    def test_version(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "cloud-harness-cli" in result.output

    def test_global_options_parse(self):
        """Global options must be accepted before a command (audit finding #1)."""
        result = runner.invoke(app, [
            "--profile", "prod", "--region", "eu-west-1", "version",
        ])
        assert result.exit_code == 0

    def test_invalid_output_format_rejected(self):
        result = runner.invoke(app, ["--output", "xml", "version"])
        assert result.exit_code != 0
        assert "Invalid output format" in result.output

    def test_dry_run_flag_accepted(self):
        result = runner.invoke(app, ["--dry-run", "version"])
        assert result.exit_code == 0


class TestAccountValidation:
    def test_valid_12_digit_id(self):
        result = runner.invoke(app, ["--account", "123456789012", "version"])
        assert result.exit_code == 0

    def test_account_name_allowed(self):
        """Design: --account accepts names, not just IDs (audit finding #5)."""
        result = runner.invoke(app, ["--account", "production", "version"])
        assert result.exit_code == 0

    def test_ou_path_allowed(self):
        result = runner.invoke(app, ["--account", "ou-xxxx/prod", "version"])
        assert result.exit_code == 0

    def test_short_numeric_id_rejected(self):
        result = runner.invoke(app, ["--account", "12345", "version"])
        assert result.exit_code != 0
        # Message is truncated by rich box — check the distinctive part
        assert "Account ID" in result.output or "Invalid" in result.output

    def test_garbage_rejected(self):
        result = runner.invoke(app, ["--account", "!!!@@@", "version"])
        assert result.exit_code != 0


class TestPluginWiring:
    def test_plugins_command_lists_all(self):
        result = runner.invoke(app, ["plugins"])
        assert result.exit_code == 0
        for plugin in ["iam", "ec2", "s3", "cloudfront", "lambda",
                       "org", "vpc", "cost", "security", "inventory"]:
            assert plugin in result.output

    def test_iam_subcommand_help(self):
        result = runner.invoke(app, ["iam", "--help"])
        assert result.exit_code == 0
        assert "list-users" in result.output
        assert "check-mfa" in result.output
        assert "rotate-keys" in result.output
        assert "find-unused" in result.output

    def test_ec2_real_commands_wired(self):
        result = runner.invoke(app, ["ec2", "--help"])
        assert result.exit_code == 0
        assert "list-instances" in result.output
        assert "start" in result.output
        assert "stop" in result.output
        assert "audit" in result.output

    def test_s3_real_commands_wired(self):
        result = runner.invoke(app, ["s3", "--help"])
        assert result.exit_code == 0
        assert "list-buckets" in result.output
        assert "public-check" in result.output

    def test_inventory_commands_wired(self):
        result = runner.invoke(app, ["inventory", "--help"])
        assert result.exit_code == 0
        assert "collect" in result.output
        assert "summarize" in result.output
        assert "show" in result.output

    def test_all_plugins_have_real_commands(self):
        """No stubs remain — every plugin registers substantive commands."""
        for plugin_name in ["iam", "ec2", "s3", "cloudfront", "lambda",
                            "org", "vpc", "cost", "security", "inventory"]:
            result = runner.invoke(app, [plugin_name, "--help"])
            assert result.exit_code == 0, f"{plugin_name} sub-app broken"
            assert "Not yet implemented" not in result.output, \
                f"{plugin_name} still has stub commands"


class TestWhoamiWithoutCredentials:
    def test_whoami_fails_cleanly_without_aws(self, tmp_path, monkeypatch):
        """With NO usable credentials (hermetic), whoami must exit 2
        with the error on stderr — never a traceback.

        Hermetic: points boto3 and the harness at empty temp files so
        real credentials on the box (~/.aws, real config) can't leak
        into the test (pass-3 fix — previously assumed the box had no
        AWS, which stopped being true once the sandbox was set up).
        """
        empty_creds = tmp_path / "credentials"
        empty_creds.write_text("")
        empty_cfg = tmp_path / "awsconfig"
        empty_cfg.write_text("")
        conf = tmp_path / "harness.yaml"
        conf.write_text("accounts:\n  defaults:\n    profile: nonexistent\n")
        monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(empty_creds))
        monkeypatch.setenv("AWS_CONFIG_FILE", str(empty_cfg))
        result = runner.invoke(app, ["--config", str(conf), "whoami"])
        assert result.exit_code == 2
