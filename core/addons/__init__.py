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
    "emit_hook"
]
