"""
Cloud Harness CLI — primitives layer

Shared building blocks: session management, credentials, pagination,
region detection, output formatting, failure handling, rate limiting.
"""

from harness_primitives.credentials import CredentialCache
from harness_primitives.failure import FailureCategory, HarnessError
from harness_primitives.output import FailureMsg, PartialResult, WarningMsg, format_output
from harness_primitives.rate_limiter import RateLimiter, TokenBucket
from harness_primitives.regions import get_enabled_regions
from harness_primitives.session import HarnessSession, create_botocore_client

__all__ = [
    "HarnessSession",
    "create_botocore_client",
    "CredentialCache",
    "RateLimiter",
    "TokenBucket",
    "get_enabled_regions",
    "format_output",
    "PartialResult",
    "FailureMsg",
    "WarningMsg",
    "HarnessError",
    "FailureCategory",
]
