"""
OpenPOS Addon Subsystem & Plugin Architecture
"""

from core.addons.loader import (
    addon_manager,
    AddonManager,
    AddonRecord,
    HookBus,
    STATE_ACTIVE,
    STATE_DISABLED,
    STATE_ERROR
)
from core.addons.catalog import (
    fetch_catalog,
    get_catalog_item,
    is_compatible,
    DEFAULT_CATALOG_URL
)
from core.addons.installer import (
    install_remote_addon
)

def emit_hook(event_name: str, *args, **kwargs):
    """Convenience helper to emit an event across all loaded and active addons."""
    return addon_manager.emit_hook(event_name, *args, **kwargs)

__all__ = [
    "addon_manager",
    "AddonManager",
    "AddonRecord",
    "HookBus",
    "STATE_ACTIVE",
    "STATE_DISABLED",
    "STATE_ERROR",
    "emit_hook",
    "fetch_catalog",
    "get_catalog_item",
    "is_compatible",
    "DEFAULT_CATALOG_URL",
    "install_remote_addon"
]
