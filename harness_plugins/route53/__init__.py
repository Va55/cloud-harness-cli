"""Route 53 plugin (DNS, read-only)."""

from harness_plugins.route53.plugin import ROUTE53_CAPABILITIES, Route53Plugin

__all__ = ["Route53Plugin", "ROUTE53_CAPABILITIES"]
