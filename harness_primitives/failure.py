"""
Edge case handling for AWS API failures.

Common failure modes:
- Expired credentials during long operation
- SCP denials (AccessDenied) — do NOT retry
- Throttling (ThrottlingException) — botocore retry handles
- Account deactivated/suspended
- Region not enabled
- Timeout errors
- Empty responses (zero items = success, not error)
"""

from enum import Enum
from typing import Optional


class FailureCategory(Enum):
    PERMISSION = "permission"        # SCP denied, AccessDenied
    THROTTLED = "throttled"         # Rate limited, botocore retry exhausted
    CREDENTIAL_EXPIRED = "credential_expired"
    REGION_DISABLED = "region_disabled"
    ACCOUNT_SUSPENDED = "account_suspended"
    TIMEOUT = "timeout"
    PARTIAL = "partial"
    FATAL = "fatal"


class HarnessError(Exception):
    """Base exception for harness errors."""

    def __init__(self, message: str, category: FailureCategory,
                 account_id: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.category = category
        self.account_id = account_id
