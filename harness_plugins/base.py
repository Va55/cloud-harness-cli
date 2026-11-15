"""
Plugin base class and capability declaration.

Each service plugin must:
1. Inherit from BasePlugin
2. Define CAPABILITIES (PluginCapabilities dataclass)
3. Implement create_app() → Typer sub-app
4. Implement list_resources(), get_resource()
5. Optionally implement: describe(), safe_op(), audit(), cost_info(), dry_run_simulate()
"""

from dataclasses import dataclass
from typing import Any, Iterator, Optional

from typer import Typer


@dataclass(frozen=True)
class PluginCapabilities:
    """What this plugin CAN do.

    Note: max_rps uses a tuple of (api_name, tps) pairs so the dataclass
    stays frozen/hashable.
    """
    name: str                              # e.g. "iam", "ec2"
    display_name: str                      # e.g. "IAM", "EC2"
    version: str = "1.0.0"
    supports_read: bool = True
    supports_create: bool = False
    supports_update: bool = False
    supports_delete: bool = False
    supports_safe_ops: bool = False
    is_global_service: bool = False        # breaks region fan-out

    # Rate limits: tuple of (api_name, tps) pairs — hashable for frozen dataclass
    max_rps: tuple = ()
    rate_limit_strict: bool = False

    # Thread safety
    requires_separate_client_per_thread: bool = True

    def get_api_rps(self) -> dict:
        """Return max_rps as a dict for convenient lookup."""
        return dict(self.max_rps)


class BasePlugin:
    """All service plugins must implement this interface."""

    CAPABILITIES: PluginCapabilities

    def get_capabilities(self) -> PluginCapabilities:
        return self.CAPABILITIES

    def create_app(self) -> Typer:
        """Return Typer sub-app for CLI commands."""
        raise NotImplementedError

    def list_resources(self, session: Any, region: Optional[str] = None, **filters) -> Iterator[Any]:
        """List all resources of this service."""
        raise NotImplementedError

    def get_resource(self, session: Any, resource_id: str, region: Optional[str] = None) -> Optional[Any]:
        """Get a single resource by ID. Return None if not found."""
        raise NotImplementedError

    def describe(self, session: Any, **filters) -> dict:
        """Describe with filtering. Default: call list + filter in Python."""
        return {"resources": list(self.list_resources(session, **filters))}

    def safe_op(self, session: Any, operation: str, resource_id: str, **params) -> dict:
        """Safe operations: stop/start, rotate, invalidate, etc."""
        raise NotImplementedError(
            f"Service {self.CAPABILITIES.name} does not support {operation}"
        )

    def audit(self, session: Any, region: Optional[str] = None) -> dict:
        """Security/compliance audit. Default: empty."""
        return {
            "service": self.CAPABILITIES.name,
            "compliant": True,
            "findings": []
        }

    def cost_info(self, session: Any, region: Optional[str] = None) -> dict:
        """Cost information. Default: null."""
        return {
            "service": self.CAPABILITIES.name,
            "total_cost": 0.0
        }

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        """Simulate an operation without executing. Per-plugin implementation."""
        raise NotImplementedError(
            f"Service {self.CAPABILITIES.name} does not support dry-run"
        )

    def is_global(self) -> bool:
        return self.CAPABILITIES.is_global_service
