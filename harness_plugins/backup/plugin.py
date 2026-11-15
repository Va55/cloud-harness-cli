"""
AWS Backup Plugin (real implementation).

Regional service. Phase 1 (v22): read + one safe op:
- list-vaults           backup vaults (+ lock state)
- list-plans            backup plans
- list-recovery-points  recovery points per vault (dates, sizes, status)
- list-jobs             backup/restore job history — the actionable one:
                       FAILED jobs are why people care about backups
- audit                 failed jobs in the period, empty vaults
- start-backup          on-demand backup job (SAFE OP, dry-run default:
                       AWS Backup has no native DryRun — the router and
                       CLI simulate locally)

Deliberately OUT of scope (v1): delete recovery points (never — data
loss), restore (high blast radius; needs confirmation flow), vault
lock changes (compliance-critical).

Restore advice: `harness backup list-recovery-points` finds the point;
the actual restore is done in the console or IaC — deliberately.
"""

from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities

BACKUP_CAPABILITIES = PluginCapabilities(
    name="backup",
    display_name="AWS Backup",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=True,
    is_global_service=False,
    max_rps=(("backup", 5.0),),
    rate_limit_strict=False,
)

# Job states worth surfacing
PROBLEM_STATES = ("FAILED", "ABORTED", "EXPIRED")


class BackupPlugin(BasePlugin):
    """AWS Backup service plugin."""

    CAPABILITIES = BACKUP_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        resource_type = filters.pop("type", "vaults")
        if resource_type == "plans":
            yield from self.list_plans(session, region)
        else:
            yield from self.list_vaults(session, region)

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        client = session.get_client("backup", region)
        try:
            vault = client.describe_backup_vault(BackupVaultName=resource_id)
            return self._vault_row(vault)
        except client.exceptions.ClientError:
            return None

    def safe_op(self, session: Any, operation: str, resource_id: str,
                **params) -> dict:
        """Safe ops: start-backup (on-demand backup job)."""
        if operation != "start-backup":
            raise NotImplementedError(
                f"AWS Backup does not support safe op: {operation}"
            )
        return self.start_backup(
            session, resource_id,
            vault_name=params.get("vault_name"),
            iam_role_arn=params.get("iam_role_arn"),
            region=params.get("region"),
        )

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        """AWS Backup has no native DryRun — simulate locally."""
        return {
            "service": "backup",
            "operation": operation,
            "resource_arn": params.get("resource_id"),
            "vault": params.get("vault_name"),
            "status": "would_execute",
            "message": "Would start an on-demand backup job. "
                       "No API call was made.",
        }

    def audit(self, session: Any, region: Optional[str] = None) -> dict:
        """Backup audit: failed/aborted jobs in the last 7 days and
        vaults with no recovery points (backups configured but nothing
        being written — the quiet disaster)."""
        findings = []
        client = session.get_client("backup", region)

        # Problem jobs (FAILED/ABORTED/EXPIRED) — list_backup_jobs
        # has no time filter; we surface states, the caller reads dates.
        for page in client.get_paginator("list_backup_jobs").paginate():
            for job in page.get("BackupJobs", []):
                state = job.get("State", "")
                if state in PROBLEM_STATES:
                    findings.append({
                        "type": f"backup_job_{state.lower()}",
                        "resource_id": job.get("ResourceArn", ""),
                        "message": f"Backup job for "
                                   f"{(job.get('ResourceArn') or '?')[-40:]} "
                                   f"{state.lower()} "
                                   f"({job.get('StatusMessage') or 'no detail'})",
                    })

        for vault in self.list_vaults(session, region):
            if vault.get("recovery_points") == 0:
                findings.append({
                    "type": "empty_vault",
                    "resource_id": vault["resource_id"],
                    "message": f"Vault {vault['resource_id']} has zero "
                               "recovery points — nothing is being backed "
                               "up into it",
                })

        return {"service": "backup", "compliant": not findings,
                "findings": findings}

    def create_app(self) -> typer.Typer:
        """Typer sub-app for AWS Backup commands."""
        backup_app = typer.Typer(name="backup", help="AWS Backup "
                                                      "(vaults, plans, jobs)")
        plugin = BackupPlugin()

        def _run(collect_fn, account, region, all_accounts):
            """Standard pipeline: resolve → sweep regions → emit."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import (
                build_stack,
                emit,
                get_runtime,
                regions_for,
                resolve_accounts,
            )

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                accounts = resolve_accounts(resolver, account, all_accounts)

                def per_account(sess, acct):
                    regions = ([region] if region
                               else regions_for(acct, config, sess, store))
                    return executor.execute_across_regions(
                        regions, collect_fn,
                        session=sess, account_id=acct.id, service="backup",
                    )

                result = executor.execute_across_accounts(accounts, per_account)
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @backup_app.command("list-vaults")
        def list_vaults_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List backup vaults (lock status, recovery point count)."""
            _run(lambda s, r: list(plugin.list_vaults(s, r)),
                 account, region, all_accounts)

        @backup_app.command("list-plans")
        def list_plans_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List backup plans."""
            _run(lambda s, r: list(plugin.list_plans(s, r)),
                 account, region, all_accounts)

        @backup_app.command("list-recovery-points")
        def list_recovery_points_cmd(
            vault: str = typer.Option(..., "--vault", help="Vault name"),
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """List recovery points in a vault (dates, sizes, status)."""
            _run(lambda s, r: list(plugin.list_recovery_points(s, r, vault)),
                 account, region, False)

        @backup_app.command("list-jobs")
        def list_jobs_cmd(
            state: Optional[str] = typer.Option(
                None, "--state", help="Filter: COMPLETED|FAILED|RUNNING|ABORTED"),
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """List backup jobs — `--state FAILED` is the point."""
            _run(lambda s, r: list(plugin.list_jobs(s, r, state=state)),
                 account, region, False)

        @backup_app.command("audit")
        def audit_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """Audit: failed jobs, vaults with zero recovery points."""
            _run(lambda s, r: plugin.audit(s, r),
                 account, region, all_accounts)

        @backup_app.command("start-backup")
        def start_backup_cmd(
            resource_arn: str = typer.Argument(
                ..., help="Resource ARN to back up (e.g. an EC2 ARN)"),
            vault: str = typer.Option(..., "--vault", help="Vault name"),
            iam_role: str = typer.Option(
                ..., "--iam-role", help="IAM role ARN the backup service "
                                       "assumes"),
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            dry_run: bool = typer.Option(False, "--dry-run"),
        ):
            """Start an on-demand backup job (SAFE OP — dry-run default)."""
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
                effective_dry_run = bool(
                    dry_run or get_ctx().get("dry_run"))
                try:
                    if effective_dry_run:
                        data = plugin.dry_run_simulate(
                            sess, "start-backup",
                            resource_id=resource_arn,
                            vault_name=vault,
                            iam_role_arn=iam_role,
                            region=region,
                        )
                    else:
                        data = plugin.safe_op(
                            sess, "start-backup", resource_arn,
                            vault_name=vault, iam_role_arn=iam_role,
                            region=region,
                        )
                    record_audit(
                        config, action="start-backup", service="backup",
                        account_id=acct.id, region=region,
                        resource_id=resource_arn, success=True,
                        dry_run=effective_dry_run,
                        principal=sess.source_identity,
                    )
                    emit(PartialResult(success={resource_arn: data}),
                         get_ctx().get("output", "table"))
                except typer.Exit:
                    raise  # emit() success — NOT a failure
                except Exception as e:
                    err = getattr(e, "response", {}).get("Error", {})
                    record_audit(
                        config, action="start-backup", service="backup",
                        account_id=acct.id, region=region,
                        resource_id=resource_arn, success=False,
                        error_message=str(err.get("Message", e))[:300],
                        dry_run=effective_dry_run,
                        principal=sess.source_identity,
                    )
                    result = PartialResult()
                    result.failures.append(FailureMsg(
                        account_id=acct.id, region=region, service="backup",
                        error_code=err.get("Code", type(e).__name__),
                        message=str(err.get("Message", e))[:300],
                    ))
                    emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        return backup_app

    # ─── Operations ─────────────────────────────────────────────

    def list_vaults(self, session: Any,
                    region: Optional[str] = None) -> Iterator[dict]:
        """List backup vaults: lock state, encryption, recovery points."""
        client = session.get_client("backup", region)
        paginator = client.get_paginator("list_backup_vaults")
        for page in paginator.paginate():
            for vault in page.get("BackupVaultList", []):
                yield self._vault_row(vault)

    def list_plans(self, session: Any,
                   region: Optional[str] = None) -> Iterator[dict]:
        """List backup plans."""
        client = session.get_client("backup", region)
        paginator = client.get_paginator("list_backup_plans")
        for page in paginator.paginate():
            for plan in page.get("BackupPlansList", []):
                yield {
                    "resource_id": plan.get("BackupPlanId"),
                    "name": plan.get("BackupPlanName"),
                    "version": plan.get("VersionId", "")[:8],
                    "last_delete_audit": plan.get("LastDeleteDate"),
                    "raw": plan,
                }

    def list_recovery_points(self, session: Any, region: Optional[str],
                             vault_name: str) -> Iterator[dict]:
        """List recovery points in a vault."""
        client = session.get_client("backup", region)
        paginator = client.get_paginator("list_recovery_points_by_backup_vault")
        for page in paginator.paginate(BackupVaultName=vault_name):
            for rp in page.get("RecoveryPoints", []):
                yield {
                    "resource_id": rp.get("RecoveryPointArn", "")[-40:],
                    "resource": rp.get("ResourceArn", "")[-40:],
                    "status": rp.get("Status"),
                    "created": str(rp.get("CreationDate", "")),
                    "size_mb": (rp.get("BackupSizeInBytes", 0) or 0) // (1024 * 1024),
                    "vault": vault_name,
                    "raw": rp,
                }

    def list_jobs(self, session: Any, region: Optional[str] = None,
                  state: Optional[str] = None) -> Iterator[dict]:
        """List backup jobs, optionally filtered by state."""
        client = session.get_client("backup", region)
        paginator = client.get_paginator("list_backup_jobs")
        for page in paginator.paginate():
            for job in page.get("BackupJobs", []):
                if state and job.get("State") != state.upper():
                    continue
                yield {
                    "resource_id": job.get("JobId", "")[:16],
                    "resource": (job.get("ResourceArn", "") or "?")[-40:],
                    "state": job.get("State"),
                    "created": str(job.get("CreationDate", "")),
                    "completed": str(job.get("CompletionDate", "")),
                    "message": (job.get("StatusMessage") or "")[:60],
                    "raw": job,
                }

    def start_backup(self, session: Any, resource_arn: str,
                     vault_name: Optional[str] = None,
                     iam_role_arn: Optional[str] = None,
                     region: Optional[str] = None) -> dict:
        """Start an on-demand backup job."""
        if not vault_name:
            raise ValueError("start-backup requires --vault")
        if not iam_role_arn:
            raise ValueError("start-backup requires --iam-role")
        client = session.get_client("backup", region)
        resp = client.start_backup_job(
            BackupVaultName=vault_name,
            ResourceArn=resource_arn,
            IamRoleArn=iam_role_arn,
        )
        return {
            "job_id": resp.get("BackupJobId", ""),
            "resource": resource_arn,
            "vault": vault_name,
            "message": "Backup job started — check "
                       f"harness backup list-jobs --region {region or ''}",
        }

    @staticmethod
    def _vault_row(vault: dict) -> dict:
        return {
            "resource_id": vault.get("BackupVaultName"),
            "arn": vault.get("BackupVaultArn"),
            "locked": vault.get("Locked", False),
            "min_retention_days": vault.get("MinRetentionDays"),
            "recovery_points": vault.get("NumberOfRecoveryPoints", 0),
            "created": str(vault.get("CreationDate", "")),
            "raw": vault,
        }
