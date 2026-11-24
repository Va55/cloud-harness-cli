"""Tests for plugin contract and registry.

Verifies:
- All registered plugins implement the BasePlugin interface
- Capabilities are valid
- No duplicate plugin names
- Duplicate command detection within a plugin
"""

import pytest

from harness_plugins.base import BasePlugin, PluginCapabilities
from harness_plugins.registry import PluginRegistry


@pytest.fixture
def registry():
    reg = PluginRegistry()
    reg.load()
    return reg


class TestRegistryDiscovery:
    def test_all_plugins_load(self, registry):
        expected = {
            "iam", "ec2", "s3", "cloudfront", "lambda",
            "org", "vpc", "cost", "security", "inventory", "backup",
            "route53",
        }
        assert set(registry.available_plugins) == expected

    def test_no_load_warnings(self, registry):
        assert registry.load_warnings == [], \
            f"Plugin load warnings: {registry.load_warnings}"

    def test_validate_no_warnings(self, registry):
        assert registry.validate() == []

    def test_get_plugin_unknown_raises(self, registry):
        with pytest.raises(ValueError, match="not found"):
            registry.get_plugin("nonexistent")


class TestPluginContract:
    """Contract test: every plugin must satisfy the interface."""

    @pytest.mark.parametrize("name", [
        "iam", "ec2", "s3", "cloudfront", "lambda",
        "org", "vpc", "cost", "security", "inventory",
    ])
    def test_plugin_implements_interface(self, registry, name):
        plugin_cls = registry.get_plugin(name)
        # Must have CAPABILITIES
        assert hasattr(plugin_cls, "CAPABILITIES")
        caps = plugin_cls.CAPABILITIES
        assert isinstance(caps, PluginCapabilities)
        assert caps.name == name
        assert caps.display_name
        assert caps.version

    @pytest.mark.parametrize("name", [
        "iam", "ec2", "s3", "cloudfront", "lambda",
        "org", "vpc", "cost", "security", "inventory",
    ])
    def test_plugin_instantiable_with_app(self, registry, name):
        """Each plugin must be instantiable and return a Typer app (or raise NotImplementedError)."""
        plugin_cls = registry.get_plugin(name)
        plugin = plugin_cls()
        assert isinstance(plugin, BasePlugin)
        try:
            app = plugin.create_app()
            assert app is not None
        except NotImplementedError:
            pytest.fail(f"Plugin {name} must provide create_app()")

    def test_capabilities_hashable(self, registry):
        """Frozen dataclass must be hashable (audit found dict field broke this)."""
        plugin_cls = registry.get_plugin("iam")
        caps = plugin_cls.CAPABILITIES
        hash(caps)  # Must not raise


class TestIAMPluginInterface:
    """IAM was the audit's contract-violation case — verify it's fixed."""

    def test_iam_implements_list_resources(self, registry):
        from harness_plugins.iam.plugin import IAMPlugin
        # Must not be the base's NotImplementedError version
        assert IAMPlugin.list_resources is not BasePlugin.list_resources

    def test_iam_implements_get_resource(self, registry):
        from harness_plugins.iam.plugin import IAMPlugin
        assert IAMPlugin.get_resource is not BasePlugin.get_resource

    def test_iam_safe_op_routing(self, registry):
        from harness_plugins.iam.plugin import IAMPlugin
        p = IAMPlugin()
        # rotate-keys must route (will fail on session use, but routing exists)
        with pytest.raises(NotImplementedError, match="does not support"):
            p.safe_op(None, "bogus-op", "x")
