"""
IAM Plugin — Identity and Access Management (real implementation).

IAM is a GLOBAL service: one call per account, never region fan-out.

Uses the standard runtime pipeline (config → resolver → executor →
PartialResult → emit) like every other plugin, so --account,
--all-accounts, --output and partial-failure semantics all work.
"""

from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities

IAM_CAPABILITIES = PluginCapabilities(
    name="iam",
    display_name="IAM",
    supports_read=True,
    supports_create=True,
    supports_delete=True,
    supports_safe_ops=True,
    is_global_service=True,
    max_rps=(("iam", 5.0),),
    rate_limit_strict=False,
)


class IAMPlugin(BasePlugin):
    """IAM service plugin."""

    CAPABILITIES = IAM_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        """List IAM users (default) or roles. Global — region ignored."""
        resource_type = filters.pop("type", "users")
        if resource_type == "roles":
            yield from self.list_roles(session)
        elif resource_type == "policies":
            yield from self.list_policies(session)
        else:
            yield from self.list_users(session)

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        """Get a single IAM user by name."""
        return self.get_user(session, resource_id)

    def safe_op(self, session: Any, operation: str, resource_id: str,
                **params) -> dict:
        """Safe operations: rotate-keys, check-mfa."""
        if operation == "rotate-keys":
            return self.rotate_keys(session, resource_id,
                                    secret_output_file=params.get("secret_output_file"))
        if operation == "check-mfa":
            return self.check_mfa(session, resource_id)
        raise NotImplementedError(f"IAM does not support safe op: {operation}")

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        """IAM has no native DryRun — simulate locally."""
        return {"service": "iam", "operation": operation, "params": params,
                "status": "would_execute"}

    def audit(self, session: Any, region: Optional[str] = None) -> dict:
        """Audit: users without MFA, unused access keys."""
        findings = []
        for user in self.list_users(session):
            username = user["name"]  # normalized row (pass-3 fix)
            mfa = self.check_mfa(session, username)
            if not mfa["mfa_enabled"]:
                findings.append({
                    "type": "user_without_mfa",
                    "resource_id": username,
                    "message": f"User {username} has no MFA device",
                })
        return {"service": "iam", "compliant": not findings, "findings": findings}

    def create_app(self) -> typer.Typer:
        """Typer sub-app for IAM commands (global — no region fan-out)."""
        iam_app = typer.Typer(name="iam", help="IAM management")
        plugin = IAMPlugin()

        def _sweep(fn, account, all_accounts):
            """Run an account-level IAM call through the standard pipeline."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import (
                build_stack,
                emit,
                get_runtime,
                resolve_accounts,
            )

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                accounts = resolve_accounts(resolver, account, all_accounts)
                result = executor.execute_across_accounts(
                    accounts,
                    lambda sess, acct: fn(sess),
                    service="iam",
                )
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @iam_app.command("list-users")
        def list_users_cmd(
            account: Optional[str] = typer.Option(None, "--account",
                                                   help="Account ID/name/OU path"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List IAM users."""
            _sweep(lambda s: list(plugin.list_users(s)), account, all_accounts)

        @iam_app.command("list-roles")
        def list_roles_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List IAM roles."""
            _sweep(lambda s: [
                {k: v for k, v in r.items() if k in
                 ("RoleName", "Arn", "CreateDate", "Path", "RoleId")}
                for r in plugin.list_roles(s)
            ], account, all_accounts)

        @iam_app.command("list-access-keys")
        def list_access_keys_cmd(
            username: str = typer.Argument(..., help="IAM username"),
            account: Optional[str] = typer.Option(None, "--account"),
        ):
            """List access keys for a user (status, age)."""
            _sweep(lambda s: plugin.list_access_keys(s, username),
                   account, False)

        @iam_app.command("check-mfa")
        def check_mfa_cmd(
            username: str = typer.Argument(..., help="IAM username"),
            account: Optional[str] = typer.Option(None, "--account"),
        ):
            """Check MFA status for a user."""
            _sweep(lambda s: plugin.check_mfa(s, username), account, False)

        @iam_app.command("rotate-keys")
        def rotate_keys_cmd(
            username: str = typer.Argument(..., help="IAM username"),
            account: Optional[str] = typer.Option(None, "--account"),
            output: Optional[str] = typer.Option(
                None, "--output-file",
                help="Write the new secret to this file (default: cache dir, 0600)"),
            dry_run: bool = typer.Option(
                False, "--dry-run",
                help="Show what would rotate without touching any keys"),
        ):
            """Rotate access keys. Secret goes to a 0600 file, never stdout."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import (
        build_stack,
        emit,
        ensure_mutable,
        get_runtime,
        record_audit,
    )
            from harness_primitives.output import FailureMsg, PartialResult

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                acct = resolver.resolve(account)
                sess = executor.session_for(acct)
                ensure_mutable(acct)
                effective_dry_run = bool(dry_run or get_ctx().get("dry_run"))
                try:
                    if effective_dry_run:
                        # Read-only simulation: show current keys, no changes
                        keys = plugin.list_access_keys(sess, username)
                        active = [k["key_id"] for k in keys
                                  if k["status"] == "Active"]
                        data = {
                            "username": username,
                            "dry_run": True,
                            "would_create": "a new access key",
                            "would_deactivate": active,
                            "message": "No changes made (dry-run)",
                        }
                    else:
                        data = plugin.rotate_keys(sess, username,
                                                   secret_output_file=output)
                    record_audit(
                        config, action="rotate-keys", service="iam",
                        account_id=acct.id, region="_global",
                        resource_id=username, success=True,
                        dry_run=effective_dry_run,
                        principal=sess.source_identity,
                    )
                    emit(PartialResult(success={username: data}),
                         get_ctx().get("output", "table"))
                except typer.Exit:
                    raise  # emit() success — NOT a failure
                except Exception as e:
                    err = getattr(e, "response", {}).get("Error", {})
                    record_audit(
                        config, action="rotate-keys", service="iam",
                        account_id=acct.id, region="_global",
                        resource_id=username, success=False,
                        error_message=str(err.get("Message", e))[:300],
                        dry_run=effective_dry_run,
                        principal=sess.source_identity,
                    )
                    result = PartialResult()
                    result.failures.append(FailureMsg(
                        account_id=acct.id, service="iam",
                        error_code=err.get("Code", type(e).__name__),
                        message=str(err.get("Message", e))[:300],
                    ))
                    emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @iam_app.command("find-unused")
        def find_unused_cmd(
            days: int = typer.Option(90, "--days", help="Days since last use"),
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """Find access keys unused for more than N days."""
            _sweep(lambda s: plugin.find_unused(s, days=days),
                   account, all_accounts)

        @iam_app.command("audit")
        def audit_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """Audit: users without MFA."""
            _sweep(lambda s: plugin.audit(s), account, all_accounts)

        return iam_app

    # ─── IAM operations ─────────────────────────────────────────

    def list_users(self, session: Any, max_items: int = 100) -> list[dict]:
        """List IAM users with pagination."""
        client = session.get_client("iam")
        users = []
        marker = None
        while True:
            kwargs = {"MaxItems": max_items}
            if marker:
                kwargs["Marker"] = marker
            resp = client.list_users(**kwargs)
            users.extend(resp.get("Users", []))
            if resp.get("IsTruncated"):
                marker = resp["Marker"]
            else:
                break
        # Contract rows (resource_id is required by the inventory
        # collector — found live, pass 3: KeyError 'resource_id')
        return [{
            "resource_id": u["UserName"],
            "name": u["UserName"],
            "arn": u.get("Arn"),
            "created": str(u.get("CreateDate", "")),
            "path": u.get("Path"),
            "user_id": u.get("UserId"),
            "raw": u,
        } for u in users]

    def list_roles(self, session: Any, max_items: int = 100) -> list[dict]:
        """List IAM roles with pagination."""
        client = session.get_client("iam")
        roles = []
        marker = None
        while True:
            kwargs = {"MaxItems": max_items}
            if marker:
                kwargs["Marker"] = marker
            resp = client.list_roles(**kwargs)
            roles.extend(resp.get("Roles", []))
            if resp.get("IsTruncated"):
                marker = resp["Marker"]
            else:
                break
        return [{
            "resource_id": r["RoleName"],
            "name": r["RoleName"],
            "arn": r.get("Arn"),
            "created": str(r.get("CreateDate", "")),
            "path": r.get("Path"),
            "raw": r,
        } for r in roles]

    def list_policies(self, session: Any, scope: str = "Local",
                      max_items: int = 100) -> list[dict]:
        """List IAM policies (Local = customer-managed only)."""
        client = session.get_client("iam")
        policies = []
        marker = None
        while True:
            kwargs = {"Scope": scope, "MaxItems": max_items}
            if marker:
                kwargs["Marker"] = marker
            resp = client.list_policies(**kwargs)
            policies.extend(resp.get("Policies", []))
            if resp.get("IsTruncated"):
                marker = resp["Marker"]
            else:
                break
        return [{
            "resource_id": p.get("PolicyName", p.get("Arn", "")),
            "name": p.get("PolicyName"),
            "arn": p.get("Arn"),
            "created": str(p.get("CreateDate", "")),
            "raw": p,
        } for p in policies]

    def list_access_keys(self, session: Any, username: str) -> list[dict]:
        """List a user's access keys with age."""
        from datetime import datetime, timezone
        client = session.get_client("iam")
        keys = client.list_access_keys(UserName=username).get("AccessKeyMetadata", [])
        now = datetime.now(timezone.utc)
        rows = []
        for key in keys:
            created = key.get("CreateDate")
            age_days = (now - created).days if created else None
            rows.append({
                "key_id": key["AccessKeyId"],
                "status": key.get("Status"),
                "created": str(created or ""),
                "age_days": age_days,
            })
        return rows

    def get_user(self, session: Any, username: str) -> Optional[dict]:
        """Get a single IAM user."""
        client = session.get_client("iam")
        try:
            resp = client.get_user(UserName=username)
            return resp.get("User")
        except client.exceptions.NoSuchEntityException:
            return None

    def create_user(self, session: Any, username: str,
                    groups: list[str] | None = None) -> dict:
        """Create an IAM user."""
        client = session.get_client("iam")
        resp = client.create_user(UserName=username, Path="/")
        user = resp["User"]
        for group in groups or []:
            client.add_user_to_group(UserName=username, GroupName=group)
        return user

    def delete_user(self, session: Any, username: str, force: bool = False) -> dict:
        """Delete an IAM user with full teardown.

        IAM requires detaching policies, removing from groups, deleting
        MFA devices and access keys BEFORE deleting the user.
        """
        client = session.get_client("iam")
        report = {"username": username, "removed": []}

        keys = client.list_access_keys(UserName=username).get("AccessKeyMetadata", [])
        if keys and not force:
            raise PermissionError(
                f"User {username} has {len(keys)} access key(s). "
                "Use force=True to delete (keys will be removed)."
            )
        for key in keys:
            client.delete_access_key(UserName=username,
                                     AccessKeyId=key["AccessKeyId"])
            report["removed"].append(f"access-key:{key['AccessKeyId']}")

        for policy in client.list_attached_user_policies(
                UserName=username).get("AttachedPolicies", []):
            client.detach_user_policy(UserName=username,
                                      PolicyArn=policy["PolicyArn"])
            report["removed"].append(f"policy:{policy['PolicyName']}")

        for group in client.list_groups_for_user(
                UserName=username).get("Groups", []):
            client.remove_user_from_group(UserName=username,
                                          GroupName=group["GroupName"])
            report["removed"].append(f"group:{group['GroupName']}")

        for mfa in client.list_mfa_devices(
                UserName=username).get("MFADevices", []):
            client.deactivate_mfa_device(UserName=username,
                                          SerialNumber=mfa["SerialNumber"])
            report["removed"].append(f"mfa:{mfa['SerialNumber']}")

        try:
            client.delete_login_profile(UserName=username)
            report["removed"].append("login-profile")
        except client.exceptions.NoSuchEntityException:
            pass

        client.delete_user(UserName=username)
        report["removed"].append("user")
        return report

    def rotate_keys(self, session: Any, username: str,
                    secret_output_file: Optional[str] = None) -> dict:
        """Rotate access keys. The secret is NEVER returned in the result:
        it is written to a 0600 file and only its location is reported."""
        import os
        from pathlib import Path
        client = session.get_client("iam")

        new_key = client.create_access_key(UserName=username)
        new_access = new_key["AccessKey"]["AccessKeyId"]
        new_secret = new_key["AccessKey"]["SecretAccessKey"]

        deactivated = 0
        for key in client.list_access_keys(UserName=username)["AccessKeyMetadata"]:
            if key["AccessKeyId"] != new_access and key["Status"] == "Active":
                client.update_access_key(UserName=username,
                                          AccessKeyId=key["AccessKeyId"],
                                          Status="Inactive")
                deactivated += 1

        secret_dir = Path.home() / ".cache" / "aws-harness" / "credentials"
        secret_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(secret_dir, 0o700)
        secret_path = (Path(secret_output_file).expanduser() if secret_output_file
                       else secret_dir / f"{new_access}.secret")

        fd = os.open(str(secret_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(new_secret)
        os.chmod(secret_path, 0o600)

        return {
            "username": username,
            "new_access_key": new_access,
            "secret_location": str(secret_path),
            "deactivated_count": deactivated,
            "message": f"Secret written to {secret_path} (0600). "
                       "Update your consumer, then delete the old keys.",
        }

    def check_mfa(self, session: Any, username: str) -> dict:
        """Check MFA status for a user."""
        client = session.get_client("iam")
        devices = client.list_mfa_devices(UserName=username).get("MFADevices", [])
        return {
            "username": username,
            "mfa_enabled": len(devices) > 0,
            "mfa_count": len(devices),
        }

    def find_unused(self, session: Any, days: int = 90) -> list[dict]:
        """Find access keys unused (or never used) for more than `days`."""
        from datetime import datetime, timezone
        client = session.get_client("iam")
        now = datetime.now(timezone.utc)
        unused = []
        for user in self.list_users(session):
            username = user["name"]  # list_users returns normalized rows
            for key in client.list_access_keys(
                    UserName=username)["AccessKeyMetadata"]:
                info = client.get_access_key_last_used(AccessKeyId=key["AccessKeyId"])
                last_used = info.get("AccessKeyLastUsed", {}).get("LastUsedDate")
                if last_used:
                    delta_days = (now - last_used).days
                    if delta_days > days:
                        unused.append({
                            "type": "access_key",
                            "username": username,
                            "key_id": key["AccessKeyId"],
                            "last_used": str(last_used),
                            "days_since_used": delta_days,
                        })
                else:
                    created = key.get("CreateDate")
                    if created:
                        delta_days = (now - created).days
                        if delta_days > days:
                            unused.append({
                                "type": "access_key_never_used",
                                "username": username,
                                "key_id": key["AccessKeyId"],
                                "created": str(created),
                                "days_since_creation": delta_days,
                            })
        return unused
