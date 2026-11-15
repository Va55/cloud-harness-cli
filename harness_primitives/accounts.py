"""
Account discovery and resolution.

Discovery: Organizations API (list_accounts) is the primary source;
SUSPENDED accounts are filtered out. Manual config accounts are merged
in (for non-Org accounts). Results persist to the store.

Resolution (selector → Account):
- 12-digit numeric → account ID (direct)
- starts with "ou-" → OU path (matched against stored ou_path)
- anything else → account name (matched against stored names)
- "self" → the caller's own account (via STS GetCallerIdentity)
- None → config default_account, else error (NO implicit org-root fallback)

OU paths are built during discovery via ListParents walks (cached in the
store; cheap at 10–50 accounts with shallow OU trees).
"""

import re
from dataclasses import dataclass
from typing import Any, Optional

from harness_primitives.config import HarnessConfig
from harness_primitives.failure import FailureCategory, HarnessError

ACCOUNT_ID_RE = re.compile(r"^\d{12}$")


@dataclass
class Account:
    id: str
    name: Optional[str]
    ou_path: Optional[str]
    status: str
    profile: Optional[str]          # profile override for this account
    role_arn: Optional[str]         # role override for this account
    regions: Optional[list[str]]    # region override for this account
    discovery_source: str          # organizations | manual
    business: Optional[str] = None  # owning business (multi-business setups)
    read_only: bool = False         # safety rail: mutations refused


class AccountResolver:
    """Discover and resolve accounts."""

    def __init__(self, config: HarnessConfig, session: Any, store: Any):
        """
        config: loaded HarnessConfig
        session: HarnessSession (management/management-plane session)
        store: sqlite3 connection (from harness_store.database.connect)
        """
        self.config = config
        self.session = session
        self.store = store
        self._biz_sessions: dict[str, Any] = {}  # per-business sessions

    def _session_for_business(self, business_name: str) -> Any:
        """Lazy per-business session (the business's own credentials)."""
        if business_name not in self._biz_sessions:
            from harness_primitives.session import HarnessSession
            biz = self.config.accounts.business(business_name)
            if biz is None:
                raise HarnessError(
                    f"Unknown business: '{business_name}'. Configured: "
                    f"{[b.name for b in self.config.accounts.businesses]}",
                    FailureCategory.FATAL,
                )
            self._biz_sessions[business_name] = HarnessSession(
                profile=biz.profile,
                region=self.config.regions.north_america.primary,
            )
        return self._biz_sessions[business_name]

    # ─── Discovery ─────────────────────────────────────────────

    def discover(self, include_org: Optional[bool] = None) -> list[Account]:
        """Discover accounts from Organizations + manual config; persist to store.

        include_org: override the config's discovery mode. None (default)
        follows accounts.discovery; True forces Organizations discovery
        even when config says 'manual'; False skips it. Used by
        `harness account list --discovery ...`.
        """
        accounts: dict[str, Account] = {}

        # 1. Per-business discovery — each business uses ITS OWN
        #    credentials (one AWS login never spans businesses)
        for biz in self.config.accounts.businesses:
            use_org = (biz.discovery == "organizations"
                       if include_org is None else include_org)
            if use_org:
                biz_session = self._session_for_business(biz.name)
                for acct in self._discover_from_orgs(biz_session):
                    acct.business = biz.name
                    acct.profile = biz.profile
                    acct.role_arn = biz.role_arn_for(acct.id)
                    accounts[acct.id] = acct
                    self._persist(acct)
            for manual in biz.accounts:
                existing = accounts.get(manual.id)
                accounts[manual.id] = Account(
                    id=manual.id,
                    name=manual.name or (existing.name if existing else None),
                    ou_path=existing.ou_path if existing else None,
                    status="ACTIVE",
                    profile=biz.profile,
                    role_arn=manual.role_arn or biz.role_arn_for(manual.id),
                    regions=manual.regions or biz.regions,
                    discovery_source="manual",
                    business=biz.name,
                    read_only=(manual.read_only if manual.read_only is not None
                               else biz.read_only if biz.read_only is not None
                               else self.config.accounts.defaults.read_only),
                )
                self._persist(accounts[manual.id])

        # 2. Global Organizations discovery — ONLY when no businesses
        #    are configured (with businesses, org access is per-business)
        use_org = (self.config.accounts.discovery == "organizations"
                   if include_org is None else include_org)
        if use_org and not self.config.accounts.businesses:
            for acct in self._discover_from_orgs(self.session):
                accounts[acct.id] = acct
                self._persist(acct)

        # 3. Top-level manual accounts (business=None — backward compat)
        for manual in self.config.accounts.manual:
            existing = accounts.get(manual.id)
            accounts[manual.id] = Account(
                id=manual.id,
                name=manual.name or (existing.name if existing else None),
                ou_path=existing.ou_path if existing else None,
                status="ACTIVE",
                profile=manual.profile,
                role_arn=manual.role_arn,
                regions=manual.regions,
                discovery_source="manual",
                business=existing.business if existing else None,
                read_only=(manual.read_only if manual.read_only is not None
                           else self.config.accounts.defaults.read_only),
            )
            self._persist(accounts[manual.id])

        return [a for a in accounts.values() if a.status != "SUSPENDED"]

    def _discover_from_orgs(self, session: Any) -> list[Account]:
        """List accounts from AWS Organizations, filtering SUSPENDED.

        Uses the given session — the business's own for multi-business
        setups, the global session otherwise.
        """
        org = session.get_client(
            "organizations",
            self.config.regions.north_america.primary,  # Organizations is global
        )
        accounts = []
        paginator = org.get_paginator("list_accounts")
        for page in paginator.paginate():
            for acct in page["Accounts"]:
                accounts.append(Account(
                    id=acct["Id"],
                    name=acct.get("Name"),
                    ou_path=self._ou_path_for(org, acct["Id"]),
                    status=acct.get("Status", "ACTIVE"),
                    profile=None,
                    role_arn=None,
                    regions=None,
                    discovery_source="organizations",
                ))
        return accounts

    def _ou_path_for(self, org_client: Any, account_id: str) -> Optional[str]:
        """Walk ListParents up from an account to build its OU path.

        Root is excluded from the path. Returns e.g. 'ou-xxxx/prod/eu'.
        Cheap for shallow trees; result persisted so it's done once
        per discovery run.
        """
        child_type, child_id = "ACCOUNT", account_id
        segments: list[str] = []
        for _ in range(20):  # Depth guard — no infinite loops on cycles
            try:
                resp = org_client.list_parents(ChildId=child_id, ChildType=child_type)
            except Exception:
                return None
            parents = resp.get("Parents", [])
            if not parents:
                break
            parent = parents[0]
            if parent["Type"] == "Root":
                break
            segments.append(parent["Name"])
            child_type, child_id = "ORGANIZATIONAL_UNIT", parent["Id"]
        return "/".join(reversed(segments)) if segments else None

    def _persist(self, acct: Account) -> None:
        from harness_store import database
        database.upsert_account(
            self.store,
            account_id=acct.id,
            name=acct.name,
            ou_path=acct.ou_path,
            status=acct.status,
            discovery_source=acct.discovery_source,
            business=acct.business,
        )

    # ─── Resolution ─────────────────────────────────────────────

    def resolve(self, selector: Optional[str] = None,
                business: Optional[str] = None) -> Account:
        """Resolve a selector to an Account.

        selector: 12-digit ID | account name | 'ou-' path | 'self' | None
        business: scope resolution to one business (--business flag).
        None selector falls back to: business default_account →
        global default_account → raise (NO implicit fallback — the
        operator must say which account they mean).
        """
        biz = None
        if business is not None:
            biz = self.config.accounts.business(business)
            if biz is None:
                raise HarnessError(
                    f"Unknown business: '{business}'. Configured: "
                    f"{[b.name for b in self.config.accounts.businesses] or '(none)'}",
                    FailureCategory.FATAL,
                )

        if selector is None:
            selector = (biz.default_account if biz
                        else self.config.accounts.default_account)
            if selector is None:
                raise HarnessError(
                    "No account specified and no default configured. "
                    "Use --account (and --business), set "
                    "AWS_HARNESS_ACCOUNT, or configure "
                    "accounts.default_account / businesses[].default_account.",
                    FailureCategory.PERMISSION,
                )
        if selector == "self":
            return self._self_account(business)

        if ACCOUNT_ID_RE.fullmatch(selector):
            return self._by_id(selector, business)
        if selector.startswith("ou-"):
            return self._by_ou_path(selector, business)
        return self._by_name(selector, business)

    def resolve_all(self, business: Optional[str] = None,
                    include_suspended: bool = False) -> list[Account]:
        """All known accounts (discovered + manual), non-suspended by default.

        business: restrict to one business's accounts (--business).
        """
        from harness_store import database
        stored = database.list_accounts(self.store, include_suspended=include_suspended)
        if not stored:
            # Nothing persisted yet — run discovery now
            return self.discover()
        accounts = []
        for s in stored:
            if business is not None and (
                    not s.get("business")
                    or s["business"].lower() != business.lower()):
                continue
            biz = (self.config.accounts.business(s["business"])
                   if s.get("business") else None)
            manual = next(
                (m for m in self.config.accounts.manual if m.id == s["id"]), None
            )
            if manual is None and biz is not None:
                manual = next(
                    (m for m in biz.accounts if m.id == s["id"]), None
                )
            # Precedence: explicit manual override > business config > none
            profile = ((manual.profile if manual else None)
                       or (biz.profile if biz else None))
            role_arn = ((manual.role_arn if manual else None)
                        or (biz.role_arn_for(s["id"]) if biz else None))
            regions = ((manual.regions if manual and manual.regions else None)
                       or (biz.regions if biz else None))
            read_only = (
                manual.read_only if manual is not None and
                manual.read_only is not None
                else biz.read_only if biz is not None and
                biz.read_only is not None
                else self.config.accounts.defaults.read_only)
            # Manual config entries are the source of truth for NAME
            # (the store can hold a stale name from earlier sessions)
            accounts.append(Account(
                id=s["id"],
                name=(manual.name if manual is not None and manual.name
                      else s["name"]),
                ou_path=s["ou_path"],
                status=s["status"],
                profile=profile,
                role_arn=role_arn,
                regions=regions,
                discovery_source=s["discovery_source"],
                business=s.get("business"),
                read_only=read_only,
            ))
        if not include_suspended:
            accounts = [a for a in accounts if a.status != "SUSPENDED"]
        return accounts

    # ─── Lookup helpers ─────────────────────────────────────────

    def _by_id(self, account_id: str,
               business: Optional[str] = None) -> Account:
        for acct in self.resolve_all(business, include_suspended=True):
            if acct.id == account_id:
                if acct.status == "SUSPENDED":
                    raise HarnessError(
                        f"Account {account_id} is SUSPENDED",
                        FailureCategory.ACCOUNT_SUSPENDED,
                        account_id,
                    )
                return acct
        raise HarnessError(
            f"Unknown account ID: {account_id} (not discovered — "
            "run discovery or add to config manual accounts)",
            FailureCategory.FATAL,
            account_id,
        )

    def _by_name(self, name: str,
                 business: Optional[str] = None) -> Account:
        matches = [a for a in self.resolve_all(business) if a.name == name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            businesses = sorted({m.business or "(none)" for m in matches})
            raise HarnessError(
                f"Account name '{name}' is ambiguous ({len(matches)} matches "
                f"in businesses: {', '.join(businesses)}) — "
                "use the 12-digit ID or add --business",
                FailureCategory.FATAL,
            )
        raise HarnessError(
            f"Unknown account name: {name}",
            FailureCategory.FATAL,
        )

    def _by_ou_path(self, ou_path: str,
                    business: Optional[str] = None) -> Account:
        # Accept both 'ou-<path>' selectors and raw stored paths:
        # selector 'ou-prod' matches stored path 'prod'
        stripped = ou_path[3:] if ou_path.startswith("ou-") else ou_path
        candidates = {ou_path, stripped}
        # Exact match first
        matches = [
            a for a in self.resolve_all(business)
            if a.ou_path and a.ou_path in candidates
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise HarnessError(
                f"OU path '{ou_path}' matches {len(matches)} accounts — "
                "use the 12-digit ID",
                FailureCategory.FATAL,
            )
        # Prefix match (OU path selects a subtree)
        prefix_matches = [
            a for a in self.resolve_all(business)
            if a.ou_path and (
                a.ou_path.startswith(ou_path + "/")
                or a.ou_path.startswith(stripped + "/")
            )
        ]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        raise HarnessError(
            f"OU path '{ou_path}' matches no single account "
            f"({len(prefix_matches)} in subtree — for all accounts in an OU, "
            "use --all-accounts)",
            FailureCategory.FATAL,
        )

    def _self_account(self, business: Optional[str] = None) -> Account:
        """The caller's own account via STS GetCallerIdentity.

        With a business scope, identity comes from the business's own
        credentials; otherwise the global session.
        """
        session = (self._session_for_business(business)
                   if business else self.session)
        sts = session.get_sts_client()
        resp = sts.get_caller_identity()
        account_id = resp["Account"]
        # ARN of the caller gives a display name
        arn = resp.get("Arn", "")
        name = arn.split("/")[-1] if "/" in arn else None
        return Account(
            id=account_id,
            name=name,
            ou_path=None,
            status="ACTIVE",
            profile=(self.config.accounts.business(business).profile
                     if business else self.config.accounts.defaults.profile),
            role_arn=None,
            regions=None,
            discovery_source="self",
            business=business,
        )
