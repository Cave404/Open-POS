"""
=============================================================================
Open-POS In-App Self-Updater Package
=============================================================================
Provides background GitHub Release checking, changelog parsing,
pre-update snapshotting, in-place code replacement, health-check
verification, automated rollback on failure, scheduled maintenance windows,
and detached process restarting.

Exports:
    check_for_system_updates()  -- Query GitHub Releases API with 2-hour cache.
    parse_markdown_changelog()  -- Categorize notes into added, changed, fixed, removed.
    check_for_updates()         -- Query GitHub Releases API for latest release.
    get_update_status()         -- Return cached UpdateInfo dict.
    start_background_checker()  -- Spawn background polling thread.
    apply_system_update()       -- Atomic snapshot, download, swap, verify, rollback.
    restart_openpos()           -- Launch detached Start_POS.bat and terminate.
    get_update_preferences()    -- Read update_preferences.json.
    save_update_preferences()   -- Persist update_preferences.json.
    is_cart_idle()              -- Check if POS register has no active checkout.
    is_window_due()             -- Check if maintenance window matches current minute.
    start_update_scheduler_daemon() -- Start scheduler daemon thread.
    create_snapshot()           -- Snapshot core source tree into data/backups/.
    apply_update()              -- Download and apply a release ZIP in-place.
    run_health_check()          -- Verify system boots successfully post-update.
    rollback()                  -- Restore from snapshot on health-check failure.
    install_update()            -- Orchestrate full snapshot→apply→check→rollback pipeline.
=============================================================================
"""

from core.updater.checker import (
    check_for_system_updates,
    parse_markdown_changelog,
    check_for_updates,
    get_update_status,
    start_background_checker,
)

from core.updater.engine import (
    apply_system_update,
    restart_openpos,
)

from core.updater.scheduler import (
    get_update_preferences,
    save_update_preferences,
    is_cart_idle,
    is_window_due,
    start_update_scheduler_daemon,
)

from core.updater.installer import (
    create_snapshot,
    apply_update,
    run_health_check,
    rollback,
    install_update,
)

__all__ = [
    "check_for_system_updates",
    "parse_markdown_changelog",
    "check_for_updates",
    "get_update_status",
    "start_background_checker",
    "apply_system_update",
    "restart_openpos",
    "get_update_preferences",
    "save_update_preferences",
    "is_cart_idle",
    "is_window_due",
    "start_update_scheduler_daemon",
    "create_snapshot",
    "apply_update",
    "run_health_check",
    "rollback",
    "install_update",
]
