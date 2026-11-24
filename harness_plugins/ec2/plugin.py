"""
EC2 Plugin — compute (real implementation).

Phase 1: read (instances, SGs, volumes, snapshots, EIPs) + safe ops
(start/stop with native EC2 DryRun support).
EC2 is regional — fan out per region.
"""

from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities

EC2_CAPABILITIES = PluginCapabilities(
    name="ec2",
    display_name="EC2",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=True,
    is_global_service=False,
    max_rps=(("ec2", 5.0),),
    rate_limit_strict=False,
)

# Console deep-link templates (region + resource id interpolated)
CONSOLE_URLS = {
    "instance": "https://{region}.console.aws.amazon.com/ec2/home?region={region}#InstanceDetails:instanceId={id}",
    "volume": "https://{region}.console.aws.amazon.com/ec2/home?region={region}#VolumesDetails:volumeId={id}",
    "security-group": "https://{region}.console.aws.amazon.com/ec2/v2/home?region={region}#SecurityGroups:group-id={id}",
}


class EC2Plugin(BasePlugin):
    """EC2 service plugin."""

    CAPABILITIES = EC2_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        """List EC2 instances (default resource type)."""
        resource_type = filters.pop("type", "instances")
        if resource_type == "security-groups":
            yield from self.list_security_groups(session, region)
        elif resource_type == "volumes":
            yield from self.list_volumes(session, region)
        elif resource_type == "snapshots":
            yield from self.list_snapshots(session, region)
        elif resource_type == "eips":
            yield from self.list_eips(session, region)
        else:
            yield from self.list_instances(session, region, **filters)

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        """Get a single instance by ID. Returns None if not found
        (InvalidInstanceID.NotFound is the AWS behavior for bad IDs)."""
        client = session.get_client("ec2", region)
        try:
            resp = client.describe_instances(InstanceIds=[resource_id])
        except client.exceptions.ClientError as e:
            if e.response.get("Error", {}).get("Code") == "InvalidInstanceID.NotFound":
                return None
            raise
        reservations = resp.get("Reservations", [])
        for r in reservations:
            for inst in r.get("Instances", []):
                return self._instance_row(inst)
        return None

    def safe_op(self, session: Any, operation: str, resource_id: str,
                region: Optional[str] = None, dry_run: bool = False,
                **params) -> dict:
        """Safe ops: start/stop (native EC2 DryRun support)."""
        client = session.get_client("ec2", region)
        kwargs = {"InstanceIds": [resource_id]}
        if dry_run:
            kwargs["DryRun"] = True

        if operation == "start":
            try:
                resp = client.start_instances(**kwargs)
                return self._transition(resp, "starting")
            except client.exceptions.ClientError as e:
                return self._handle_dryrun_or_raise(e, "start", resource_id)
        if operation == "stop":
            kwargs.setdefault("Force", params.get("force", False))
            try:
                resp = client.stop_instances(**kwargs)
                return self._transition(resp, "stopping")
            except client.exceptions.ClientError as e:
                return self._handle_dryrun_or_raise(e, "stop", resource_id)
        raise NotImplementedError(f"EC2 does not support safe op: {operation}")

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        """EC2 has native DryRun — the real call is made with DryRun=True."""
        return self.safe_op(session, operation, dry_run=True, **params)

    def audit(self, session: Any, region: Optional[str] = None) -> dict:
        """Audit: instances with public IPs, wide-open security groups."""
        findings = []
        # Public instances
        for inst in self.list_instances(session, region):
            if inst.get("public_ip"):
                findings.append({
                    "type": "public_instance",
                    "resource_id": inst["resource_id"],
                    "message": "Instance has a public IP",
                })
        # Wide-open SGs (0.0.0.0/0 on port 22 or all ports)
        for sg in self.list_security_groups(session, region):
            for perm in sg.get("ip_permissions", []):
                for ip_range in perm.get("IpRanges", []):
                    cidr = ip_range.get("CidrIp", "")
                    if cidr == "0.0.0.0/0" and (
                        perm.get("FromPort") in (22, None)
                        or perm.get("IpProtocol") == "-1"
                    ):
                        findings.append({
                            "type": "open_security_group",
                            "resource_id": sg["resource_id"],
                            "message": f"SG {sg['name']} allows {cidr} "
                                       f"on port {perm.get('FromPort', 'ALL')}",
                        })
        return {"service": "ec2", "compliant": not findings, "findings": findings}

    def create_app(self) -> typer.Typer:
        """Typer sub-app for EC2 commands."""
        ec2_app = typer.Typer(name="ec2", help="EC2 management")
        plugin = EC2Plugin()

        @ec2_app.command("list-instances")
        def list_instances(
            account: Optional[str] = typer.Option(None, "--account",
                                                    help="Account ID/name/OU path"),
            region: Optional[str] = typer.Option(None, "--region", help="Region"),
            state: Optional[str] = typer.Option(None, "--state",
                                                 help="Filter: running|stopped|pending"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List EC2 instances across accounts × regions."""
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
                        regions,
                        lambda s, r: list(plugin.list_instances(s, r, state=state)),
                        session=sess, account_id=acct.id, service="ec2",
                    )

                result = executor.execute_across_accounts(accounts, per_account)
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @ec2_app.command("describe")
        def describe(
            instance_id: str = typer.Argument(..., help="Instance ID (i-...)"),
            account: Optional[str] = typer.Option(None, "--account"),
            region: str = typer.Option(..., "--region", help="Region (required — EC2 is regional)"),
        ):
            """Describe one instance."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import build_stack, emit, get_runtime

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                acct = resolver.resolve(account)
                sess = executor.session_for(acct)
                try:
                    inst = plugin.get_resource(sess, instance_id, region)
                except Exception as e:
                    # Never a raw traceback (project rule): malformed IDs,
                    # permission drift etc. land in the failure block.
                    err = getattr(e, "response", {}).get("Error", {})
                    from harness_primitives.output import FailureMsg, PartialResult
                    result = PartialResult()
                    result.failures.append(FailureMsg(
                        account_id=acct.id, region=region, service="ec2",
                        error_code=err.get("Code", type(e).__name__),
                        message=str(err.get("Message", e))[:300],
                    ))
                    emit(result, get_ctx().get("output", "table"))
                    raise typer.Exit(result.exit_code) from None
                if inst is None:
                    typer.echo(f"Instance {instance_id} not found in {region}", err=True)
                    raise typer.Exit(1)
                from harness_primitives.output import PartialResult
                result = PartialResult(success={instance_id: inst})
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @ec2_app.command("start")
        def start(
            instance_id: str = typer.Argument(...),
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(
                None, "--region", help="Region (auto-detected if omitted)"),
            yes: bool = typer.Option(
                False, "--yes", help="Execute for real (default: dry-run)"),
            dry_run: bool = typer.Option(
                False, "--dry-run", help="Force simulation (the default)"),
        ):
            """Start an instance (safe op — dry-run by default)."""
            _run_safe_op(plugin, "start", instance_id, account, region,
                         yes, dry_run)

        @ec2_app.command("stop")
        def stop(
            instance_id: str = typer.Argument(...),
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(
                None, "--region", help="Region (auto-detected if omitted)"),
            force: bool = typer.Option(False, "--force"),
            yes: bool = typer.Option(
                False, "--yes", help="Execute for real (default: dry-run)"),
            dry_run: bool = typer.Option(
                False, "--dry-run", help="Force simulation (the default)"),
        ):
            """Stop an instance (safe op — dry-run by default)."""
            _run_safe_op(plugin, "stop", instance_id, account, region,
                         yes, dry_run, force=force)

        @ec2_app.command("security-groups")
        def security_groups(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """List security groups."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import build_stack, emit, get_runtime, regions_for

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                acct = resolver.resolve(account)
                sess = executor.session_for(acct)
                regions = ([region] if region
                           else regions_for(acct, config, sess, store))
                result = executor.execute_across_regions(
                    regions,
                    lambda s, r: list(plugin.list_security_groups(s, r)),
                    session=sess, account_id=acct.id, service="ec2",
                )
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @ec2_app.command("audit")
        def audit_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """Audit: public instances, wide-open security groups."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import build_stack, emit, get_runtime, regions_for

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                acct = resolver.resolve(account)
                sess = executor.session_for(acct)
                regions = ([region] if region
                           else regions_for(acct, config, sess, store))
                result = executor.execute_across_regions(
                    regions, lambda s, r: plugin.audit(s, r),
                    session=sess, account_id=acct.id, service="ec2",
                )
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        return ec2_app

    # ─── EC2 operations ─────────────────────────────────────────

    def list_instances(self, session: Any, region: Optional[str] = None,
                       state: Optional[str] = None) -> Iterator[dict]:
        """List EC2 instances with pagination and optional state filter."""
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_instances")
        filters = []
        if state:
            filters = [{"Name": "instance-state-name", "Values": [state]}]
        for page in paginator.paginate(Filters=filters):
            for reservation in page.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    yield self._instance_row(inst)

    def list_security_groups(self, session: Any,
                             region: Optional[str] = None) -> Iterator[dict]:
        """List security groups."""
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_security_groups")
        for page in paginator.paginate():
            for sg in page.get("SecurityGroups", []):
                yield {
                    "resource_id": sg["GroupId"],
                    "name": sg.get("GroupName"),
                    "vpc_id": sg.get("VpcId"),
                    "description": sg.get("Description"),
                    "ip_permissions": sg.get("IpPermissions", []),
                    "raw": sg,
                }

    def list_volumes(self, session: Any, region: Optional[str] = None) -> Iterator[dict]:
        """List EBS volumes."""
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_volumes")
        for page in paginator.paginate():
            for vol in page.get("Volumes", []):
                yield {
                    "resource_id": vol["VolumeId"],
                    "state": vol.get("State"),
                    "size_gb": vol.get("Size"),
                    "type": vol.get("VolumeType"),
                    "attached_to": [a.get("InstanceId") for a in vol.get("Attachments", [])],
                    "raw": vol,
                }

    def list_snapshots(self, session: Any, region: Optional[str] = None) -> Iterator[dict]:
        """List own EBS snapshots."""
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_snapshots")
        for page in paginator.paginate(OwnerIds=["self"]):
            for snap in page.get("Snapshots", []):
                yield {
                    "resource_id": snap["SnapshotId"],
                    "state": snap.get("State"),
                    "started": str(snap.get("StartTime", "")),
                    "volume_id": snap.get("VolumeId"),
                    "raw": snap,
                }

    def list_eips(self, session: Any, region: Optional[str] = None) -> Iterator[dict]:
        """List elastic IPs."""
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_addresses")
        for page in paginator.paginate():
            for eip in page.get("Addresses", []):
                yield {
                    "resource_id": eip.get("AllocationId", eip.get("PublicIp", "")),
                    "public_ip": eip.get("PublicIp"),
                    "associated": bool(eip.get("InstanceId") or eip.get("AssociationId")),
                    "raw": eip,
                }

    # ─── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _instance_row(inst: dict) -> dict:
        """Normalize an instance into a resource row."""
        tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
        return {
            "resource_id": inst["InstanceId"],
            "state": inst.get("State", {}).get("Name"),
            "type": inst.get("InstanceType"),
            "public_ip": inst.get("PublicIpAddress"),
            "private_ip": inst.get("PrivateIpAddress"),
            "name": tags.get("Name"),
            "tags": tags,
            "launch_time": str(inst.get("LaunchTime", "")),
            "raw": inst,
        }

    def _transition(self, resp: dict, verb: str) -> dict:
        """Normalize a start/stop response."""
        changes = resp.get("StoppingInstances", resp.get("StartingInstances", []))
        return {
            "status": verb,
            "instances": [
                {"id": c["InstanceId"], "current": c.get("CurrentState", {}).get("Name")}
                for c in changes
            ],
        }

    def _handle_dryrun_or_raise(self, error: Exception, op: str,
                                resource_id: str) -> dict:
        """DryRun successes raise DryRunOperation — that means allowed."""
        code = error.response.get("Error", {}).get("Code", "")
        if code == "DryRunOperation":
            return {
                "status": f"dry-run-ok ({op} permitted)",
                "resource_id": resource_id,
            }
        raise error


def _effective_dry_run(yes: bool, dry_run: bool) -> bool:
    """Safety contract (user-manual §8): safe ops run DRY by default;
    --yes executes for real. The global --dry-run always forces a
    simulation, even combined with --yes — it must never be a
    silent no-op (audit pass 2, #1).
    """
    from harness_cli.main import get_ctx
    return bool(dry_run or get_ctx().get("dry_run") or not yes)


def _locate_instance(sess, acct, config, store, plugin, instance_id) -> "str | None":
    """Find which in-scope region holds the instance (reads only).

    Lets `ec2 start/stop` and `ask` work without --region; refuses
    cleanly when the instance exists nowhere in scope.
    """
    from harness_cli.runtime import regions_for
    for r in regions_for(acct, config, sess, store):
        if plugin.get_resource(sess, instance_id, r) is not None:
            return r
    return None


def _run_safe_op(plugin, operation, instance_id, account, region,
                 yes, dry_run, **params):
    """Shared runner for start/stop commands.

    Dry-run by default; --yes executes for real (and then only on
    accounts without the read_only lock). Records the action in the
    local audit trail and reports failures through PartialResult
    (never a raw traceback).
    """
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
        effective_dry_run = _effective_dry_run(yes, dry_run)
        # The read_only lock blocks REAL executions only — dry-runs
        # are reads by definition (see ensure_mutable's contract).
        if not effective_dry_run:
            ensure_mutable(acct)
        if region is None:
            region = _locate_instance(sess, acct, config, store,
                                     plugin, instance_id)
            if region is None:
                result = PartialResult()
                result.failures.append(FailureMsg(
                    account_id=acct.id, service="ec2",
                    error_code="NotFound",
                    message=f"Instance {instance_id} not found in any "
                            f"in-scope region for account {acct.id} "
                            "(pass --region explicitly to override)",
                ))
                emit(result, get_ctx().get("output", "table"))
                return
        try:
            result_data = plugin.safe_op(
                sess, operation, instance_id,
                region=region, dry_run=effective_dry_run, **params
            )
            record_audit(
                config, action=operation, service="ec2",
                account_id=acct.id, region=region,
                resource_id=instance_id, success=True,
                dry_run=effective_dry_run,
                principal=sess.source_identity,
            )
            emit(PartialResult(success={instance_id: result_data}),
                 get_ctx().get("output", "table"))
        except typer.Exit:
            raise  # emit() success — NOT a failure
        except Exception as e:
            err = getattr(e, "response", {}).get("Error", {})
            record_audit(
                config, action=operation, service="ec2",
                account_id=acct.id, region=region,
                resource_id=instance_id, success=False,
                error_message=str(err.get("Message", e))[:300],
                dry_run=effective_dry_run,
                principal=sess.source_identity,
            )
            result = PartialResult()
            result.failures.append(FailureMsg(
                account_id=acct.id, region=region, service="ec2",
                error_code=err.get("Code", type(e).__name__),
                message=str(err.get("Message", e))[:300],
            ))
            emit(result, get_ctx().get("output", "table"))
    finally:
        executor.shutdown()
