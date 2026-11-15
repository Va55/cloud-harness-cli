"""
Region enablement detection via EC2 DescribeRegions.

Detects which regions are enabled for an account.
Not every account has all configured regions enabled.

Detection: ec2.describe_regions(AllRegions=True), parsing OptInStatus:
- opt-in-not-required → enabled by default
- opted-in             → enabled
- not-opted-in         → disabled

The detection call itself is always made against us-east-1, which every
AWS account has enabled.
"""

from typing import Any

from botocore.exceptions import (
    ClientError,
    ReadTimeoutError,
)
from botocore.exceptions import (
    ConnectionError as BotocoreConnectionError,
)

from harness_primitives.failure import (
    FailureCategory,
    HarnessError,
)

DETECTION_REGION = "us-east-1"  # always enabled; used to probe


def get_enabled_regions(session: Any, account_id: str) -> list[str]:
    """Detect which regions are enabled for this account.

    Raises HarnessError on permission/network failure — never silently
    returns a hardcoded list (that hides SCP denials and outages).
    Callers who want a fallback must catch and choose explicitly.
    """
    try:
        ec2 = session.get_client("ec2", DETECTION_REGION)
        resp = ec2.describe_regions(AllRegions=True)
        return [
            r["RegionName"]
            for r in resp["Regions"]
            if r.get("OptInStatus") in ("opted-in", "opt-in-not-required")
        ]
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("UnauthorizedOperation", "AccessDenied",
                    "AccessDeniedException", "OptInRequired"):
            raise HarnessError(
                f"Not authorized to call ec2:DescribeRegions "
                f"({code}) — check IAM permissions",
                FailureCategory.PERMISSION,
                account_id,
            ) from e
        if code in ("ThrottlingException", "RequestLimitExceeded"):
            raise HarnessError(
                f"Throttled detecting regions: {code}",
                FailureCategory.THROTTLED,
                account_id,
            ) from e
        raise HarnessError(
            f"Region detection failed for {account_id}: {code}",
            FailureCategory.FATAL,
            account_id,
        ) from e
    except (BotocoreConnectionError, ReadTimeoutError) as e:
        raise HarnessError(
            f"Timed out/connection failed detecting regions: {e}",
            FailureCategory.TIMEOUT,
            account_id,
        ) from e
    # Unexpected errors propagate so the partial-failure layer classifies them.
