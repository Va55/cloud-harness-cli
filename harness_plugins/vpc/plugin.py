"""
VPC Plugin — networking (real implementation, read-only).

Regional service. Phase 1: read (VPCs, subnets, route tables) —
extended (Phase 22) with topology + visibility: internet gateways,
NAT gateways (cost visibility), network ACLs, VPC endpoints, flow
logs, and an audit (VPCs without flow logs, public subnets).
The EC2 plugin already covers security groups; this covers topology.
"""

from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities

VPC_CAPABILITIES = PluginCapabilities(
    name="vpc",
    display_name="VPC",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=False,
    is_global_service=False,
    max_rps=(("ec2", 5.0),),  # VPC calls are EC2 API
    rate_limit_strict=False,
)


class VPCPlugin(BasePlugin):
    """VPC service plugin."""

    CAPABILITIES = VPC_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        resource_type = filters.pop("type", "vpcs")
        if resource_type == "subnets":
            yield from self.list_subnets(session, region)
        else:
            yield from self.list_vpcs(session, region)

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        client = session.get_client("ec2", region)
        resp = client.describe_vpcs(VpcIds=[resource_id])
        vpcs = resp.get("Vpcs", [])
        return self._vpc_row(vpcs[0]) if vpcs else None

    def safe_op(self, session: Any, operation: str, resource_id: str, **params) -> dict:
        raise NotImplementedError("VPC Phase 1 is read-only")

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        return {"service": "vpc", "operation": operation,
                "params": params, "status": "would_execute"}

    # ─── Operations ────────────────────────────────────────────

    def list_vpcs(self, session: Any, region: Optional[str] = None) -> Iterator[dict]:
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_vpcs")
        for page in paginator.paginate():
            for vpc in page.get("Vpcs", []):
                yield self._vpc_row(vpc)

    def list_subnets(self, session: Any, region: Optional[str] = None,
                     vpc_id: Optional[str] = None) -> Iterator[dict]:
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_subnets")
        filters = [{"Name": "vpc-id", "Values": [vpc_id]}] if vpc_id else []
        for page in paginator.paginate(Filters=filters):
            for sn in page.get("Subnets", []):
                tags = {t["Key"]: t["Value"] for t in sn.get("Tags", [])}
                yield {
                    "resource_id": sn["SubnetId"],
                    "vpc_id": sn.get("VpcId"),
                    "cidr": sn.get("CidrBlock"),
                    "az": sn.get("AvailabilityZone"),
                    "state": sn.get("State"),
                    "public": sn.get("MapPublicIpOnLaunch", False),
                    "name": tags.get("Name"),
                    "raw": sn,
                }

    def list_route_tables(self, session: Any, region: Optional[str] = None,
                          vpc_id: Optional[str] = None) -> Iterator[dict]:
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_route_tables")
        filters = [{"Name": "vpc-id", "Values": [vpc_id]}] if vpc_id else []
        for page in paginator.paginate(Filters=filters):
            for rt in page.get("RouteTables", []):
                yield {
                    "resource_id": rt["RouteTableId"],
                    "vpc_id": rt.get("VpcId"),
                    "routes": [
                        {"dest": r.get("DestinationCidrBlock"),
                         "target": (r.get("GatewayId") or r.get("NatGatewayId")
                                    or r.get("TransitGatewayId") or r.get("NetworkInterfaceId")
                                    or r.get("InstanceId") or "local")}
                        for r in rt.get("Routes", [])
                    ],
                    "associations": [a.get("SubnetId") or "main"
                                     for a in rt.get("Associations", [])],
                    "raw": rt,
                }

    @staticmethod
    def _vpc_row(vpc: dict) -> dict:
        tags = {t["Key"]: t["Value"] for t in vpc.get("Tags", [])}
        return {
            "resource_id": vpc["VpcId"],
            "cidr": vpc.get("CidrBlock"),
            "state": vpc.get("State"),
            "default": vpc.get("IsDefault", False),
            "name": tags.get("Name"),
            "tags": tags,
            "raw": vpc,
        }

    def list_internet_gateways(self, session: Any,
                               region: Optional[str] = None) -> Iterator[dict]:
        """List internet gateways with their VPC attachments."""
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_internet_gateways")
        for page in paginator.paginate():
            for igw in page.get("InternetGateways", []):
                tags = {t["Key"]: t["Value"] for t in igw.get("Tags", [])}
                yield {
                    "resource_id": igw["InternetGatewayId"],
                    "attached_vpcs": [a.get("VpcId")
                                      for a in igw.get("Attachments", [])],
                    "name": tags.get("Name"),
                    "raw": igw,
                }

    def list_nat_gateways(self, session: Any,
                          region: Optional[str] = None) -> Iterator[dict]:
        """List NAT gateways — the classic silent cost driver."""
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_nat_gateways")
        for page in paginator.paginate():
            for nat in page.get("NatGateways", []):
                tags = {t["Key"]: t["Value"] for t in nat.get("Tags", [])}
                yield {
                    "resource_id": nat["NatGatewayId"],
                    "vpc_id": nat.get("VpcId"),
                    "subnet_id": nat.get("SubnetId"),
                    "state": nat.get("State"),
                    "type": nat.get("NatType") or "nat" ,
                    "created": str(nat.get("CreateTime", "")),
                    "name": tags.get("Name"),
                    "raw": nat,
                }

    def list_nacls(self, session: Any, region: Optional[str] = None,
                   vpc_id: Optional[str] = None) -> Iterator[dict]:
        """List network ACLs with a rule summary (count in/out)."""
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_network_acls")
        filters = [{"Name": "vpc-id", "Values": [vpc_id]}] if vpc_id else []
        for page in paginator.paginate(Filters=filters):
            for nacl in page.get("NetworkAcls", []):
                entries = nacl.get("Entries", [])
                yield {
                    "resource_id": nacl["NetworkAclId"],
                    "vpc_id": nacl.get("VpcId"),
                    "default": nacl.get("IsDefault", False),
                    "rules_in": sum(1 for e in entries
                                    if e.get("Egress") is False),
                    "rules_out": sum(1 for e in entries
                                     if e.get("Egress") is True),
                    "raw": nacl,
                }

    def list_endpoints(self, session: Any, region: Optional[str] = None,
                       vpc_id: Optional[str] = None) -> Iterator[dict]:
        """List VPC endpoints (Interface/Gateway) — cost + exfiltration view."""
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_vpc_endpoints")
        filters = [{"Name": "vpc-id", "Values": [vpc_id]}] if vpc_id else []
        for page in paginator.paginate(Filters=filters):
            for ep in page.get("VpcEndpoints", []):
                yield {
                    "resource_id": ep["VpcEndpointId"],
                    "vpc_id": ep.get("VpcId"),
                    "service": ep.get("ServiceName", "").split(".")[-1]
                    if ep.get("ServiceName") else None,
                    "type": ep.get("VpcEndpointType"),
                    "state": ep.get("State"),
                    "private_dns": ep.get("PrivateDnsEnabled"),
                    "raw": ep,
                }

    def list_flow_logs(self, session: Any,
                       region: Optional[str] = None) -> Iterator[dict]:
        """List flow logs (VPC network visibility)."""
        client = session.get_client("ec2", region)
        paginator = client.get_paginator("describe_flow_logs")
        for page in paginator.paginate():
            for fl in page.get("FlowLogs", []):
                yield {
                    "resource_id": fl["FlowLogId"],
                    "resource": fl.get("ResourceId"),
                    "traffic_type": fl.get("TrafficType"),
                    "destination": (fl.get("LogDestination")
                                    or fl.get("LogGroupName")),
                    "status": fl.get("FlowLogStatus"),
                    "raw": fl,
                }

    def describe_vpc(self, session: Any, vpc_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        """Deep view of one VPC: subnets, IGW attachment, flow logs."""
        client = session.get_client("ec2", region)
        try:
            vpc = client.describe_vpcs(VpcIds=[vpc_id])["Vpcs"][0]
        except client.exceptions.ClientError:
            return None
        subnets = client.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["Subnets"]
        igws = client.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )["InternetGateways"]
        # DescribeFlowLogs has no 'vpc-id' filter — the resource-id
        # filter matches the VPC (a flow log's attached resource).
        # (Found live: real AWS rejects 'vpc-id' with
        # InvalidParameterValue; moto is lenient — pass-4 fix)
        flow_logs = client.describe_flow_logs(
            Filters=[{"Name": "resource-id", "Values": [vpc_id]}])["FlowLogs"]
        row = self._vpc_row(vpc)
        row.update({
            "subnet_count": len(subnets),
            "public_subnets": sum(
                1 for s in subnets if s.get("MapPublicIpOnLaunch")),
            "internet_gateways": [i["InternetGatewayId"] for i in igws],
            "flow_logs": len(flow_logs),
        })
        return row

    def audit(self, session: Any, region: Optional[str] = None) -> dict:
        """Network audit: VPCs without flow logs, public subnets,
        NAT gateways in non-available states."""
        findings = []
        client = session.get_client("ec2", region)

        vpcs = {v["VpcId"]: v for page in
                client.get_paginator("describe_vpcs").paginate()
                for v in page.get("Vpcs", [])}
        flow_vpcs = set()
        for page in client.get_paginator("describe_flow_logs").paginate():
            for fl in page.get("FlowLogs", []):
                flow_vpcs.add(fl.get("ResourceId"))
        for vpc_id in vpcs:
            if vpc_id not in flow_vpcs:
                findings.append({
                    "type": "vpc_without_flow_logs",
                    "resource_id": vpc_id,
                    "message": f"VPC {vpc_id} has no flow logs — "
                               "network traffic is invisible",
                })

        for subnet in client.get_paginator("describe_subnets").paginate():
            for sn in subnet.get("Subnets", []):
                if sn.get("MapPublicIpOnLaunch"):
                    findings.append({
                        "type": "public_subnet",
                        "resource_id": sn["SubnetId"],
                        "message": f"Subnet {sn['SubnetId']} auto-assigns "
                                   "public IPs",
                    })

        for page in client.get_paginator("describe_nat_gateways").paginate():
            for nat in page.get("NatGateways", []):
                if nat.get("State") not in ("available",):
                    findings.append({
                        "type": "nat_gateway_state",
                        "resource_id": nat["NatGatewayId"],
                        "message": f"NAT gateway {nat['NatGatewayId']} "
                                   f"in state '{nat.get('State')}'",
                    })

        return {"service": "vpc", "compliant": not findings,
                "findings": findings}

    # ─── CLI ────────────────────────────────────────────────────

    def create_app(self) -> typer.Typer:
        vpc_app = typer.Typer(name="vpc", help="VPC management (read-only)")
        plugin = VPCPlugin()

        def _run_multi_region(collect_fn, account, region, all_accounts, config_key):
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
                        session=sess, account_id=acct.id, service="ec2",
                    )

                result = executor.execute_across_accounts(accounts, per_account)
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @vpc_app.command("list")
        def list_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List VPCs."""
            _run_multi_region(
                lambda s, r: list(plugin.list_vpcs(s, r)),
                account, region, all_accounts, None,
            )

        @vpc_app.command("subnets")
        def subnets_cmd(
            vpc_id: Optional[str] = typer.Option(None, "--vpc", help="Filter by VPC ID"),
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """List subnets."""
            _run_multi_region(
                lambda s, r: list(plugin.list_subnets(s, r, vpc_id=vpc_id)),
                account, region, False, None,
            )

        @vpc_app.command("route-tables")
        def route_tables_cmd(
            vpc_id: Optional[str] = typer.Option(None, "--vpc", help="Filter by VPC ID"),
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """List route tables."""
            _run_multi_region(
                lambda s, r: list(plugin.list_route_tables(s, r, vpc_id=vpc_id)),
                account, region, False, None,
            )

        @vpc_app.command("describe")
        def describe_cmd(
            vpc_id: str = typer.Argument(..., help="VPC ID (vpc-...)"),
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """Deep view of one VPC: subnets, IGW, flow logs."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import (
                build_stack,
                emit,
                get_runtime,
                regions_for,
                resolve_accounts,
            )
            from harness_primitives.output import FailureMsg, PartialResult

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                accounts = resolve_accounts(resolver, account, False)
                result = PartialResult()
                for acct in accounts:
                    sess = executor.session_for(acct)
                    regions = ([region] if region
                               else regions_for(acct, config, sess, store))
                    for r in regions:
                        try:
                            row = plugin.describe_vpc(sess, vpc_id, r)
                        except Exception as e:
                            err = getattr(e, "response", {}).get("Error", {})
                            result.failures.append(FailureMsg(
                                account_id=acct.id, region=r, service="ec2",
                                error_code=err.get("Code", type(e).__name__),
                                message=str(err.get("Message", e))[:300],
                            ))
                            continue
                        if row:
                            result.success[f"{acct.id}:{r}"] = row
                if not result.success and not result.failures:
                    typer.echo(f"VPC {vpc_id} not found in scope.",
                               err=True)
                    raise typer.Exit(2)
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @vpc_app.command("internet-gateways")
        def igw_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List internet gateways and their VPC attachments."""
            _run_multi_region(
                lambda s, r: list(plugin.list_internet_gateways(s, r)),
                account, region, all_accounts, None,
            )

        @vpc_app.command("nat-gateways")
        def nat_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List NAT gateways (state + placement — the silent cost driver)."""
            _run_multi_region(
                lambda s, r: list(plugin.list_nat_gateways(s, r)),
                account, region, all_accounts, None,
            )

        @vpc_app.command("nacls")
        def nacl_cmd(
            vpc_id: Optional[str] = typer.Option(None, "--vpc", help="Filter by VPC ID"),
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """List network ACLs with rule counts."""
            _run_multi_region(
                lambda s, r: list(plugin.list_nacls(s, r, vpc_id=vpc_id)),
                account, region, False, None,
            )

        @vpc_app.command("endpoints")
        def endpoints_cmd(
            vpc_id: Optional[str] = typer.Option(None, "--vpc", help="Filter by VPC ID"),
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """List VPC endpoints (cost + data-exfiltration visibility)."""
            _run_multi_region(
                lambda s, r: list(plugin.list_endpoints(s, r, vpc_id=vpc_id)),
                account, region, False, None,
            )

        @vpc_app.command("flow-logs")
        def flow_logs_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List flow logs (network traffic visibility)."""
            _run_multi_region(
                lambda s, r: list(plugin.list_flow_logs(s, r)),
                account, region, all_accounts, None,
            )

        @vpc_app.command("audit")
        def audit_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """Audit: VPCs without flow logs, public subnets, odd NAT states."""
            _run_multi_region(
                lambda s, r: plugin.audit(s, r),
                account, region, all_accounts, None,
            )

        return vpc_app
