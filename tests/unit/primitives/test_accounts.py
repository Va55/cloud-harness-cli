"""Tests for the account resolver (discovery + resolution).

Uses moto to mock Organizations and STS where possible.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from harness_primitives.accounts import AccountResolver
from harness_primitives.config import HarnessConfig
from harness_primitives.failure import HarnessError
from harness_store import database


def make_config(tmp_path, manual=None, default_account=None):
    cfg = HarnessConfig()
    if manual:
        cfg.accounts.manual = manual
    cfg.accounts.default_account = default_account
    return cfg


@pytest.fixture
def store(tmp_path):
    conn = database.connect(tmp_path / "test.db")
    database.migrate(conn)
    yield conn
    conn.close()


@dataclass
class FakeAccount:
    id: str
    name: str
    status: str = "ACTIVE"
    ou: str | None = None


class FakeOrgClient:
    """Minimal fake of the boto3 organizations client."""

    def __init__(self, accounts):
        self.accounts = accounts
        self.get_paginator = lambda op: self
        # ListParents responses: child → parent
        self.parents: dict[str, dict] = {}
        for acct in accounts:
            if acct.ou:
                ou_id = f"ou-{acct.ou.replace('/', '-')}"
                self.parents[acct.id] = {"Id": ou_id, "Type": "ORGANIZATIONAL_UNIT", "Name": acct.ou.split("/")[-1]}
                # Parent of the OU chain → Root (depth-1 fakes here)

    def paginate(self):
        yield {"Accounts": [
            {"Id": a.id, "Name": a.name, "Status": a.status} for a in self.accounts
        ]}

    def list_parents(self, ChildId, ChildType):  # noqa: N803 — boto3 API contract
        parent = self.parents.get(ChildId)
        if parent is None:
            return {"Parents": [{"Id": "r-root", "Type": "Root"}]}
        return {"Parents": [parent]}


class FakeSession:
    """Fake HarnessSession returning fake clients."""

    def __init__(self, org_client):
        self._org = org_client

    def get_client(self, service, region=None):
        assert service == "organizations"
        return self._org

    def get_sts_client(self):
        sts = MagicMock()
        sts.get_caller_identity.return_value = {
            "Account": "999999999999",
            "Arn": "arn:aws:iam::999999999999:user/alice",
        }
        return sts


def make_resolver(config, store, accounts):
    org = FakeOrgClient(accounts)
    return AccountResolver(config, FakeSession(org), store)


class TestDiscovery:
    def test_discover_from_orgs_persists(self, tmp_path, store):
        cfg = make_config(tmp_path)
        resolver = make_resolver(cfg, store, [
            FakeAccount("111111111111", "prod", ou="prod"),
            FakeAccount("222222222222", "staging"),
        ])
        found = resolver.discover()
        assert {a.id for a in found} == {"111111111111", "222222222222"}
        stored = database.list_accounts(store)
        assert len(stored) == 2
        assert stored[0]["name"] == "prod"

    def test_suspended_filtered(self, tmp_path, store):
        cfg = make_config(tmp_path)
        resolver = make_resolver(cfg, store, [
            FakeAccount("111111111111", "prod"),
            FakeAccount("222222222222", "dead", status="SUSPENDED"),
        ])
        found = resolver.discover()
        assert [a.id for a in found] == ["111111111111"]

    def test_manual_accounts_merged(self, tmp_path, store):
        from harness_primitives.config import ManualAccount
        cfg = make_config(tmp_path, manual=[
            ManualAccount(id="333333333333", name="standalone", profile="standalone"),
        ])
        # discovery=organizations finds nothing; manual adds one
        resolver = make_resolver(cfg, store, [])
        found = resolver.discover()
        assert [a.id for a in found] == ["333333333333"]
        assert found[0].profile == "standalone"
        assert found[0].discovery_source == "manual"

    def test_ou_path_built(self, tmp_path, store):
        cfg = make_config(tmp_path)
        resolver = make_resolver(cfg, store, [
            FakeAccount("111111111111", "prod", ou="prod"),
        ])
        found = resolver.discover()
        assert found[0].ou_path == "prod"


class TestResolution:
    @pytest.fixture(autouse=True)
    def discovered(self, tmp_path, store):
        cfg = make_config(tmp_path)
        self.cfg = cfg
        self.store = store
        self.resolver = make_resolver(cfg, store, [
            FakeAccount("111111111111", "prod", ou="prod"),
            FakeAccount("222222222222", "staging"),
        ])
        self.resolver.discover()

    def test_resolve_by_id(self):
        acct = self.resolver.resolve("111111111111")
        assert acct.id == "111111111111"
        assert acct.name == "prod"

    def test_resolve_by_name(self):
        acct = self.resolver.resolve("staging")
        assert acct.id == "222222222222"

    def test_resolve_by_ou_path(self):
        acct = self.resolver.resolve("ou-prod")
        assert acct.id == "111111111111"

    def test_resolve_self(self):
        acct = self.resolver.resolve("self")
        assert acct.id == "999999999999"
        assert acct.name == "alice"

    def test_resolve_none_without_default_raises(self):
        with pytest.raises(HarnessError, match="No account specified"):
            self.resolver.resolve(None)

    def test_resolve_none_with_config_default(self):
        self.cfg.accounts.default_account = "staging"
        acct = self.resolver.resolve(None)
        assert acct.id == "222222222222"

    def test_resolve_unknown_name_raises(self):
        with pytest.raises(HarnessError, match="Unknown account name"):
            self.resolver.resolve("nonexistent")

    def test_resolve_ambiguous_name_raises(self):
        # Add a second account with the same name
        database.upsert_account(self.store, "333333333333", name="prod")
        with pytest.raises(HarnessError, match="ambiguous"):
            self.resolver.resolve("prod")

    def test_resolve_suspended_id_raises(self):
        database.upsert_account(self.store, "444444444444", name="old", status="SUSPENDED")
        with pytest.raises(HarnessError, match="SUSPENDED"):
            self.resolver.resolve("444444444444")


class TestResolveAll:
    def test_uses_store_without_rediscovery(self, tmp_path, store):
        """resolve_all prefers the store; no API calls needed."""
        cfg = make_config(tmp_path)
        resolver = make_resolver(cfg, store, [])
        # Persist directly
        database.upsert_account(store, "111111111111", name="prod")
        accounts = resolver.resolve_all()
        assert [a.id for a in accounts] == ["111111111111"]

    def test_rediscovery_when_store_empty(self, tmp_path, store):
        cfg = make_config(tmp_path)
        resolver = make_resolver(cfg, store, [
            FakeAccount("111111111111", "prod"),
        ])
        accounts = resolver.resolve_all()  # store empty → discovers
        assert [a.id for a in accounts] == ["111111111111"]
