#!/usr/bin/env python3
# ruff: noqa: N999  (hyphenated CLI script, not an importable module)
"""Import AWS accounts from the accounts spreadsheet into harness config.

Reads AWS_ACCOUNTS_AND_ADMIN_ROLES.xlsx (one sheet per business:
Alias | ID | Role) and emits a harness businesses config:

  - One BusinessConfig per sheet (profile = business name lowercased —
    ADJUST to match your ~/.aws/credentials profile names)
  - Manual discovery per business (the sheet IS the account inventory)
  - Explicit role_arn per account: arn:aws:iam::<ID>:role/<Role>
    (role names are per-account aliases — no template fits them)
  - Accounts without a Role (e.g. the shared/login account) get
    role_arn: null → used with profile credentials directly

Usage:
    python3 scripts/import-accounts-xlsx.py <spreadsheet.xlsx> [out.yaml]

The generated file is a starting point: fix the profile names, add
defaults/regions as needed, then copy to ~/.config/cloud-harness/config.yaml
"""

import sys
from pathlib import Path

import openpyxl
import yaml

# The login/shared accounts (no switch-role) — reached with their own
# profile credentials, no assumption.
NO_ROLE_HINTS = ("shared",)


def _clean(value) -> str:
    """Trim the sheet's stray whitespace, stringify IDs."""
    if value is None:
        return ""
    return str(value).strip()


def import_accounts(xlsx_path: Path) -> dict:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    businesses = []
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
        if not rows or _clean(rows[0][0]).lower() != "alias":
            continue  # not an account sheet
        accounts = []
        biz_name = sheet.strip()
        for row in rows[1:]:
            if row is None or all(c is None for c in row):
                continue
            alias, account_id, role = (_clean(row[0]) if len(row) > 0 else "",
                                       _clean(row[1]) if len(row) > 1 else "",
                                       _clean(row[2]) if len(row) > 2 else "")
            if not account_id or not account_id.isdigit() or len(account_id) != 12:
                print(f"  [WARN] {biz_name}: skipping malformed row: {row!r}",
                      file=sys.stderr)
                continue
            role_arn = (f"arn:aws:iam::{account_id}:role/{role}"
                        if role else None)
            if not role and not any(h in alias.lower() for h in NO_ROLE_HINTS):
                print(f"  [WARN] {biz_name}/{alias}: no role and not a known "
                      f"login account — assuming direct profile credentials",
                      file=sys.stderr)
            accounts.append({
                "id": account_id,
                "name": alias,
                "role_arn": role_arn,
            })
        if not accounts:
            continue
        businesses.append({
            "name": biz_name,
            "profile": biz_name.lower(),  # ADJUST to your AWS profile
            "discovery": "manual",
            "accounts": accounts,
        })
        print(f"{biz_name}: {len(accounts)} account(s)")
    return {"accounts": {"discovery": "manual", "businesses": businesses}}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    xlsx = Path(sys.argv[1]).expanduser()
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    config = import_accounts(xlsx)
    if not config["accounts"]["businesses"]:
        print("No businesses found — wrong file?", file=sys.stderr)
        sys.exit(2)

    body = yaml.safe_dump(config, sort_keys=False, default_flow_style=False)

    header = """\
# Cloud Harness CLI config — generated from {xlsx}
# by scripts/import-accounts-xlsx.py on {date}
#
# TODO before use:
#   1. Fix each business's `profile:` to match your ~/.aws/credentials
#      profile names (generated as the business name lowercased).
#   2. Copy to ~/.config/cloud-harness/config.yaml
#
# Accounts without role_arn (e.g. the shared login account) are used
# with their profile's credentials directly.

""".format(xlsx=xlsx,
           date=__import__("datetime").date.today().isoformat())

    if out:
        out.write_text(header + body)
        print(f"\nWritten: {out}")
    else:
        print(header + body)


if __name__ == "__main__":
    main()
