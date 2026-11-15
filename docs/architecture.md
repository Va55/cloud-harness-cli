# Cloud Harness CLI — Architecture Design v3.0 (Final)

> Multi-account, multi-region AWS management platform. CLI-first, Python/boto3. Single-operator scope (v3.1): one user, >4 businesses, each business >3 AWS accounts.
> Reviews: GLM-5.3 (structural critique) + DeepSeek Pro V4 (operational precision)
> Verified: ThreadPoolExecutor, Cost Explorer limits, SQLite schema, credential security

---

## 1. Project Structure

```
cloud-harness-cli/
├── pyproject.toml                # Project config, dependencies, entry points
├── README.md
├── .env.example                  # Template for env vars
│
├── harness_primitives/           # Shared primitives layer
│   ├── __init__.py
│   ├── session.py                # ThreadPoolExecutor + boto3 session factory
│   ├── credentials.py            # SSO, AssumeRole, SourceIdentity, MFA, ExternalId
│   ├── pagination.py             # Rate-limited iterator (per API, per region)
│   ├── regions.py                # Region enablement detection via DescribeRegions
│   ├── output.py                 # JSON/Table/YAML/formatters + progress
│   ├── failure.py                # Partial-failure aggregation + edge case handling
│   ├── config.py                 # YAML config + JSON schema validation
│   ├── rate_limiter.py           # Per-account-per-region-per-API token buckets
│   └── constants.py              # Region maps, status codes, API limits
│
├── harness_plugins/              # Service plugins (each declares own Typer sub-app)
│   ├── __init__.py
│   ├── base.py                   # Plugin capabilities + Typer sub-app interface
│   ├── registry.py               # Entry-point discovery
│   ├── iam/
│   │   ├── __init__.py           # Typer sub-app
│   │   ├── users.py              # User CRUD, MFA, password policy
│   │   ├── roles.py              # Role mgmt, trust policies, inline policies
│   │   ├── policies.py           # Policy analysis, sim, validation
│   │   ├── groups.py             # Group membership, permissions boundary
│   │   └── access_keys.py        # Key rotation, status, last usage
│   ├── ec2/
│   │   ├── __init__.py           # Typer sub-app
│   │   ├── instances.py          # Launch, stop, terminate, describe
│   │   ├── vpc.py                # VPCs, subnets, route tables, IGW, NACL
│   │   ├── security_groups.py    # SG rules, audit
│   │   ├── elastic_ips.py        # EIP management
│   │   ├── volumes.py            # EBS volumes, snapshots, lifecycle
│   │   └── auto_scaling.py       # ASG mgmt, launch templates
│   ├── s3/
│   │   ├── __init__.py           # Typer sub-app
│   │   ├── buckets.py            # Bucket CRUD, versioning, lifecycle
│   │   ├── policy.py             # Bucket policies, ACLs, block public
│   │   ├── replication.py        # Cross-region replication
│   │   └── analytics.py          # Access patterns, cost optimization
│   ├── cloudfront/
│   │   ├── __init__.py           # Typer sub-app
│   │   ├── distributions.py      # Distributions, origins, behaviors
│   │   ├── key_groups.py         # Signed URL keys
│   │   └── invalidation.py       # Cache invalidation
│   ├── lambda/
│   │   ├── __init__.py           # Typer sub-app
│   │   ├── functions.py          # Create, update, invoke, delete
│   │   ├── layers.py             # Layer management
│   │   ├── events.py             # Event sources, permissions, aliases
│   │   └── provisioning.py       # Concurrent, timeout, memory, snapshots
│   ├── org/
│   │   ├── __init__.py           # Typer sub-app
│   │   ├── accounts.py           # Account mgmt, OU structure (API-discovered)
│   │   ├── policies.py           # SCPs, policy attachment
│   │   └── billing.py            # Consolidated billing, tags
│   ├── vpc/
│   │   ├── __init__.py           # Typer sub-app
│   │   ├── peering.py            # VPC peering
│   │   ├── transit_gateway.py    # Transit Gateway
│   │   ├── vpn.py                # Site-to-Site VPN
│   │   └── flow_logs.py          # Flow log management
│   ├── cost/
│   │   ├── __init__.py           # Typer sub-app
│   │   ├── explorer.py           # Cost Explorer queries (0.5 TPS serialized)
│   │   └── budgets.py            # Budget status, threshold display
│   ├── security/
│   │   ├── __init__.py           # Typer sub-app
│   │   ├── guardduty.py          # GuardDuty findings
│   │   ├── security_hub.py       # Security Hub standards, findings
│   │   ├── config.py             # Config rules, compliance
│   │   ├── macie.py              # Data discovery findings
│   │   └── waf.py                # WAF web ACLs, rules
│   └── inventory/
│       ├── __init__.py           # Typer sub-app
│       ├── collector.py          # Resource collection (incremental, region-aware)
│       ├── storage.py            # SQLite-backed store (WAL mode)
│       └── diff.py               # Snapshot diff engine
│
├── harness_cli/                  # CLI application
│   ├── __init__.py
│   ├── main.py                   # Typer entry point
│   ├── groups/
│   │   ├── __init__.py
│   │   ├── account.py
│   │   ├── iam.py
│   │   ├── ec2.py
│   │   ├── s3.py
│   │   ├── cloudfront.py
│   │   ├── lambda.py
│   │   ├── vpc.py
│   │   ├── cost.py
│   │   ├── security.py
│   │   ├── org.py
│   │   ├── inventory.py
│   │   ├── audit.py
│   │   ├── plugin.py             # Plugin discovery, list, validate
│   │   └── system.py             # whoami, doctor, version
│   └── formatters.py
│
├── harness_store/                # Persistent state (SQLite, sync-only)
│   ├── __init__.py
│   ├── database.py               # sqlite3 connection, WAL mode, migrations
│   ├── schemas/
│   │   ├── v001_accounts.sql
│   │   ├── v002_inventory.sql
│   │   ├── v003_audit.sql
│   │   └── v004_diffs.sql
│   └── sync.py
│
├── tests/                        # Test suite
│   ├── conftest.py
│   ├── unit/
│   │   ├── primitives/
│   │   │   ├── test_session.py
│   │   │   ├── test_credentials.py
│   │   │   ├── test_rate_limiter.py
│   │   │   ├── test_regions.py
│   │   │   └── test_failure.py
│   │   ├── plugins/
│   │   │   └── test_contract.py  # Plugin interface contract tests
│   │   ├── store/
│   │   │   └── test_migrations.py
│   │   └── cli/
│   │       └── test_main.py
│   ├── integration/              # Moto + sandbox account
│   │   ├── test_iam.py
│   │   ├── test_ec2.py
│   │   └── test_cost.py          # CE rate limit verification
│   └── fixtures/
│       ├── moto_responses/
│       └── sandbox_manifest.json
│
├── scripts/
│   ├── setup-env.sh
│   └── init-db.sh
│
├── docs/
│   ├── getting-started.md
│   ├── commands.md
│   ├── plugin-development.md
│   ├── multi-account-setup.md
│   ├── security.md
│   └── architecture.md
│
└── infra/
    ├── harness-stack.yaml
    └── policies/
        └── harness-admin-policy.json
```

---

## 2. Core Design Principles

### 2.1. Phase 1 Scope — Read + Safe Ops Only

**Phase 1 (now):**
- Read-only inventory: list/describe resources across accounts
- Cost overview: CE queries, budget status display
- Organization management: account/OU/SCP discovery and listing
- Safe operations: EC2 stop/start, Lambda invoke, IAM key rotation, CloudFront invalidation
- Audit trail: CloudTrail attribution + local diff

**Phase 2 (demand-driven):**
- Resource provisioning → scaffold Terraform/CDK templates (don't provision directly)
- Security scan aggregation → consume Security Hub/Prowler API
- Right-sizing → consume Compute Optimizer API
- Alerting backend → requires scheduler/daemon (not CLI scope)

### 2.2. Multi-Account Discovery & Resolution

```
Organizations API (discovered, primary)     Manual override (YAML)
         ↓                                              ↓
   Account list ───→ merge ───→ Account map ─→ resolve to session
```

**Resolution order:**
1. Explicit `--account <id|name|ou-path>` flag
2. `CLOUD_HARNESS_ACCOUNT` env var
3. Current AWS CLI profile name
4. Default profile
5. **NO implicit org root fallback** — requires explicit opt-in

**Account validation:**
```python
def validate_account_id(account_id: str) -> bool:
    """Validate account ID is 12-digit numeric string."""
    return bool(re.match(r'^\d{12}$', account_id))
```

### 2.3. Credential Flow (SSO + AssumeRole + ExternalId + SourceIdentity)

```
AWS CLI profiles (SSO, AssumeRole, static keys)
    ↓
harness config overrides (role ARN, external ID, session tags)
    ↓
Credential resolution:
  1. Static keys → direct session
  2. SSO → sso.get_role_credentials() → temp session
  3. AssumeRole → sts.assume_role() + external_id + mfa → temp session
  4. External IDP → web identity federation
    ↓
Credential caching (atomic writes, 0600, temp creds only)
    ↓
boto3 session with temp credentials
    ↓
SourceIdentity tagged on all AssumeRole calls
```

**CloudTrail Attribution (all four required):**
```python
response = sts.assume_role(
    RoleArn=role_arn,
    RoleSessionName=f"harness-{username}-{os.getpid()}",  # unique session name
    SourceIdentity=f"user:{username}",                     # human attribution
    ExternalId=external_id,                                # confused deputy prevention
    Tags=[{"Key": "Department", "Value": "platform"}],    # session tags
    TransitiveTagKeys=["Department"],                     # propagate downstream
    DurationSeconds=3600,
)
```

**Trust policy must include:**
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"AWS": "arn:aws:iam::123456789012:root"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {"sts:ExternalId": "harness-123456789012"},
                "StringLike": {"sts:SourceIdentity": "user:*"}
            }
        }
    ]
}
```

### 2.4. Credential Cache (Secure — Atomic Writes)

```
Credential cache location: ~/.cache/cloud-harness/credentials
Permissions: 0600 (owner read/write only), directory 0700
Format: JSON with TTL-based expiration
Atomic writes: O_EXCL | O_NOFOLLOW + fsync + os.replace()
Only temporary credentials cached (never static keys)
```

```python
import os, json, tempfile

class CredentialCache:
    """Secure credential caching with atomic writes."""
    
    CACHE_DIR = cache_dir()          # ~/.cache/cloud-harness
    
    def __init__(self):
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(self.CACHE_DIR, 0o700)
    
    def put(self, session_key: str, credentials: dict, ttl_seconds: int = 3600):
        """Store credentials with TTL using atomic write."""
        cache_file = self.CACHE_DIR / f"{session_key}.json"
        data = {
            "credentials": credentials,
            "expires_at": time.time() + ttl_seconds,
            "created_at": time.time(),
        }
        # Atomic write: write to temp, fsync, rename
        fd = os.open(str(cache_file) + ".tmp", 
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(cache_file) + ".tmp", str(cache_file))
        except FileExistsError:
            # Another process wrote first — race condition handled
            pass
    
    def get(self, session_key: str) -> dict | None:
        """Get cached credentials if not expired."""
        cache_file = self.CACHE_DIR / f"{session_key}.json"
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            if time.time() > data["expires_at"]:
                return None  # Expired
            return data["credentials"]
        except (json.JSONDecodeError, KeyError):
            return None  # Corrupted
    
    def clear(self, session_key: str):
        """Remove specific cache entry."""
        cache_file = self.CACHE_DIR / f"{session_key}.json"
        if cache_file.exists():
            cache_file.unlink()
    
    def clear_all(self):
        """Clear all cached credentials (--refresh flag)."""
        for f in self.CACHE_DIR.glob("*.json"):
            f.unlink()
```

### 2.5. Plugin Interface (Capability-Based)

**The interface declares capabilities, not fixed verbs. Each plugin owns its Typer sub-app.**

```python
from dataclasses import dataclass, field
from typing import Iterator, Any, Optional
from typer import Typer

@dataclass(frozen=True)
class PluginCapabilities:
    """What this plugin CAN do."""
    name: str                              # e.g. "iam", "ec2"
    display_name: str                      # e.g. "IAM", "EC2"
    version: str = "1.0.0"
    supports_read: bool = True
    supports_create: bool = False
    supports_update: bool = False
    supports_delete: bool = False
    supports_safe_ops: bool = False
    is_global_service: bool = False        # breaks region fan-out
    
    # Rate limits: per API name → TPS
    max_rps: dict = field(default_factory=dict)
    rate_limit_strict: bool = False        # e.g., Cost Explorer is very strict
    
    # Thread safety
    requires_separate_client_per_thread: bool = True

class BasePlugin:
    """All service plugins must implement this interface."""
    
    CAPABILITIES: PluginCapabilities
    
    def get_capabilities(self) -> PluginCapabilities:
        return self.CAPABILITIES
    
    def create_app(self) -> Typer:
        """Return Typer sub-app for CLI commands."""
        raise NotImplementedError
    
    def list_resources(self, session: Session, region: Optional[str] = None, **filters) -> Iterator[Any]:
        """List all resources of this service."""
        raise NotImplementedError
    
    def get_resource(self, session: Session, resource_id: str, region: Optional[str] = None) -> Optional[Any]:
        """Get a single resource by ID. Return None if not found."""
        raise NotImplementedError
    
    def describe(self, session: Session, **filters) -> dict:
        """Describe with filtering. Default: call list + filter in Python."""
        return {"resources": list(self.list_resources(session, **filters))}
    
    def safe_op(self, session: Session, operation: str, resource_id: str, **params) -> dict:
        """Safe operations: stop/start, rotate, invalidate, etc."""
        raise NotImplementedError(f"Service {self.CAPABILITIES.name} does not support {operation}")
    
    def audit(self, session: Session, region: Optional[str] = None) -> dict:
        """Security/compliance audit. Default: empty."""
        return {"service": self.CAPABILITIES.name, "compliant": True, "findings": []}
    
    def cost_info(self, session: Session, region: Optional[str] = None) -> dict:
        """Cost information. Default: null."""
        return {"service": self.CAPABILITIES.name, "total_cost": 0.0}
    
    def dry_run_simulate(self, session: Session, operation: str, **params) -> dict:
        """Simulate an operation without executing. Per-plugin implementation."""
        raise NotImplementedError(f"Service {self.CAPABILITIES.name} does not support dry-run")
    
    def is_global(self) -> bool:
        return self.CAPABILITIES.is_global_service
    
    def validate_account(self, account_id: str) -> bool:
        """Validate account ID format."""
        import re
        return bool(re.match(r'^\d{12}$', account_id))
```

**Plugin registry (entry points, NOT filesystem scanning):**
```toml
# pyproject.toml
[project.entry-points."cloud_harness.plugins"]
iam = "harness_plugins.iam.plugin:IAMPlugin"
ec2 = "harness_plugins.ec2.plugin:EC2Plugin"
s3 = "harness_plugins.s3.plugin:S3Plugin"
cloudfront = "harness_plugins.cloudfront.plugin:CloudFrontPlugin"
lambda = "harness_plugins.lambda.plugin:LambdaPlugin"
org = "harness_plugins.org.plugin:OrgPlugin"
vpc = "harness_plugins.vpc.plugin:VPCPlugin"
cost = "harness_plugins.cost.plugin:CostPlugin"
security = "harness_plugins.security.plugin:SecurityPlugin"
inventory = "harness_plugins.inventory.plugin:InventoryPlugin"
```

### 2.6. Region & Account Matrix

```yaml
regions:
  north_america:
    primary: us-east-1
    members:
      - us-east-1    # US East (N. Virginia)
      - us-east-2    # US East (Ohio)
      - us-west-1    # US West (N. California)
      - us-west-2    # US West (Oregon)
      - ca-central-1 # Canada (Central)
  europe:
    primary: eu-west-1
    members:
      - eu-west-1    # Europe (Ireland)
      - eu-west-2    # Europe (London)
      - eu-west-3    # Europe (Paris)
      - eu-central-1 # Europe (Frankfurt)
      - eu-central-2 # Europe (Zurich)
      - eu-north-1   # Europe (Stockholm)

global_services:
  - iam
  - cloudfront
  - sts
  - route53
  - s3 (list_buckets only)
  - waf (global scope)
  - organizations
  - budget
  - pricing
```

**Region enablement detection (via EC2 DescribeRegions):**
```python
def get_enabled_regions(session, account_id, cache, cache_ttl=86400):
    """Detect which regions are enabled for this account."""
    cache_key = f"regions-{account_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    ec2 = session.client('ec2', region_name='us-east-1')
    resp = ec2.describe_regions(AllRegions=True)
    enabled = [
        r['RegionName'] for r in resp['Regions']
        if r.get('OptInStatus') in ('opted-in', 'opt-in-not-required')
    ]
    cache.set(cache_key, enabled, ttl=cache_ttl)
    return enabled

# Usage in execution:
enabled = get_enabled_regions(session, account_id, region_cache)
for region in enabled:  # Only enabled regions, not all 12
    ...
```

### 2.7. Execution Model (ThreadPoolExecutor + Botocore Config)

**Confirmed: ThreadPoolExecutor is correct. Do NOT use aioboto3.**

```python
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from botocore.config import Config

@dataclass
class ExecutionConfig:
    max_workers: int = 50               # Max total threads
    per_account_limit: int = 10         # Max concurrent ops per account
    per_api_limit: int = 5              # Max concurrent calls per API per region
    rate_limit_rps: float = 10.0        # Global default rate limit

class HarnessExecutor:
    """Thread-pool executor with per-account/per-region/per-API rate limiting."""
    
    def __init__(self, config: ExecutionConfig | None = None):
        self.config = config or ExecutionConfig()
        self._pool = ThreadPoolExecutor(max_workers=self.config.max_workers)
        self._rate_limiter = RateLimiter(self.config.rate_limit_rps)
        self._account_semaphores: dict[str, threading.Semaphore] = {}
    
    def execute_across_accounts(
        self,
        account_ids: list[str],
        func: callable,
        **kwargs
    ) -> dict[str, Any]:
        """Run func(account_id, session, ...) across accounts in parallel."""
        futures = {}
        for acct in account_ids:
            future = self._pool.submit(func, acct, self._session_for(acct), **kwargs)
            futures[future] = acct
        
        results = {}
        for future in as_completed(futures):
            acct = futures[future]
            try:
                results[acct] = {"status": "success", "data": future.result()}
            except Exception as e:
                results[acct] = {"status": "error", "error": str(e)}
        return results
    
    def execute_across_regions(
        self,
        regions: list[str],
        func: callable,
        is_global: bool = False,
        **kwargs
    ) -> dict[str, Any]:
        """Run func(region, session, ...) across regions."""
        if is_global:
            # Call once with primary region (global service)
            return {"_global": func(regions[0], self._session_for(regions[0]), **kwargs)}
        
        futures = {}
        for region in regions:
            future = self._pool.submit(func, region, self._session_for(region), **kwargs)
            futures[future] = region
        
        results = {}
        for future in as_completed(futures):
            region = futures[future]
            try:
                results[region] = {"status": "success", "data": future.result()}
            except Exception as e:
                results[region] = {"status": "error", "error": str(e)}
        return results
    
    def _session_for(self, account_or_region: str) -> Session:
        """Get cached session for account/region."""
        ...
    
    def shutdown(self):
        self._pool.shutdown(wait=True)
```

**Botocore client config (per client):**
```python
def create_botocore_client(session, service, region):
    """Create a properly configured botocore client."""
    config = Config(
        max_pool_connections=10,               # per account/region
        connect_timeout=5,
        read_timeout=30,
        retries={'mode': 'adaptive', 'max_attempts': 5}
    )
    return session.client(service, region_name=region, config=config)
```

**Thread safety notes:**
- boto3 **clients** are thread-safe (share across threads for same account/region)
- boto3 **resources** are NOT thread-safe (never use `boto3.resource()`)
- Session is thread-safe for creating clients
- Cache one `boto3.Session` per account; create clients per thread as needed

### 2.8. Rate Limiter (Per-Account-Per-Region-Per-API)

```python
import threading, time

class TokenBucket:
    """Thread-safe token bucket rate limiter."""
    
    def __init__(self, rate: float, burst: int = 1):
        self.rate = rate               # tokens per second
        self.capacity = burst
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.lock = threading.Lock()
    
    def acquire(self):
        """Acquire a token, blocking if necessary."""
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            wait = (1.0 - self.tokens) / self.rate
        time.sleep(wait)
        self.acquire()  # Retry after sleep

class RateLimiter:
    """Per-account-per-region-per-API rate limiting."""
    
    # Default limits per service
    SERVICE_LIMITS = {
        "ce": {"rate": 0.5, "burst": 1, "strict": True},  # Cost Explorer — 0.5 TPS!
        "organizations": {"rate": 10.0, "burst": 5},
        "guardduty": {"rate": 15.0, "burst": 5},
        "ec2": {"rate": 5.0, "burst": 3},
        "iam": {"rate": 5.0, "burst": 3},
        "s3": {"rate": 5.0, "burst": 3},
        "lambda": {"rate": 5.0, "burst": 3},
        "cloudfront": {"rate": 2.0, "burst": 1},  # Global service
        "default": {"rate": 10.0, "burst": 5},
    }
    
    def __init__(self, default_rps: float = 10.0):
        self.default_rps = default_rps
        self._buckets: dict[str, TokenBucket] = {}
    
    def _get_bucket_key(self, service: str, account_id: str, region: str | None = None) -> str:
        """Build unique key: global services use account+service; regional use account+region+service."""
        is_global = service in ("iam", "cloudfront", "sts", "route53", "organizations", "budget", "pricing")
        if is_global or region is None:
            return f"{account_id}:{service}"
        return f"{account_id}:{region}:{service}"
    
    def get_limit(self, service: str) -> dict:
        return self.SERVICE_LIMITS.get(service, self.SERVICE_LIMITS["default"])
    
    def acquire(self, service: str, account_id: str, region: str | None = None):
        """Acquire a rate limit token for this service+account+region."""
        key = self._get_bucket_key(service, account_id, region)
        limit = self.get_limit(service)
        
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(rate=limit["rate"], burst=limit["burst"])
        
        self._buckets[key].acquire()
```

**Cost Explorer specifics (critical):**
- Rate: **0.5 TPS** (one request every 2 seconds)
- All CE calls **serialized per account** — no concurrent CE calls
- Cache results for 24 hours (cost data is already 24h stale)
- Use `GroupBy` to collapse dimensions instead of one call per service/region
- Never paginate CE in a loop without explicit `NextPageToken`
- Set `rate_limit_strict = True` for CE

### 2.9. Output & Partial-Failure Handling

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class WarningMsg:
    account_id: str
    message: str

@dataclass
class FailureMsg:
    account_id: str
    region: str | None
    service: str | None
    resource: str | None
    error_code: str
    message: str

@dataclass
class PartialResult:
    """Result of an operation across multiple accounts/regions."""
    success: dict[str, Any] = field(default_factory=dict)
    failures: list[FailureMsg] = field(default_factory=list)
    warnings: list[WarningMsg] = field(default_factory=list)
    
    @property
    def is_all_success(self) -> bool:
        return len(self.failures) == 0
    
    @property
    def failure_count(self) -> int:
        return len(self.failures)
    
    @property
    def success_count(self) -> int:
        return len(self.success)

def format_output(result: PartialResult, format: str, verbose: bool = False) -> str:
    """Format partial result for display."""
    if format == "json":
        # stdout only, stderr for diagnostics
        return json.dumps({
            "status": "partial_failure" if result.failures else "success",
            "success_count": result.success_count,
            "failure_count": result.failure_count,
            "warning_count": len(result.warnings),
            "success": result.success,
            "failures": [f.__dict__ for f in result.failures],
            "warnings": [w.message for w in result.warnings],
        }, indent=2)
    
    if format == "table":
        lines = [f"{'Account':<20} {'Status':<10} {'Service':<15} {'Details'}"]
        lines.append("-" * 70)
        for acct, data in result.success.items():
            lines.append(f"{acct:<20} {'OK':<10} {'-':<15} {str(data)[:30]}")
        for f in result.failures:
            lines.append(f"{f.account_id:<20} {'FAIL':<10} {f.service or '-':<15} {f.message[:30]}")
        return "\n".join(lines)
    
    if format == "yaml":
        import yaml
        return yaml.dump({
            "status": "partial_failure" if result.failures else "success",
            "success_count": result.success_count,
            "failure_count": result.failure_count,
            "failures": [f.__dict__ for f in result.failures],
            "warnings": [w.message for w in result.warnings],
        })
    
    return f"Success: {result.success_count}, Failures: {result.failure_count}"

# Exit code convention:
# 0 = all success
# 1 = partial success (some failures — e.g. SCP denied for one account)
# 2 = fatal error (config error, credential failure, all accounts failed)
#
# stdout = data only, stderr = diagnostics/tracebacks (when --verbose)
# Quiet mode suppresses all except fatal errors and JSON output
```

### 2.10. Credential Cache (Updated — Atomic Writes + Security)

```
Credential cache location: ~/.cache/cloud-harness/credentials
Permissions: 0600 (file), 0700 (directory)
Format: JSON with TTL-based expiration
Atomic writes: O_EXCL | O_NOFOLLOW + fsync + os.replace()
Only temporary credentials cached (never static keys)
Race condition handled: O_EXCL fails if file exists, handled gracefully
For CI: use AWS_WEB_IDENTITY_TOKEN_FILE / OIDC (not local cache)
```

### 2.11. Audit Trail & Attribution (Updated — Complete)

```
CloudTrail (existing, authoritative)
    ↓
Harness adds:
  1. SourceIdentity = "user:{username}"
  2. RoleSessionName = "harness-{username}-{pid}"
  3. SessionTags = {harness_user}   # single-operator: identify the tool
  4. ExternalId = "harness-{account-id}" (confused deputy prevention)
    ↓
CloudTrail shows: User → Session → SourceIdentity → Action
    ↓
Harness audit = correlation + diff, not duplicate logging
```

**Trust policy requirements:**
```json
{
    "Condition": {
        "StringEquals": {"sts:ExternalId": "harness-{account-id}"},
        "StringLike": {"sts:SourceIdentity": "user:*"}
    }
}
```

**Local audit (supplementary, append-only):**
```sql
-- harness_store/schemas/v003_audit.sql
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    principal TEXT NOT NULL,                    -- who initiated
    source_identity TEXT NOT NULL,              -- human attribution
    account_id TEXT NOT NULL,
    region TEXT,
    service TEXT NOT NULL,
    action TEXT NOT NULL,                       -- list-instances, stop, create-user
    resource_id TEXT,
    request_id TEXT,                            -- AWS RequestId for tracing
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    error_message TEXT,
    dry_run INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT                               -- full request/response for debugging
);

CREATE INDEX idx_audit_account ON audit_events(account_id, timestamp);
CREATE INDEX idx_audit_user ON audit_events(source_identity, timestamp);
CREATE INDEX idx_audit_action ON audit_events(action, timestamp);

-- WAL mode for concurrent writes
-- PRAGMA journal_mode=WAL;
-- PRAGMA busy_timeout=5000;
```

**Audit commands (read-only, no alerts — no backend):**
```
harness audit trail [--account <id>] [--days 7] [--user <name>] [--service <s>]
harness audit diff <snapshot1> <snapshot2>  # Resource diff between snapshots
```

---

## 3. CLI Command Design

### 3.1. Global Options

```
harness [global-options] <command> [subcommand] [options]

Global options:
  --profile PROFILE       AWS CLI profile (default: default)
  --account ACCOUNT_ID    AWS account ID, name, or OU path
                          (e.g., "123456789012", "production", "ou-xxxx/production")
  --role ROLE_ARN         Assume this role before executing
  --external-id ID        External ID for assume-role (cross-account security)
  --region REGION         Override target region
  --all-regions           Execute across all configured regions
  --all-accounts          Execute across all discovered accounts
  --output FORMAT         json|table|yaml|text (default: table)
  --dry-run               Simulate without executing (per-plugin support)
  --verbose, -v           Verbose output
  --quiet, -q             Suppress non-essential output
  --config PATH           Custom config file path
  --refresh               Refresh cached credentials
  --no-color              Disable colored output
```

### 3.2. Command Groups & Subcommands

#### `harness whoami` — Identity
```
harness whoami                              # Current identity (caller ID + session tags)
```

#### `harness doctor` — Health Check
```
harness doctor [--account <id>]             # Check permissions, region enablement, credential validity
```

#### `harness account` — Account Management
```
harness account list [--discovery org|manual|both]
harness account show --account <id>
harness account assume --account <id>       # Assume role & print env vars
harness account regions --account <id>      # Show available/enabled regions
```

#### `harness iam` — Identity & Access
```
harness iam list-users [--account <id>] [--region eu-west-1]
harness iam get-user <username>
harness iam create-user <username> [--groups <g1,g2>]
harness iam delete-user <username> [--force]
harness iam list-roles [--account <id>]
harness iam get-role <role-name>
harness iam create-role <name> --trust-policy <file>
harness iam attach-policy <role-name> --arn <policy-arn>
harness iam list-access-keys <username>
harness iam rotate-keys <username>          # Safe op
harness iam check-mfa [--username <user>]
harness iam simulate-policy <username> --actions s3:* --resource <arn>
harness iam password-policy [--account <id>]
harness iam find-unused [--days 30]
```

#### `harness ec2` — Compute
```
harness ec2 list-instances [--state running|stopped|pending] [--account <id>] [--region <r>]
harness ec2 describe <instance-id>
harness ec2 start <instance-id>             # Safe op
harness ec2 stop <instance-id>              # Safe op
harness ec2 terminate <instance-id> [--force]
harness ec2 launch --image ami-xxx --type t3.micro [--count 1] [--subnet <id>] [--sg <id>]
harness ec2 tags <instance-id> [--set key=value] [--remove key]
harness ec2 security-groups [--vpc <id>]
harness ec2 eips [--associated|--unassociated]
harness ec2 volumes [--state available|in-use]
harness ec2 snapshots [--account <id>] [--days-back 7]
harness ec2 price-check <instance-type> --region <r>
```

#### `harness s3` — Storage
```
harness s3 list-buckets [--account <id>] [--region eu-west-1]
harness s3 bucket-info <bucket-name>
harness s3 create-bucket <name> [--region <r>] [--versioning]
harness s3 delete-bucket <name> [--force]
harness s3 list-objects <bucket> [--prefix <p>] [--max-keys 1000]
harness s3 lifecycle <bucket> [--get|--set <config.yaml>]
harness s3 replication <bucket> [--get|--enable|--disable] [--dest-bucket <arn>]
harness s3 public-check <bucket>
harness s3 cost-analysis <bucket> [--period 30d]
harness s3 analytics <bucket> [--recommendations]
```

#### `harness cloudfront` — CDN (Global service)
```
harness cloudfront list-distributions
harness cloudfront distribution-info <id>
harness cloudfront create-distribution --origin <s3-bucket|url> [--viewer-https-only]
harness cloudfront delete-distribution <id>
harness cloudfront invalidate <id> --paths '/*'
harness cloudfront update-origin <id> --new-origin <arn>
harness cloudfront certificates [--list|--get <id>]
```

#### `harness lambda` — Serverless
```
harness lambda list-functions [--runtime python3.12|nodejs20|...] [--region <r>]
harness lambda function-info <function-name> [--region <r>]
harness lambda create-function <name> --runtime <runtime> --handler <handler> --role <arn> --zip-file <path>|<s3-arn>
harness lambda update-code <name> --zip-file <path> [--region <r>]
harness lambda invoke <name> [--payload '{"key":"value"}'] [--log-type Tail] [--region <r>]
harness lambda delete-function <name>
harness lambda layers [--list|--get <arn>]
harness lambda events <function> [--list|--add <event-source> --filter <expr>]
harness lambda concurrency <name> [--get|--set <value>]
harness lambda snapshots --export
```

#### `harness vpc` — Networking
```
harness vpc list [--account <id>] [--region <r>]
harness vpc info <vpc-id>
harness vpc subnets <vpc-id>
harness vpc routes <vpc-id>
harness vpc internet-gateway <vpc-id>
harness vpc nacl <vpc-id>
harness vpc peering-create --vpc-1 <id> --vpc-2 <id> --peer-account <id>
harness vpc peering-accept <id>
harness vpc peering-delete <id>
harness vpc tgw-list
harness vpc tgw-create --name <name> --region <r>
harness vpc vpn-list
harness vpc vpn-create --name <name> --customer-cidr <cidr> --tunnel-dp <dp1,dp2>
harness vpc flow-logs <vpc-id> [--enable|--disable|--get]
```

#### `harness cost` — Financial (Read-Only)
```
harness cost explorer --start 2024-01-01 --end 2024-01-31 --granularity MONTHLY --group-by TYPE=SERVICE|REGION
harness cost budgets list
harness cost budgets show <name>
harness cost by-service --period 30d
harness cost by-region --period 30d
harness cost by-tag --tag-key Environment
harness cost forecast --months 3
harness cost anomalies --period 7d
```

#### `harness security` — Security (Read-Only, Aggregate)
```
harness security guardduty [--findings|--enable-detector] [--account <id>]
harness security hub [--standards|--findings|--enable] [--account <id>]
harness security config [--rules|--compliance|--enable] [--account <id>]
harness security macie [--findings|--enable] [--account <id>]
harness security waf [--list|--web-acl <id>] [--account <id>]
harness security posture [--account <id>]
```

#### `harness inventory` — Resource Discovery
```
harness inventory collect [--account <id>] [--service iam|ec2|s3|...] [--output inventory.json]
harness inventory show [--account <id>] [--service <s>]
harness inventory diff [--base <file1>] [--compare <file2>]
harness inventory search --tag Environment=prod --type ec2
harness inventory export --format csv --services ec2,iam,s3
harness inventory summarize [--account <id>]
```

#### `harness audit` — Change Tracking
```
harness audit trail [--account <id>] [--days 7] [--user <name>] [--service <s>]
harness audit diff <snapshot1> <snapshot2>
```

#### `harness org` — Organizations
```
harness org list-accounts [--discovery]     # API-discovered from Organizations
harness org list-ous
harness org create-account <name> <email> [--ou <id>]
harness org move-account <account-id> --target-ou <ou-id>
harness org list-scp [--ou <id>]
harness org attach-scp <policy-id> --target <ou|account-id>
harness org billing-summary
harness org consolidated-tags
```

#### `harness plugin` — Plugin Management
```
harness plugin list                         # Show loaded plugins and capabilities
harness plugin validate                     # Check for duplicate command names
```

---

## 4. Data Flow (Updated)

```
┌─────────────────────────────────────────────────────┐
│                    CLI Entry Point                  │
│                  (Typer / argparse)                 │
│  Global: --profile, --account, --role, --region     │
│         --all-regions, --all-accounts, --output     │
│         --dry-run, --verbose, --config              │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              Config Resolver                        │
│  • Load YAML config + env vars                      │
│  • JSON schema validation                           │
│  • Account ID validation (12-digit)                 │
│  • Resolve account, region, profile                 │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│             Credential Manager                      │
│  • SSO / AssumeRole / Static keys                   │
│  • SourceIdentity + RoleSessionName + ExternalId    │
│  • SessionTags + TransitiveTagKeys                  │
│  • Credential cache (~/.cache/cloud-harness/)         │
│  • Atomic writes (O_EXCL | O_NOFOLLOW + fsync)      │
│  • 0600 permissions (file), 0700 (directory)        │
│  • TTL-based expiration                             │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│             Region Resolver                         │
│  • Discover enabled regions (DescribeRegions)       │
│  • Cache per-account for 24 hours                   │
│  • Skip disabled regions                            │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              Harness Executor                       │
│  • ThreadPoolExecutor (not asyncio, not aioboto3)   │
│  • max_workers=50, per_account=10, per_api=5        │
│  • Botocore adaptive retry (max_attempts=5)         │
│  • Session caching (avoid repeated AssumeRole)      │
│  • Per-account-per-region-per-API rate limiting     │
│  • Cost Explorer serialized (0.5 TPS, 24h cache)    │
│  • Botocore config: max_pool_connections=10,        │
│    connect_timeout=5, read_timeout=30               │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│            Plugin Dispatch                          │
│  • Discover plugin via entry points                 │
│  • Call plugin method (list/get/safe-op/audit)      │
│  • Global service detection (skip region fan-out)   │
│  • Dry-run simulation per-plugin                    │
│  • Tag-based deletion guards                        │
│  • Edge case handling (expired, SCP, throttle)      │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              Output Formatter                       │
│  • JSON / Table / YAML / Text                       │
│  • Partial-failure aggregation                      │
│  • Progress indicators (for long operations)        │
│  • Row limits (rich tables choke >10k rows)         │
│  • stdout=data, stderr=diagnostics                  │
│  • Exit codes: 0=success, 1=partial, 2=fatal        │
└─────────────────────────────────────────────────────┘
```

---

## 5. Edge Case Handling (failure.py)

```python
from enum import Enum

class FailureCategory(Enum):
    PERMISSION = "permission"        # SCP denied, AccessDenied
    THROTTLED = "throttled"         # Rate limited, botocore retry exhausted
    CREDENTIAL_EXPIRED = "credential_expired"  # ExpiredToken
    REGION_DISABLED = "region_disabled"  # Not opted-in
    ACCOUNT_SUSPENDED = "account_suspended"  # SUSPENDED status
    TIMEOUT = "timeout"             # Connection/read timeout
    PARTIAL = "partial"             # Some succeeded, some failed
    FATAL = "fatal"                 # Config error, no accounts

class HarnessError(Exception):
    """Base exception for harness errors."""
    def __init__(self, message: str, category: FailureCategory, account_id: str | None = None):
        super().__init__(message)
        self.message = message
        self.category = category
        self.account_id = account_id

class HarnessFailure:
    """Handle common AWS API failure modes."""
    
    @staticmethod
    def handle_access_denied(error, account_id, service, region):
        """SCP or IAM permission denied — do NOT retry."""
        return FailureMsg(
            account_id=account_id,
            region=region,
            service=service,
            error_code=error.response["Error"]["Code"],
            message=error.response["Error"]["Message"]
        )
    
    @staticmethod
    def handle_throttling(error, account_id, service, region):
        """Rate limited — botocore adaptive retry handles most cases."""
        # If retry exhausted, return as warning
        return FailureMsg(
            account_id=account_id,
            region=region,
            service=service,
            error_code=error.response["Error"]["Code"],
            message=f"Throttled after retries: {error.response['Error']['Message']}"
        )
    
    @staticmethod
    def handle_expired_token(error, account_id):
        """Credential expired — attempt one refresh."""
        return HarnessError(
            f"Credential expired for account {account_id}. Refreshing...",
            FailureCategory.CREDENTIAL_EXPIRED,
            account_id
        )
    
    @staticmethod
    def handle_account_suspended(account_id):
        """Account is suspended — filter out."""
        return HarnessError(
            f"Account {account_id} is SUSPENDED. Skipping.",
            FailureCategory.ACCOUNT_SUSPENDED,
            account_id
        )
    
    @staticmethod
    def handle_region_disabled(region, account_id):
        """Region not opted-in."""
        return FailureMsg(
            account_id=account_id,
            region=region,
            service=None,
            error_code="RegionNotOptedIn",
            message=f"Region {region} not enabled for account {account_id}"
        )
```

---

## 6. SQLite Schema (Full, WAL Mode)

```sql
-- harness_store/schemas/v001_accounts.sql
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT,
    ou_path TEXT,
    status TEXT DEFAULT 'ACTIVE',       -- ACTIVE|SUSPENDED
    regions_enabled TEXT,               -- JSON array of region names
    last_seen TIMESTAMP DEFAULT (datetime('now')),
    discovered_at TIMESTAMP DEFAULT (datetime('now')),
    discovery_source TEXT DEFAULT 'organizations'  -- organizations|manual
);

CREATE INDEX idx_accounts_status ON accounts(status);
CREATE INDEX idx_accounts_discovered ON accounts(discovered_at);

-- harness_store/schemas/v002_inventory.sql
CREATE TABLE IF NOT EXISTS inventory_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    region TEXT NOT NULL,
    service TEXT NOT NULL,
    collected_at TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS resources (
    snapshot_id INTEGER NOT NULL REFERENCES inventory_snapshots(id),
    resource_id TEXT NOT NULL,
    arn TEXT,
    account_id TEXT NOT NULL,
    region TEXT NOT NULL,
    service TEXT NOT NULL,
    tags_json TEXT,                     -- JSON
    state TEXT,
    raw_json TEXT,                      -- full response for future use
    PRIMARY KEY (snapshot_id, resource_id)
);

CREATE INDEX idx_resources_account_region_service ON resources(account_id, region, service);
CREATE INDEX idx_resources_arn ON resources(arn);
CREATE INDEX idx_resources_snapshot ON resources(snapshot_id);

-- Metadata table for schema migrations
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

INSERT OR IGNORE INTO metadata (key, value) VALUES ('schema_version', '1');

-- harness_store/schemas/v003_audit.sql
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    principal TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    account_id TEXT NOT NULL,
    region TEXT,
    service TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_id TEXT,
    request_id TEXT,
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    error_message TEXT,
    dry_run INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT
);

CREATE INDEX idx_audit_account ON audit_events(account_id, timestamp);
CREATE INDEX idx_audit_user ON audit_events(source_identity, timestamp);
CREATE INDEX idx_audit_action ON audit_events(action, timestamp);

-- harness_store/schemas/v004_diffs.sql
CREATE TABLE IF NOT EXISTS resource_diffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_a INTEGER NOT NULL REFERENCES inventory_snapshots(id),
    snapshot_b INTEGER NOT NULL REFERENCES inventory_snapshots(id),
    resource_id TEXT NOT NULL,
    change_type TEXT NOT NULL CHECK (change_type IN ('added', 'removed', 'modified')),
    path TEXT,
    old_value TEXT,
    new_value TEXT
);

CREATE INDEX idx_diffs_snapshot_a ON resource_diffs(snapshot_a);
CREATE INDEX idx_diffs_snapshot_b ON resource_diffs(snapshot_b);
```

**SQLite connection pattern (thread-safe):**
```python
import sqlite3

def get_db_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

# Each worker thread gets its own connection
# Or use a connection pool (threading.Lock + deque)
```

---

## 7. Dependencies

```toml
# pyproject.toml
[project]
name = "cloud-harness-cli"
version = "0.1.0"
description = "Multi-account AWS management CLI"
requires-python = ">=3.11,<3.13"
license = {text = "Apache-2.0"}

dependencies = [
    # Core
    "boto3>=1.36,<2.0",
    "botocore>=1.36,<2.0",
    
    # CLI
    "typer>=0.15",
    "rich>=13",           # Pretty tables (with row limits), progress, colors
    
    # Config
    "pyyaml>=6.0",        # YAML config (always safe_load)
    "python-dotenv>=1.0", # .env support
    "pydantic>=2.0",      # Data validation & models
    "jsonschema>=4.23",   # JSON schema validation for config
    
    # Utilities
    "rich-argparse>=1.0", # Rich CLI integration
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "moto>=5.0",          # AWS mock for unit testing
    "mypy>=1.11",
    "ruff>=0.6",
]

[project.scripts]
harness = "harness_cli.main:main"

# Plugin entry points
[project.entry-points."cloud_harness.plugins"]
iam = "harness_plugins.iam.plugin:IAMPlugin"
ec2 = "harness_plugins.ec2.plugin:EC2Plugin"
s3 = "harness_plugins.s3.plugin:S3Plugin"
cloudfront = "harness_plugins.cloudfront.plugin:CloudFrontPlugin"
lambda = "harness_plugins.lambda.plugin:LambdaPlugin"
org = "harness_plugins.org.plugin:OrgPlugin"
vpc = "harness_plugins.vpc.plugin:VPCPlugin"
cost = "harness_plugins.cost.plugin:CostPlugin"
security = "harness_plugins.security.plugin:SecurityPlugin"
inventory = "harness_plugins.inventory.plugin:InventoryPlugin"
```

**Removed dependencies (unnecessary):**
- `aiosqlite` — use standard `sqlite3` with threads
- `cryptography` — not needed yet
- `httpx` — not needed (botocore handles HTTP)

---

## 8. Configuration File (Updated)

```yaml
# ~/.config/cloud-harness/config.yaml

# Account definitions
accounts:
  discovery: organizations    # Auto-discover from Organizations API
  
  manual:                     # Manual overrides (non-Org accounts)
    - id: "000000000000"
      name: standalone
      profile: standalone
      regions: [us-east-1]

  defaults:
    profile: default
    role_arn: null            # AssumeRole ARN (if different)
    external_id: null         # External ID for cross-account
    session_tags:
      harness_user: "$USER"
    regions: null

# Execution settings
execution:
  max_workers: 50
  per_account_limit: 10
  per_api_limit: 5
  rate_limit_rps: 10.0
  session_cache_ttl: 3600
  credential_cache_ttl: 3600

# Output defaults
output:
  format: table
  max_rows: 1000              # Limit for table output
  color: auto

# Region configuration
regions:
  north_america:
    primary: us-east-1
    members: [us-east-1, us-east-2, us-west-1, us-west-2, ca-central-1]
  europe:
    primary: eu-west-1
    members: [eu-west-1, eu-west-2, eu-west-3, eu-central-1, eu-central-2, eu-north-1]

# Cost display defaults (read-only, no backend alerts)
cost:
  display_currency: USD
  period_default: 30d

# Security defaults
security:
  max_unused_key_days: 90
  max_unused_role_days: 180
  enforce_mfa_for_delete: true
  production_tag_guard: true

# Inventory storage
inventory:
  store: sqlite
  sqlite_path: ~/.cache/cloud-harness/inventory.db
  retention_days: 90

# Audit trail
audit:
  enabled: true
  sqlite_path: ~/.cache/cloud-harness/audit.db
  retention_days: 365

# SQLite settings
sqlite:
  wal_mode: true
  busy_timeout_ms: 5000
```

---

## 9. Security Model (Updated)

### 9.1. Credential Security
- No credentials in config files
- Only role ARNs and external IDs in config
- Credential cache: atomic writes (O_EXCL | O_NOFOLLOW + fsync + os.replace)
- 0600 permissions (file), 0700 (directory)
- TTL-based expiration
- Only temporary credentials cached (never static keys)
- `--refresh` flag to clear all cached credentials

### 9.2. Deletion Guards
- Tag-based: refuse to delete `Environment=production` resources
- `--force` flag required for delete operations
- MFA required for destructive ops (configurable)
- Confirmation prompt for destructive ops (unless `--quiet`)

### 9.3. CloudTrail Attribution (Complete)
```python
# Every AssumeRole call includes ALL FOUR:
response = sts.assume_role(
    RoleArn=role_arn,
    RoleSessionName=f"harness-{username}-{os.getpid()}",  # unique session name
    SourceIdentity=f"user:{username}",                     # human attribution
    ExternalId=external_id,                                # confused deputy prevention
    Tags=[{"Key": "Department", "Value": "platform"}],    # session tags
    TransitiveTagKeys=["Department"],                     # propagate downstream
)
```

### 9.4. Rate Limiting
- Per-account + per-region + per-API limits
- Botocore built-in retry (adaptive mode, max_attempts=5)
- Bounded concurrency per account
- Cost Explorer: **0.5 TPS** serialized per account, 24h cache
- EC2 Describe*: conservative 5 TPS per region
- Global services: per-account + per-API only

### 9.5. Plugin Security
- Entry-point based loading (not filesystem scanning)
- No arbitrary code execution from config
- Botocore debug logging sanitized before exposure
- Validate plugin names and command names for uniqueness at startup

### 9.6. Additional Security Measures
- YAML safe loading: always `yaml.safe_load()`, never `yaml.load()`
- Config file permissions: 0600
- Account ID validation: 12-digit numeric string
- Log/redact secrets: never print Authorization headers or full HTTP requests
- Confused deputy prevention: ExternalId required for cross-account
- Session policies for read-only operations (restrict blast radius)

---

## 10. Expandability Roadmap

### Phase 1 (now): Read + Safe Ops (prerequisites for everything)
IAM (read), EC2 (read + safe ops), S3 (read), CloudFront (read + invalidate), Lambda (read + invoke), VPC (read + safe ops), Organizations (read), Cost (read-only), Security (read-only), Inventory (read-only)

### Phase 2: Inventory Sweep + Agent Interface
**2-core:** full multi-account inventory sweep (executor + account resolver + EC2/S3 real implementations + inventory collector/CLI + store API + `harness console` deep-links)
**2a:** `harness ask` — NL router (natural language → existing commands; robust on small local models)
**2b:** `harness serve-mcp` — MCP server exposing PluginRegistry as tools; pi / Claude Code / any MCP client becomes the interface (client brings its own LLM)
**2c (optional):** built-in `harness chat` agent loop — only if MCP clients prove insufficient

### Phase 3: Terraform Scaffolding
Resource provisioning → scaffold Terraform/CDK templates. Harness reads resource state → generates IaC.

### Phase 4: Advanced Operations
ECS, EKS (needs k8s client), RDS, DynamoDB, Route 53, CloudWatch, Step Functions, EventBridge, SNS/SQS, ElastiCache

### Phase 5: Analytics
Glue, Athena, Redshift, MSK, Kinesis, Bedrock, SageMaker

### Phase 6: Specialty
IoT, Ground Station, Braket, WAF, Shield, Security Hub/Prowler integration

---

## 11. Test Strategy

```
Unit tests:
  - moto.mock_aws for boto3 mocking
  - Pytest fixtures for common scenarios
  - Plugin interface contract tests
  - Rate limiter unit tests (token bucket under concurrent threads)
  - Credential cache concurrency (multiple processes writing)
  - Region enablement detection (mock DescribeRegions)
  - SQLite migration tests (apply schema version, assert idempotency)
  - CLI end-to-end tests (typer.testing.CliRunner)

Integration tests:
  - Sandbox AWS account (separate from production)
  - Account manifest for test accounts
  - CE rate limit verification (never exceed 0.5 TPS)
  - CloudTrail attribution verification
  - Disabled regions skip without errors
  - Exit codes match partial-failure semantics

Coverage targets:
  - Primitives: 90%+
  - Each plugin: 80%+
  - CLI: 70%+ (integration heavy)

moto limitations (note for test planning):
  - CE: NOT fully supported → sandbox integration suite
  - Organizations: NOT fully supported → sandbox integration suite
  - Security Hub: NOT fully supported → sandbox integration suite
  - GuardDuty: NOT fully supported → sandbox integration suite
  - Pin moto to match boto3 version
```

---

## 12. Packaging & Distribution

```bash
# Install from source
pip install -e .

# Install from PyPI (future)
pip install cloud-harness-cli

# Distribution
python -m build
twine upload dist/*

# Personal distribution (single-operator):
# - pip install -e . in a venv or pipx for CLI isolation
# - Pin the venv per machine; no shared-config coupling
# - Entry-point-based plugins keep local plugin versions honest
```

---

## 13. Agent Interface (pi / Claude Code / Hermes-style)

> Added Phase 11. Natural language as a *second layer* over the CLI —
> the CLI stays primary (scripts, cron, CI need deterministic commands).
> Agent layers ride on top of the same tool layer; they never bypass
> the safety model.

### 13.1. Core Insight

What makes pi / Claude Code / Hermes work is not the chat UI — it is a
**tool layer + agent loop**:

```
System prompt + tool definitions (JSON schema) + LLM loop + tool executor
```

The harness already implements the hard parts:

| Agent concept | Harness component (exists) |
|---|---|
| Tool definition | `PluginCapabilities` + plugin methods (`list_resources`, `get_resource`, `safe_op`) |
| Tool discovery | `PluginRegistry` (entry points → JSON schema generator is a small addition) |
| Tool results | `PartialResult` — structured JSON, exactly what an LLM needs |
| Safety guardrails | Deletion guards, dry-run, per-plugin `supports_safe_ops` capability flags |
| Audit | `audit_events` table + SourceIdentity attribution |

### 13.2. Three Tiers

**Tier 1 — `harness ask`: NL router (no agent loop)**

```
$ harness ask "show unused iam keys in prod"
→ routes to: harness iam find-unused --account prod
```

- Small local model (or structured parsing) maps natural language → existing commands
- No loop, no hallucination surface — the router can only pick from real commands
- Robust on small local models; immediate value

**Tier 2 — MCP server: `harness serve-mcp` (the real answer)**

```
pi / Claude Code / any MCP client
        ↓  (MCP: tool calls with JSON schemas)
harness MCP server → PluginRegistry → boto3 → AWS
```

- Model Context Protocol server exposing the plugin registry as tools
- **The client brings its own LLM** — pi, Claude Code, Hermes natively become
  the interface; no chat UI to build or maintain
- Harness stays the deterministic, testable core; the agent client is swappable

**Tier 3 — built-in `harness chat`: full agent loop (optional)**

- LLM backend pluggable: local llama.cpp/ollama or OpenAI-compatible API
- Only worth it if self-contained experience is required; Tier 2 provides
  the same experience mostly for free
- Small local models have weaker tool-calling JSON reliability — needs
  schema validation + generous retries, or a stronger model

### 13.3. Safety Model for Agent Calls

More important, not less — LLM outputs are less predictable than typed commands:

1. **Read-only by default:** agent-exposed tools start with `list`/`get`/`inventory` only
2. **Safe-ops require explicit confirmation** per call (`supports_safe_ops` capability gates exposure)
3. **Deletes are never exposed to the agent in v1** — capability-based filtering at the MCP boundary
4. **Dry-run is the default mode** for anything mutating until confirmation flow is proven
5. **Every agent call hits the same `audit_events` trail** with SourceIdentity attribution

### 13.4. Ordering (non-negotiable)

**Build the tools first.** An agent over 9 stub plugins is a chatbot that says
"not yet implemented." The tiers are Phase 2 items, stacked on top of the
existing Priority 1–2 roadmap (config loader, account resolver, executor,
EC2/S3 implementations, inventory collector):

- **Phase 2a:** `harness ask` NL router
- **Phase 2b:** `harness serve-mcp` MCP server
- **Phase 2c (optional):** built-in chat loop only if MCP clients prove insufficient

---

## 14. Verification Checklist

After implementing, run:

```bash
# Unit tests
pytest tests/unit

# Rate limiter stress test
pytest tests/unit/primitives/test_rate_limiter.py -s

# Plugin contract
pytest tests/unit/plugins/test_contract.py

# SQLite migration
pytest tests/unit/store/test_migrations.py

# CLI smoke
harness doctor --profile <sandbox-profile> --account <sandbox-account-id>
harness inventory collect --account <sandbox-account-id> --all-regions --output json | jq .
harness cost explorer --start 2025-01-01 --end 2025-01-31 --account <sandbox-account-id>
harness audit trail --account <sandbox-account-id> --days 7
```

**In a sandbox account, verify:**
- CloudTrail shows `sourceIdentity` and `userName` correctly for every AssumeRole
- Cost Explorer calls never exceed 0.5 TPS (watch CloudWatch metrics)
- Disabled regions are skipped without errors
- Exit codes match the partial-failure semantics
- Credential cache files have 0600 permissions
- No static keys are cached
- Region enablement detection works correctly

---

*Design v3.0 — Final. All GLM-5.3 and DeepSeek Pro findings addressed. Ready for implementation.*
