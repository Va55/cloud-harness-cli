"""
Plugin discovery via Python entry points.

Discovers plugins registered in pyproject.toml under [project.entry-points."cloud_harness.plugins"].
Validates capabilities and command name uniqueness at startup.
"""

import importlib.metadata
from typing import Any


class PluginRegistry:
    """Discover and validate plugins via entry points."""

    GROUP = "cloud_harness.plugins"

    def __init__(self):
        self._plugins: dict[str, Any] = {}
        self._warnings: list[str] = []
        self._loaded = False

    def load(self):
        """Load all registered plugins. Missing modules are recorded as warnings."""
        if self._loaded:
            return
        self._warnings = []
        eps = importlib.metadata.entry_points(group=self.GROUP)
        for ep in eps:
            try:
                plugin = ep.load()
                if hasattr(plugin, "CAPABILITIES"):
                    name = plugin.CAPABILITIES.name
                    if name in self._plugins:
                        self._warnings.append(f"Duplicate plugin name: {name}")
                    self._plugins[name] = plugin
                else:
                    self._warnings.append(
                        f"Plugin {ep.name} has no CAPABILITIES — not a valid harness plugin"
                    )
            except Exception as e:
                self._warnings.append(f"Could not load plugin {ep.name}: {e}")
        self._loaded = True

    def get_plugin(self, name: str) -> Any:
        """Get a plugin by name."""
        if not self._loaded:
            self.load()
        if name not in self._plugins:
            raise ValueError(
                f"Plugin '{name}' not found. Available: {list(self._plugins.keys())}"
            )
        return self._plugins[name]

    def list_plugins(self) -> list[dict]:
        """List all loaded plugins with capabilities."""
        if not self._loaded:
            self.load()
        result = []
        for plugin_cls in self._plugins.values():
            caps = plugin_cls.CAPABILITIES
            result.append({
                "name": caps.name,
                "display_name": caps.display_name,
                "version": caps.version,
                "supports_read": caps.supports_read,
                "supports_create": caps.supports_create,
                "supports_delete": caps.supports_delete,
                "supports_safe_ops": caps.supports_safe_ops,
                "is_global_service": caps.is_global_service,
            })
        return result

    def validate(self) -> list[str]:
        """Validate plugins: duplicate names AND duplicate command names across sub-apps."""
        if not self._loaded:
            self.load()
        warnings = list(self._warnings)
        # Duplicate plugin names
        names = [p.CAPABILITIES.name for p in self._plugins.values()]
        if len(names) != len(set(names)):
            warnings.append("Duplicate plugin names detected!")

        # Duplicate CLI command names *within the same namespace level*.
        # Plugin sub-apps are namespaced (harness <plugin> <cmd>), so a
        # 'list' in ec2 and a 'list' in s3 is fine — they only collide
        # if the SAME plugin defines the same command twice (Typer
        # itself won't allow that) or top-level names collide.
        for plugin_cls in self._plugins.values():
            try:
                plugin = plugin_cls()
            except TypeError:
                continue
            try:
                sub_app = plugin.create_app()
            except NotImplementedError:
                continue
            except Exception:
                continue
            if sub_app is None:
                continue
            # Check for duplicate command names within one plugin's app
            plugin_cmds = []
            for item in sub_app.registered_commands:
                cmd_name = item.name or item.callback.__name__.replace("_", "-")
                if cmd_name in plugin_cmds:
                    warnings.append(
                        f"Plugin '{plugin.CAPABILITIES.name}' defines command "
                        f"'{cmd_name}' more than once"
                    )
                plugin_cmds.append(cmd_name)
        return warnings

    @property
    def available_plugins(self) -> list[str]:
        """Get list of available plugin names."""
        if not self._loaded:
            self.load()
        return list(self._plugins.keys())

    @property
    def load_warnings(self) -> list[str]:
        """Get warnings from the last load()."""
        if not self._loaded:
            self.load()
        return list(self._warnings)
