"""Tests for the xlsx → config import script.

Uses ONLY the sanitized fixture (tests/fixtures/example-accounts.xlsx):
5 businesses, 24 fake accounts, same structural shape as the operator's
real inventory (per-account admin roles, one shared login account
without a role, one leading-zero account ID).
"""

from pathlib import Path

import pytest

FIXTURE = Path(__file__).parents[3] / "tests" / "fixtures" / "example-accounts.xlsx"

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(), reason="fixture xlsx not present")


def _import(xlsx_path=FIXTURE):
    import importlib.util
    script = (Path(__file__).parents[3] / "scripts"
              / "import-accounts-xlsx.py")
    spec = importlib.util.spec_from_file_location("import_xlsx", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.import_accounts(Path(xlsx_path))


class TestImportAccounts:
    def test_five_businesses(self):
        data = _import()
        names = [b["name"] for b in data["accounts"]["businesses"]]
        assert names == ["alpha", "beta", "gamma", "delta", "epsilon"]

    def test_account_counts_match_structure(self):
        data = _import()
        counts = {b["name"]: len(b["accounts"])
                  for b in data["accounts"]["businesses"]}
        assert counts == {"alpha": 8, "beta": 6, "gamma": 7,
                          "delta": 2, "epsilon": 1}

    def test_all_ids_are_12_digits_and_fake(self):
        data = _import()
        for biz in data["accounts"]["businesses"]:
            for acct in biz["accounts"]:
                assert len(acct["id"]) == 12 and acct["id"].isdigit()
                # fake range or the deliberate leading-zero fixture ID
                assert acct["id"].startswith("10000") or \
                    acct["id"] == "000000000982"

    def test_role_arns_built_from_sheet(self):
        data = _import()
        biz_beta = next(b for b in data["accounts"]["businesses"]
                  if b["name"] == "beta")
        tds = next(a for a in biz_beta["accounts"] if a["name"] == "beta-tds")
        assert tds["role_arn"] == \
            "arn:aws:iam::100000000009:role/beta-tds-full-admin-trust-role"

    def test_login_account_has_no_role(self):
        data = _import()
        biz_alpha = next(b for b in data["accounts"]["businesses"]
                  if b["name"] == "alpha")
        shared = next(a for a in biz_alpha["accounts"]
                      if a["name"] == "alpha-shared-iac")
        assert shared["role_arn"] is None

    def test_generated_yaml_loads_as_valid_config(self, tmp_path):
        """The script's output must be a loadable HarnessConfig —
        including the leading-zero ID surviving the YAML round-trip."""
        import yaml

        from harness_primitives.config import load_config
        data = _import()
        out = tmp_path / "gen.yaml"
        out.write_text(yaml.safe_dump(data, sort_keys=False,
                                      default_flow_style=False))
        config = load_config(out)
        biz_alpha = config.accounts.business("alpha")
        ids = [a.id for a in biz_alpha.accounts]
        assert "000000000982" in ids          # leading zero preserved
        live = next(a for a in biz_alpha.accounts if a.name == "alpha-live-iac")
        assert live.role_arn == \
            "arn:aws:iam::000000000982:role/live-full-admin-trust-role"
        assert sum(len(b.accounts) for b in config.accounts.businesses) == 24
