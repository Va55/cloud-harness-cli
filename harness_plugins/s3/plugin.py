"""
S3 Plugin — object storage (real implementation).

Phase 1: read (buckets, bucket-info, public-check) — no mutating ops.
ListBuckets is a global call; bucket operations are regional (bucket's
own region). This plugin handles the region pinning per bucket.
"""

from typing import Any, Iterator, Optional

import typer
from botocore.exceptions import ClientError

from harness_plugins.base import BasePlugin, PluginCapabilities

S3_CAPABILITIES = PluginCapabilities(
    name="s3",
    display_name="S3",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=False,
    is_global_service=False,  # list_buckets is global but bucket ops are regional
    max_rps=(("s3", 5.0),),
    rate_limit_strict=False,
)

CONSOLE_URL = "https://s3.console.aws.amazon.com/s3/buckets/{id}"


class S3Plugin(BasePlugin):
    """S3 service plugin."""

    CAPABILITIES = S3_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        """List buckets (single global call — no region fan-out needed)."""
        yield from self.list_buckets(session, **filters)

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        """Get bucket info: location, encryption, versioning, public-block."""
        try:
            return self.bucket_info(session, resource_id)
        except Exception:
            return None

    def safe_op(self, session: Any, operation: str, resource_id: str, **params) -> dict:
        raise NotImplementedError("S3 Phase 1 is read-only")

    def audit(self, session: Any, region: Optional[str] = None) -> dict:
        """Audit: buckets that are publicly accessible."""
        findings = []
        for bucket in self.list_buckets(session):
            check = self.public_check(session, bucket["resource_id"])
            if check["is_public"]:
                findings.append({
                    "type": "public_bucket",
                    "resource_id": bucket["resource_id"],
                    "message": f"Bucket is public: {check['reasons']}",
                })
        return {"service": "s3", "compliant": not findings, "findings": findings}

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        return {"service": "s3", "operation": operation, "params": params,
                "status": "would_execute"}

    def create_app(self) -> typer.Typer:
        """Typer sub-app for S3 commands."""
        s3_app = typer.Typer(name="s3", help="S3 management")
        plugin = S3Plugin()

        @s3_app.command("list-buckets")
        def list_buckets_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List S3 buckets."""
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

                def per_account(sess, acct):
                    return list(plugin.list_buckets(sess))

                result = executor.execute_across_accounts(
                    accounts, per_account, service="s3"
                )
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @s3_app.command("bucket-info")
        def bucket_info_cmd(
            bucket: str = typer.Argument(..., help="Bucket name"),
            account: Optional[str] = typer.Option(None, "--account"),
        ):
            """Bucket details: location, encryption, versioning, public-block."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import build_stack, emit, get_runtime

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                acct = resolver.resolve(account)
                sess = executor.session_for(acct)
                info = plugin.bucket_info(sess, bucket)
                from harness_primitives.output import PartialResult
                emit(PartialResult(success={bucket: info}),
                     get_ctx().get("output", "table"))
            except typer.Exit:
                raise  # emit() success — NOT a failure
            except Exception as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(2) from e
            finally:
                executor.shutdown()

        @s3_app.command("public-check")
        def public_check_cmd(
            bucket: str = typer.Argument(..., help="Bucket name"),
            account: Optional[str] = typer.Option(None, "--account"),
        ):
            """Check if a bucket is publicly accessible."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import build_stack, emit, get_runtime

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                acct = resolver.resolve(account)
                sess = executor.session_for(acct)
                check = plugin.public_check(sess, bucket)
                from harness_primitives.output import PartialResult
                emit(PartialResult(success={bucket: check}),
                     get_ctx().get("output", "table"))
            except typer.Exit:
                raise  # emit() success — NOT a failure
            except Exception as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(2) from e
            finally:
                executor.shutdown()

        @s3_app.command("audit")
        def audit_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """Audit all buckets for public exposure."""
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

                def per_account(sess, acct):
                    return plugin.audit(sess)

                result = executor.execute_across_accounts(
                    accounts, per_account, service="s3"
                )
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        return s3_app

    # ─── S3 operations ──────────────────────────────────────────

    def list_buckets(self, session: Any, **filters) -> Iterator[dict]:
        """List buckets (global call — one call, not per region)."""
        client = session.get_client("s3")
        resp = client.list_buckets()
        for bucket in resp.get("Buckets", []):
            name = bucket["Name"]
            yield {
                "resource_id": name,
                "name": name,
                "created": str(bucket.get("CreationDate", "")),
            }

    def bucket_info(self, session: Any, bucket: str) -> dict:
        """Full bucket details. The client is pinned to the bucket's region.

        A bucket that does not exist is an ERROR, not a row of
        'unknown' fields — fabricating success here would make the
        public-exposure story a false negative (silent wrong data is
        worse than a clean failure).
        """
        # 1. Get bucket region (must use us-east-1 or the session region first)
        probe = session.get_client("s3", "us-east-1")
        try:
            loc = probe.get_bucket_location(Bucket=bucket).get("LocationConstraint") or "us-east-1"
        except probe.exceptions.NoSuchBucket:
            raise  # let the command report the bucket as not found
        except Exception:
            # Permission issues on GetBucketLocation degrade to the
            # session default; the per-bucket reads below surface the
            # real denial if there is one.
            loc = "us-east-1"
        client = session.get_client("s3", loc)

        info = {
            "resource_id": bucket,
            "name": bucket,
            "region": loc,
        }

        # 2. Encryption
        try:
            enc = client.get_bucket_encryption(Bucket=bucket)
            info["encryption"] = enc.get("ServerSideEncryptionConfiguration", {}) \
                .get("Rules", [{}])[0].get("ApplyServerSideEncryptionByDefault", {}) \
                .get("SSEAlgorithm", "unknown")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ServerSideEncryptionConfigurationNotFoundError":
                info["encryption"] = "NONE (unencrypted at rest by default policy)"
            else:
                info["encryption"] = "unknown"
        except Exception:
            info["encryption"] = "unknown"

        # 3. Versioning
        try:
            ver = client.get_bucket_versioning(Bucket=bucket)
            info["versioning"] = ver.get("Status", "Disabled")
        except Exception:
            info["versioning"] = "unknown"

        # 4. Public access block
        try:
            pab = client.get_public_access_block(Bucket=bucket)
            config = pab.get("PublicAccessBlockConfiguration", {})
            info["public_access_block"] = {
                "block_public_acls": config.get("BlockPublicAcls", False),
                "block_public_policy": config.get("BlockPublicPolicy", False),
                "ignore_public_acls": config.get("IgnorePublicAcls", False),
                "restrict_public_buckets": config.get("RestrictPublicBuckets", False),
            }
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchPublicAccessBlockConfiguration":
                info["public_access_block"] = "NOT CONFIGURED"
            else:
                info["public_access_block"] = "unknown"
        except Exception:
            info["public_access_block"] = "unknown"

        return info

    def public_check(self, session: Any, bucket: str) -> dict:
        """Determine if a bucket is publicly accessible.

        Checks in order:
        1. Public Access Block — if all four settings on, definitively private
        2. Bucket ACL grants to AllUsers or AuthenticatedUsers
        3. Bucket policy with Principal:* (non-Conditional)
        """
        probe = session.get_client("s3", "us-east-1")
        try:
            loc = probe.get_bucket_location(Bucket=bucket).get("LocationConstraint") or "us-east-1"
        except probe.exceptions.NoSuchBucket:
            raise  # nonexistent bucket is an error, never "is_public: False"
        except Exception:
            loc = "us-east-1"
        client = session.get_client("s3", loc)

        reasons: list[str] = []

        # 1. Public Access Block
        pab_all_on = False
        try:
            pab = client.get_public_access_block(Bucket=bucket).get(
                "PublicAccessBlockConfiguration", {}
            )
            pab_all_on = all(
                pab.get(k, False) for k in (
                    "BlockPublicAcls", "BlockPublicPolicy",
                    "IgnorePublicAcls", "RestrictPublicBuckets",
                )
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchPublicAccessBlockConfiguration":
                reasons.append("no public access block configured")
        except Exception:
            pass

        if pab_all_on:
            return {"bucket": bucket, "is_public": False,
                    "reasons": ["all public access block settings enabled"]}

        # 2. ACL grants
        try:
            acl = client.get_bucket_acl(Bucket=bucket)
            for grant in acl.get("Grants", []):
                grantee = grant.get("Grantee", {})
                uri = grantee.get("URI", "")
                if "AllUsers" in uri or "AuthenticatedUsers" in uri:
                    reasons.append(f"ACL grants {uri.rsplit('/', 1)[-1]} "
                                   f"permission {grant.get('Permission')}")
        except Exception:
            pass

        # 3. Bucket policy Principal:*
        try:
            import json
            policy = client.get_bucket_policy(Bucket=bucket).get("Policy")
            if policy:
                stmts = json.loads(policy).get("Statement", [])
                if not isinstance(stmts, list):
                    stmts = [stmts]
                for stmt in stmts:
                    if stmt.get("Effect") != "Allow":
                        continue
                    principal = stmt.get("Principal", "")
                    principals = ([principal] if isinstance(principal, str)
                                  else principal.get("*", []) if isinstance(principal, dict)
                                  else [principal])
                    if "*" in principals or principal == "*":
                        if not stmt.get("Condition"):
                            reasons.append(
                                f"policy allows {stmt.get('Action')} to Principal:*"
                            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchBucketPolicy":
                pass  # No policy = fine
        except Exception:
            pass

        return {"bucket": bucket, "is_public": bool(reasons), "reasons": reasons}
