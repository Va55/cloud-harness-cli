"""Tests for config loading and validation."""

import os
from pathlib import Path

import pytest

from harness_primitives.config import (
    HarnessConfig,
    load_config,
)

VALID_CONFIG = """
accounts:
  discovery: organizations
  manual:
    - id: "111111111111"
      name: standalone
      profile: standalone
      regions: [us-east-1]
  defaults:
    profile: prod
    session_tags:
      harness_user: "$HARNESS_TEST_USER"

execution:
  max_workers: 10
  per_account_limit: 3

output:
  format: json

inventory:
  sqlite_path: ~/custom/inventory.db
"""


@pytest.fixture
def config_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(VALID_CONFIG)
    return p


class TestLoadConfig:
    def test_load_valid_config(self, config_file):
        cfg = load_config(str(config_file))
        assert cfg.accounts.discovery == "organizations"
        assert cfg.accounts.manual[0].id == "111111111111"
        assert cfg.accounts.defaults.profile == "prod"
        assert cfg.execution.max_workers == 10
        assert cfg.output.format == "json"
        assert cfg.source_path == config_file

    def test_missing_file_raises_for_explicit(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / "nonexistent.yaml"))

    def test_no_config_uses_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HARNESS_CONFIG", "")  # empty → unset behavior
        os.environ.pop("HARNESS_CONFIG", None)
        os.environ.pop("AWS_HARNESS_CONFIG", None)
        # Point home to empty dir so default path doesn't exist
        monkeypatch.setattr("harness_primitives.config.DEFAULT_CONFIG_PATH",
                            tmp_path / "nothing.yaml")
        cfg = load_config()
        assert cfg.accounts.defaults.profile == "default"
        assert cfg.execution.max_workers == 50
        assert cfg.source_path is None

    def test_invalid_yaml_type_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("- just\n- a\n- list\n")
        with pytest.raises(ValueError, match="mapping"):
            load_config(str(p))

    def test_invalid_values_raise(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("execution:\n  max_workers: -5\n")
        with pytest.raises(ValueError, match="Invalid config"):
            load_config(str(p))

    def test_invalid_output_format_rejected(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("output:\n  format: xml\n")
        with pytest.raises(ValueError):
            load_config(str(p))


class TestEnvOverrides:
    def test_account_env_override(self, config_file, monkeypatch):
        monkeypatch.setenv("AWS_HARNESS_ACCOUNT", "222222222222")
        cfg = load_config(str(config_file))
        assert cfg.accounts.default_account == "222222222222"

    def test_profile_env_override(self, config_file, monkeypatch):
        monkeypatch.setenv("AWS_HARNESS_PROFILE", "staging")
        cfg = load_config(str(config_file))
        assert cfg.accounts.defaults.profile == "staging"


class TestExpansion:
    def test_env_var_in_session_tags(self, config_file, monkeypatch):
        monkeypatch.setenv("HARNESS_TEST_USER", "alice")
        cfg = load_config(str(config_file))
        assert cfg.accounts.defaults.session_tags["harness_user"] == "alice"

    def test_unset_env_var_expands_empty(self, config_file, monkeypatch):
        monkeypatch.delenv("HARNESS_TEST_USER", raising=False)
        cfg = load_config(str(config_file))
        assert cfg.accounts.defaults.session_tags["harness_user"] == ""

    def test_path_expansion(self, config_file):
        cfg = load_config(str(config_file))
        p = str(cfg.inventory.sqlite_path)
        assert "~" not in p
        assert p.startswith(str(Path.home()))


class TestDefaults:
    def test_defaults_are_sane(self):
        cfg = HarnessConfig()
        assert cfg.execution.max_workers == 50
        assert cfg.execution.per_account_limit == 10
        assert cfg.execution.per_api_limit == 5
        assert cfg.output.format == "table"
        assert cfg.security.enforce_mfa_for_delete is True
        assert cfg.audit.enabled is True
        assert "us-east-1" in cfg.regions.north_america.members
        assert "eu-west-1" in cfg.regions.europe.members

    def test_account_id_pattern_enforced(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("""
accounts:
  manual:
    - id: "12345"
""")
        with pytest.raises(ValueError):
            load_config(str(p))
