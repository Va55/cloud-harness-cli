"""Tests for multi-business support (Phase 18, Option B).

One user, several businesses — each business with its own AWS
credentials (profile). Discovery runs per business with the business's
profile; names can collide across businesses; --business scopes
resolution.
"""

from unittest.mock import MagicMock

import pytest

import harness_cli.main as cli_main
from harness_primitives.accounts import Account, AccountResolver
from harness_primitives.config import (
    AccountsConfig,
    BusinessConfig,
    HarnessConfig,
    ManualAccount,
)
from harness_primitives.failure import HarnessError


def _ctx(**kw):
    cli_main._CTX.clear()
    cli_main._CTX.update(kw)


def _biz_config():
    """Two businesses, both manual-discovery for testability."""
    return HarnessConfig(accounts=AccountsConfig(
        discovery="manual",
        businesses=[
            BusinessConfig(
                name="acme", profile="acme-profile",
                discovery="manual",
                role_arn="arn:aws:iam::{account_id}:role/AcmeAccess",
                external_id="ext-acme",
                accounts=[
                    ManualAccount(id="111111111111", name="prod"),
                    ManualAccount(id="222222222222", name="dev"),
                ],
            ),
            BusinessConfig(
                name="globex", profile="globex-profile",
                discovery="manual",
                accounts=[
                    ManualAccount(id="333333333333", name="prod"),  # name collision!
                    ManualAccount(id="444444444444", name="staging"),
                ],
                default_account="staging",
            ),
        ],
    ))


def _resolver(config, store):
    session = MagicMock()
    return AccountResolver(config, session, store)


@pytest.fixture
def store(tmp_path):
    from harness_store import database
    conn = database.connect(tmp_path / "store.db")
    database.migrate(conn)
    return conn


class TestBusinessConfig:
    def test_businesses_parse(self):
        config = _biz_config()
        assert len(config.accounts.businesses) == 2
        biz = config.accounts.business("acme")
        assert biz.profile == "acme-profile"

    def test_business_role_template_expansion(self):
        config = _biz_config()
        biz = config.accounts.business("acme")
        assert biz.role_arn_for("111111111111") == \
            "arn:aws:iam::111111111111:role/AcmeAccess"
        globex = config.accounts.business("globex")
        assert globex.role_arn_for("111111111111") is None  # no template

    def test_unknown_business_is_none(self):
        config = _biz_config()
        assert config.accounts.business("nosuch") is None


class TestBusinessDiscovery:
    def test_manual_accounts_discover_per_business(self, store):
        config = _biz_config()
        resolver = _resolver(config, store)
        accounts = resolver.discover()
        by_id = {a.id: a for a in accounts}
        assert len(accounts) == 4
        # Business attribution
        assert by_id["111111111111"].business == "acme"
        assert by_id["333333333333"].business == "globex"
        # Per-business profile (the business's own credentials)
        assert by_id["111111111111"].profile == "acme-profile"
        assert by_id["444444444444"].profile == "globex-profile"
        # Business role template stamped on the account
        assert by_id["111111111111"].role_arn == \
            "arn:aws:iam::111111111111:role/AcmeAccess"

    def test_org_discovery_uses_business_session(self, store):
        """Org discovery must run with the business's own credentials."""
        config = HarnessConfig(accounts=AccountsConfig(
            businesses=[BusinessConfig(
                name="acme", profile="acme-profile",
                discovery="organizations")],
        ))
        resolver = _resolver(config, store)

        called_profiles = []
        real_session_for_business = resolver._session_for_business

        def spy(business_name):
            sess = real_session_for_business(business_name)
            called_profiles.append(sess.profile)
            return sess

        resolver._session_for_business = spy

        org = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Accounts": [
            {"Id": "111111111111", "Name": "prod", "Status": "ACTIVE"},
        ]}]
        org.get_paginator.return_value = paginator
        org.list_parents.return_value = {"Parents": []}  # flat OU tree

        def fake_get_client(service, region):
            assert service == "organizations"
            return org

        biz_sess = MagicMock()
        biz_sess.profile = "acme-profile"
        biz_sess.get_client.side_effect = fake_get_client
        # _session_for_business creates a real HarnessSession; patch it
        # to return our mock instead
        resolver._biz_sessions["acme"] = biz_sess

        def spy2(business_name):
            return resolver._biz_sessions[business_name]

        resolver._session_for_business = spy2
        accounts = resolver.discover()
        assert accounts[0].id == "111111111111"
        assert accounts[0].business == "acme"
        assert accounts[0].profile == "acme-profile"

    def test_global_org_skipped_when_businesses_configured(self, store):
        """With businesses configured, the global session must NOT be
        used for Organizations discovery (one login spans no businesses)."""
        config = HarnessConfig(accounts=AccountsConfig(
            discovery="organizations",
            businesses=[BusinessConfig(
                name="acme", profile="acme-profile", discovery="manual")],
        ))
        resolver = _resolver(config, store)
        resolver.session.get_client = MagicMock(
            side_effect=AssertionError("global session used for discovery"))
        accounts = resolver.discover()  # must not raise
        assert accounts == []


class TestBusinessResolution:
    def test_resolve_all_scoped_to_business(self, store):
        config = _biz_config()
        resolver = _resolver(config, store)
        resolver.discover()
        acme = resolver.resolve_all(business="acme")
        assert {a.id for a in acme} == {"111111111111", "222222222222"}
        globex = resolver.resolve_all(business="globex")
        assert {a.id for a in globex} == {"333333333333", "444444444444"}
        # No scope → everything
        assert len(resolver.resolve_all()) == 4

    def test_name_collision_resolved_by_business(self, store):
        """'prod' exists in BOTH businesses — --business disambiguates."""
        config = _biz_config()
        resolver = _resolver(config, store)
        resolver.discover()
        acct = resolver.resolve("prod", business="globex")
        assert acct.id == "333333333333"
        acct = resolver.resolve("prod", business="acme")
        assert acct.id == "111111111111"

    def test_name_collision_without_business_is_error_with_guidance(self, store):
        config = _biz_config()
        resolver = _resolver(config, store)
        resolver.discover()
        with pytest.raises(HarnessError, match="--business"):
            resolver.resolve("prod")

    def test_business_default_account(self, store):
        """--business globex with no --account → globex's default."""
        config = _biz_config()
        resolver = _resolver(config, store)
        resolver.discover()
        acct = resolver.resolve(None, business="globex")
        assert acct.id == "444444444444"  # staging

    def test_unknown_business_raises(self, store):
        config = _biz_config()
        resolver = _resolver(config, store)
        with pytest.raises(HarnessError, match="Unknown business"):
            resolver.resolve("prod", business="nosuch")

    def test_stored_accounts_roundtrip_business(self, store):
        """Business survives the store roundtrip (resolve_all rebuild)."""
        config = _biz_config()
        resolver = _resolver(config, store)
        resolver.discover()
        # resolve_all reads from the STORE, not config businesses
        acme = resolver.resolve_all(business="acme")
        assert all(a.business == "acme" for a in acme)
        # Business template re-applied on rebuild
        prod = next(a for a in acme if a.name == "prod")
        assert prod.role_arn == "arn:aws:iam::111111111111:role/AcmeAccess"


class TestBusinessStore:
    def test_business_column_persisted(self, store):
        from harness_store import database
        database.upsert_account(store, "111111111111", name="prod",
                                discovery_source="manual", business="acme")
        acct = database.get_account(store, "111111111111")
        assert acct["business"] == "acme"

    def test_business_survives_partial_upsert(self, store):
        from harness_store import database
        database.upsert_account(store, "111111111111", name="prod",
                                business="acme")
        # Region detection upserts without business
        database.upsert_account(store, "111111111111",
                                regions_enabled=["us-east-1"])
        acct = database.get_account(store, "111111111111")
        assert acct["business"] == "acme"       # NOT wiped
        assert acct["name"] == "prod"

    def test_migrate_idempotent_with_business(self, tmp_path):
        """Double migrate must not fail on the ADD COLUMN guard."""
        from harness_store import database
        conn = database.connect(tmp_path / "s.db")
        assert database.migrate(conn) == 4       # four schema files
        assert database.migrate(conn) == 4       # idempotent


class TestBusinessCLI:
    def test_business_flag_registered(self):
        from typer.testing import CliRunner

        from harness_cli.main import app
        result = CliRunner().invoke(app, ["--help"])
        assert "--business" in result.output

    def test_resolve_accounts_passes_business(self, store):
        from harness_cli.runtime import resolve_accounts
        config = _biz_config()
        resolver = _resolver(config, store)
        resolver.discover()
        _ctx(business="acme", all_accounts=True, account=None)
        accounts = resolve_accounts(resolver, None, all_accounts=True)
        assert {a.id for a in accounts} == {"111111111111", "222222222222"}
        _ctx()

    def test_executor_uses_business_external_id(self):
        """The session for a business account must use the business's
        external_id, not the global default."""
        from harness_primitives.executor import HarnessExecutor
        config = _biz_config()
        executor = HarnessExecutor(config)
        try:
            acct = Account(
                id="111111111111", name="prod", ou_path=None,
                status="ACTIVE", profile="acme-profile",
                role_arn="arn:aws:iam::111111111111:role/AcmeAccess",
                regions=None, discovery_source="manual", business="acme",
            )
            sess = executor.session_for(acct)
            assert sess.external_id == "ext-acme"
            assert sess.role_arn == "arn:aws:iam::111111111111:role/AcmeAccess"
        finally:
            executor.shutdown()
