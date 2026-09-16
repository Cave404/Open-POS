"""
=============================================================================
Open-POS In-App Self-Updater Package
=============================================================================
Provides background GitHub Release checking, changelog parsing,
pre-update snapshotting, in-place code replacement, health-check
verification, and automated rollback on failure.

Exports:
    check_for_updates()         -- Query GitHub Releases API for latest release.
    get_update_status()         -- Return cached UpdateInfo dict.
    start_background_checker()  -- Spawn background polling thread.
    create_snapshot()           -- Snapshot core source tree into data/backups/.
    apply_update()              -- Download and apply a release ZIP in-place.
    run_health_check()          -- Verify system boots successfully post-update.
    rollback()                  -- Restore from snapshot on health-check failure.
    install_update()            -- Orchestrate full snapshot→apply→check→rollback pipeline.
=============================================================================
"""

from core.updater.checker import (
    check_for_updates,
    get_update_status,
    start_background_checker,
)

from core.updater.installer import (
    create_snapshot,
    apply_update,
    run_health_check,
    rollback,
    install_update,
)

__all__ = [
    "check_for_updates",
    "get_update_status",
    "start_background_checker",
    "create_snapshot",
    "apply_update",
    "run_health_check",
    "rollback",
    "install_update",
]
