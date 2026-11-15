"""
Configuration loading and validation.

Resolution order:
1. --config flag path
2. CLOUD_HARNESS_CONFIG (or HARNESS_CONFIG) env var
3. ~/.config/cloud-harness/config.yaml (if exists)
4. Built-in defaults (always valid)

Env var overrides (highest precedence for their field):
- CLOUD_HARNESS_ACCOUNT → accounts.default_account
- CLOUD_HARNESS_PROFILE → accounts.defaults.profile

All YAML loaded with yaml.safe_load(). Paths (~) expanded. $VAR in
session_tags expanded from the environment.
"""

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

# ─── Locations ─────────────────────────────────────────────────
# The project was renamed after its first release. Runtime locations keep
# working for existing installations: the new directory is preferred, the
# pre-rename one is used when it already exists (no migration step).
APP_NAME = "cloud-harness"
LEGACY_APP_NAME = "aws-harness"

CONFIG_DIR = Path.home() / ".config" / APP_NAME
LEGACY_CONFIG_DIR = Path.home() / ".config" / LEGACY_APP_NAME
CACHE_DIR = Path.home() / ".cache" / APP_NAME
LEGACY_CACHE_DIR = Path.home() / ".cache" / LEGACY_APP_NAME


def cache_dir() -> Path:
    """Cache directory: new location, else the pre-rename one."""
    if CACHE_DIR.exists():
        return CACHE_DIR
    return LEGACY_CACHE_DIR if LEGACY_CACHE_DIR.exists() else CACHE_DIR


DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.yaml"


def config_path() -> Path:
    """Default config file: new location, else the pre-rename one."""
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    legacy = LEGACY_CONFIG_DIR / "config.yaml"      # pre-rename installation
    return legacy if legacy.exists() else DEFAULT_CONFIG_PATH


# ─── Pydantic models (the living schema) ───────────────────────

class ManualAccount(BaseModel):
    id: str = Field(pattern=r"^\d{12}$")
    name: Optional[str] = None
    profile: Optional[str] = None
    role_arn: Optional[str] = None
    regions: Optional[list[str]] = None
    read_only: Optional[bool] = None    # mutations refused (safety rail)


class BusinessConfig(BaseModel):
    """One business line: its own credentials and account group.

    Mirrors the console workflow — per-business login (profile),
    accounts within the business reached via role assumption:
      profile   → that business's own AWS credentials
      role_arn  → cross-account template WITHIN the business
                  ({account_id} expanded per account)
      discovery → organizations (ListAccounts with business profile)
                  | manual (explicit accounts list)
    """
    name: str = Field(pattern=r"^[\w][\w.-]*$")
    profile: str                     # the business's own credentials
    role_arn: Optional[str] = None
    external_id: Optional[str] = None
    discovery: str = "organizations"
    accounts: list[ManualAccount] = Field(default_factory=list)
    default_account: Optional[str] = None
    regions: Optional[list[str]] = None
    read_only: Optional[bool] = None    # mutations refused for ALL
                                       # accounts in this business

    def role_arn_for(self, account_id: Optional[str]) -> Optional[str]:
        """Expand the {account_id} placeholder, like AccountDefaults."""
        if not self.role_arn:
            return None
        if "{account_id}" in self.role_arn:
            if not account_id:
                return None
            return self.role_arn.replace("{account_id}", account_id)
        return self.role_arn


class AccountDefaults(BaseModel):
    profile: str = "default"
    read_only: bool = False              # global safety rail (default off)
    role_arn: Optional[str] = None
    external_id: Optional[str] = None
    session_tags: dict[str, str] = Field(default_factory=dict)
    regions: Optional[list[str]] = None

    def role_arn_for(self, account_id: Optional[str]) -> Optional[str]:
        """Resolve the role ARN, expanding an `{account_id}` placeholder.

        Organizations-discovered accounts have no per-account role ARN in
        config, so the standard pattern is a role-name convention:
            role_arn: "arn:aws:iam::{account_id}:role/HarnessAccess"
        Self-account (`self`) calls skip assumption (role_arn_for -> None
        for the caller's own account when no explicit ARN is configured).
        """
        if not self.role_arn:
            return None
        if "{account_id}" in self.role_arn:
            if not account_id:
                return None  # cannot expand without an account
            return self.role_arn.replace("{account_id}", account_id)
        return self.role_arn


class AccountsConfig(BaseModel):
    discovery: str = "organizations"  # organizations | manual | none
    manual: list[ManualAccount] = Field(default_factory=list)
    businesses: list[BusinessConfig] = Field(default_factory=list)
    defaults: AccountDefaults = Field(default_factory=AccountDefaults)
    default_account: Optional[str] = None  # ID, name, or OU path

    def business(self, name: str) -> Optional[BusinessConfig]:
        """Look up a business by name (case-insensitive: --business alpha
        matches configured 'Alpha'). None if unknown."""
        for biz in self.businesses:
            if biz.name.lower() == name.lower():
                return biz
        return None


class ExecutionConfigModel(BaseModel):
    max_workers: int = Field(default=50, ge=1, le=500)
    per_account_limit: int = Field(default=10, ge=1, le=100)
    per_api_limit: int = Field(default=5, ge=1, le=50)
    rate_limit_rps: float = Field(default=10.0, gt=0)
    session_cache_ttl: int = Field(default=3600, ge=60)
    credential_cache_ttl: int = Field(default=3600, ge=60)


class OutputConfig(BaseModel):
    format: str = Field(default="table", pattern=r"^(json|table|yaml|text)$")
    max_rows: int = Field(default=1000, ge=1)
    color: str = Field(default="auto", pattern=r"^(on|off|auto)$")


class RegionGroup(BaseModel):
    primary: str
    members: list[str]


class RegionsConfig(BaseModel):
    north_america: RegionGroup = Field(default_factory=lambda: RegionGroup(
        primary="us-east-1",
        members=["us-east-1", "us-east-2", "us-west-1", "us-west-2", "ca-central-1"],
    ))
    europe: RegionGroup = Field(default_factory=lambda: RegionGroup(
        primary="eu-west-1",
        members=["eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1",
                  "eu-central-2", "eu-north-1"],
    ))


class CostConfig(BaseModel):
    display_currency: str = "USD"
    period_default: str = "30d"


class SecurityConfig(BaseModel):
    max_unused_key_days: int = 90
    max_unused_role_days: int = 180
    enforce_mfa_for_delete: bool = True
    production_tag_guard: bool = True


class InventoryConfig(BaseModel):
    store: str = "sqlite"
    sqlite_path: Path = cache_dir() / "inventory.db"
    retention_days: int = 90


class AuditConfig(BaseModel):
    enabled: bool = True
    sqlite_path: Path = cache_dir() / "audit.db"
    retention_days: int = 365


class HarnessConfig(BaseModel):
    accounts: AccountsConfig = Field(default_factory=AccountsConfig)
    execution: ExecutionConfigModel = Field(default_factory=ExecutionConfigModel)
    output: OutputConfig = Field(default_factory=OutputConfig)
    regions: RegionsConfig = Field(default_factory=RegionsConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    inventory: InventoryConfig = Field(default_factory=InventoryConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    source_path: Optional[Path] = None  # Where the config was loaded from


# ─── Loader ─────────────────────────────────────────────────────

_ENV_VAR_RE = re.compile(r"\$([A-Z_][A-Z0-9_]*)")


def _expand_env_vars(value: str) -> str:
    """Expand $VAR references from the environment (unset → empty)."""
    return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _deep_expand_paths(obj: Any) -> Any:
    """Recursively expand ~ and $VAR in string values (not keys)."""
    if isinstance(obj, dict):
        return {k: _deep_expand_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_expand_paths(v) for v in obj]
    if isinstance(obj, str):
        expanded = _expand_env_vars(obj)
        return str(Path(expanded).expanduser()) if "~" in obj or expanded.startswith("~") else expanded
    return obj


def find_config_path(explicit: Optional[str] = None) -> Optional[Path]:
    """Determine which config file to load, without loading it."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        return p
    env = (os.environ.get("CLOUD_HARNESS_CONFIG")
           or os.environ.get("HARNESS_CONFIG")
           or os.environ.get("CLOUD_HARNESS_CONFIG"))  # last two: pre-rename
    if env:
        p = Path(env).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        return p
    resolved = config_path()      # honours a monkeypatched DEFAULT_CONFIG_PATH
    if resolved.exists():
        return resolved
    return None


def load_config(explicit: Optional[str] = None) -> HarnessConfig:
    """Load, validate, and environment-merge the harness configuration.

    Never raises for a *missing* config (defaults apply); raises for an
    *invalid* config (validation must fail loudly, not silently).
    """
    path = find_config_path(explicit)
    raw: dict = {}
    if path is not None:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Config file {path} must contain a mapping, got {type(raw).__name__}")

    raw = _deep_expand_paths(raw)

    try:
        config = HarnessConfig(**raw)
    except ValidationError as e:
        raise ValueError(f"Invalid config in {path or 'defaults'}: {e}") from e

    config.source_path = path

    # ── Environment overrides (highest precedence for their fields) ──
    account_env = (os.environ.get("CLOUD_HARNESS_ACCOUNT")
                   or os.environ.get("CLOUD_HARNESS_ACCOUNT"))  # pre-rename
    if account_env:
        config.accounts.default_account = account_env
    profile_env = (os.environ.get("CLOUD_HARNESS_PROFILE")
                   or os.environ.get("CLOUD_HARNESS_PROFILE"))  # pre-rename
    if profile_env:
        config.accounts.defaults.profile = profile_env

    return config
