"""
Session management for AWS Harness.

Creates boto3 sessions with proper credential resolution and caching.
botocore clients are thread-safe; resources are not.

Credential flow:
    1. Base session from the AWS CLI profile
    2. If role_arn is set → STS AssumeRole with all four CloudTrail
       attribution fields (RoleSessionName, SourceIdentity, ExternalId,
       session Tags) → derived session with temporary credentials
    3. Clients are created from the *effective* session and cached

The role assumption is lazy and cached: it happens on first client
creation, not in the constructor, so constructing sessions is cheap
and fan-out workers only pay for roles they actually use.
"""

import os
import re
import threading
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.config import Config

# Used when neither the profile nor an explicit region provides one.
# us-east-1 always exists and is the endpoint for global services.
FALLBACK_REGION = "us-east-1"


@dataclass
class ExecutionConfig:
    """Thread pool and rate limiting configuration."""
    max_workers: int = 50               # Max total threads
    per_account_limit: int = 10         # Max concurrent ops per account
    per_api_limit: int = 5              # Max concurrent calls per API per region
    rate_limit_rps: float = 10.0        # Global default rate limit


class HarnessSession:
    """AWS session manager with role assumption and botocore config."""

    def __init__(self, profile: str = "default", role_arn: Optional[str] = None,
                 external_id: Optional[str] = None,
                 session_tags: Optional[dict] = None,
                 account_id: Optional[str] = None,
                 region: Optional[str] = None,
                 source_identity: Optional[str] = None):
        self.profile = profile
        self.role_arn = role_arn
        self.external_id = external_id
        self.session_tags = session_tags or {}
        self.account_id = account_id
        self.region = region
        self.source_identity = source_identity or _default_source_identity()

        self._base_session: Optional[boto3.Session] = None
        self._effective_session: Optional[boto3.Session] = None
        self._client_cache: dict = {}
        # RLock: get_session() holds the lock while calling
        # get_base_session()/_assume_role_session(), which re-enter it.
        # A plain Lock deadlocks here.
        self._lock = threading.RLock()

    # ─── Sessions ───────────────────────────────────────────────

    def get_base_session(self) -> boto3.Session:
        """Base boto3 session from the AWS CLI profile (no role assumed)."""
        if self._base_session is None:
            with self._lock:
                if self._base_session is None:
                    self._base_session = boto3.Session(profile_name=self.profile)
        return self._base_session

    def get_session(self) -> boto3.Session:
        """Effective session: base session, or role-assumed when role_arn is set.

        This is where cross-account access actually happens. Without a
        role_arn the base profile credentials are used (single account);
        with one, credentials come from STS AssumeRole with full
        CloudTrail attribution.
        """
        if self._effective_session is not None:
            return self._effective_session

        with self._lock:
            if self._effective_session is not None:
                return self._effective_session
            if not self.role_arn:
                self._effective_session = self.get_base_session()
            else:
                self._effective_session = self._assume_role_session()
            return self._effective_session

    def _assume_role_session(self) -> boto3.Session:
        """Assume role_arn and return a session with temporary credentials.

        Sets all four CloudTrail attribution fields:
        - RoleSessionName  (harness-<profile>-<pid>, or account-scoped)
        - SourceIdentity   (human attribution — shows who, not just the role)
        - ExternalId       (confused-deputy prevention; required cross-account)
        - Tags + TransitiveTagKeys (propagate to downstream services)
        """
        creds = self.assume_role_credentials()
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=self._resolve_region(self.get_base_session()),
        )

    def assume_role_credentials(self, duration: int = 3600) -> dict:
        """Assume role_arn and return the STS Credentials dict.

        Single implementation of the AssumeRole call — used by
        get_session() and by `harness account assume`. Raises ValueError
        for an invalid duration (STS: 900–43200s) and lets botocore
        errors (AccessDenied, ...) propagate to the caller.
        """
        if not (900 <= duration <= 43200):
            raise ValueError(
                f"Duration must be 900–43200 seconds, got {duration}"
            )
        # STS must use the session's configured region (this sandbox
        # org denies STS actions in us-east-1 — found live, pass 3);
        # FALLBACK_REGION only when nothing is configured
        sts_region = self._resolve_region(self.get_base_session())
        sts = create_botocore_client(
            self.get_base_session(), "sts", sts_region
        )

        params: dict = {
            "RoleArn": self.role_arn,
            "RoleSessionName": self._role_session_name(),
            "DurationSeconds": duration,
        }
        if self.source_identity:
            params["SourceIdentity"] = self.source_identity
        if self.external_id:
            params["ExternalId"] = self.external_id
        if self.session_tags:
            params["Tags"] = [
                {"Key": k, "Value": v} for k, v in self.session_tags.items()
            ]
            params["TransitiveTagKeys"] = list(self.session_tags.keys())

        try:
            response = sts.assume_role(**params)
        except Exception as e:
            # Some orgs (observed live: AWS account-access 'advanced
            # mode') deny sts:TagSession / sts:SetSourceIdentity org-
            # wide regardless of identity/trust/SCP/RCP policies.
            # Attribution gracefully degrades to RoleSessionName (still
            # unique + CloudTrail-visible) + the local audit trail.
            msg = str(e)
            if ("TagSession" in msg or "SetSourceIdentity" in msg) \
                    and "AccessDenied" in msg:
                import sys
                print(f"[WARN] {type(self).__name__}: this org blocks "
                      f"session tags / source identity "
                      f"(account-access governance) — assuming with "
                      f"RoleSessionName attribution only: "
                      f"{params.get('RoleSessionName')}", file=sys.stderr)
                params.pop("Tags", None)
                params.pop("TransitiveTagKeys", None)
                params.pop("SourceIdentity", None)
                response = sts.assume_role(**params)
            else:
                raise
        return response["Credentials"]

    def _role_session_name(self) -> str:
        """Unique, traceable session name for CloudTrail."""
        scope = self.account_id or self.profile
        return f"harness-{scope}-{os.getpid()}"[:64]  # STS limit is 64 chars

    # ─── Clients ────────────────────────────────────────────────

    def get_client(self, service: str, region: Optional[str] = None) -> boto3.client:
        """Get a properly configured botocore client.

        Clients are cached per service+region and configured with:
        - max_pool_connections=10
        - connect_timeout=5s
        - read_timeout=30s
        - retries={'mode': 'adaptive', 'max_attempts': 5}
        """
        key = f"{service}:{region or 'default'}"
        cached = self._client_cache.get(key)
        if cached is not None:
            return cached
        with self._lock:
            cached = self._client_cache.get(key)
            if cached is not None:
                return cached
            actual_region = region or self._resolve_region(self.get_session())
            client = create_botocore_client(
                self.get_session(), service, actual_region
            )
            self._client_cache[key] = client
            return client

    def get_sts_client(self) -> boto3.client:
        """STS client (always from the BASE session — assuming a role must
        not require already having assumed it, or it would recurse)."""
        return create_botocore_client(
            self.get_base_session(), "sts",
            self._resolve_region(self.get_base_session()),
        )

    def _resolve_region(self, session: boto3.Session) -> str:
        """Region precedence: explicit → profile/session → fallback."""
        return self.region or session.region_name or FALLBACK_REGION

    # ─── Regions ────────────────────────────────────────────────

    def get_enabled_regions(self, account_id: Optional[str] = None) -> list[str]:
        """Detect enabled regions via EC2 DescribeRegions.

        Raises HarnessError on failure — see harness_primitives.regions.
        """
        from harness_primitives.regions import get_enabled_regions as _get
        return _get(self, account_id or self.account_id or self.profile)

    # ─── Lifecycle ──────────────────────────────────────────────

    def shutdown(self):
        """Clear client cache."""
        with self._lock:
            self._client_cache.clear()

    def is_cross_account(self) -> bool:
        """True when this session represents an assumed (cross-account) role."""
        return bool(self.role_arn)


def _default_source_identity() -> str:
    r"""Human attribution for CloudTrail — who ran the harness.

    STS SourceIdentity allows only [\w+=,.@-] (NO colons — found live
    in pass 3: AssumeRole rejected 'harness:user' with ValidationError).
    """
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    user = re.sub(r"[^\w+=,.@-]", "-", user)[:40]
    return f"harness-{user}"


def create_botocore_client(session: boto3.Session, service: str,
                           region: str) -> boto3.client:
    """Create a properly configured botocore client.

    Configuration:
    - max_pool_connections=10 (per account/region)
    - connect_timeout=5s
    - read_timeout=30s
    - retries: adaptive mode, max_attempts=5
    """
    config = Config(
        max_pool_connections=10,
        connect_timeout=5,
        read_timeout=30,
        retries={'mode': 'adaptive', 'max_attempts': 5}
    )
    return session.client(service, region_name=region, config=config)
