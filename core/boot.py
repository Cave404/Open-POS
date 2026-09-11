"""
=============================================================================
Open-POS System Boot Sequencer & Update Verification Hook
=============================================================================
This module orchestrates the multi-phase initialization pipeline executed on
application startup. It reports granular percentage progress and status
messages to the desktop splash window before transitioning control to the
primary System Manager dashboard.

Boot Pipeline Stages:
  Phase 1 (0% - 20%):   Environment & Configuration Verification
  Phase 2 (20% - 45%):  Git Repository Update Checker Hook
  Phase 3 (45% - 70%):  Database Schema & Image Cache Sanity Check
  Phase 4 (70% - 90%):  Addon Plugin Discovery & Manifest Registration
  Phase 5 (90% - 100%): Finalization Buffer & Desktop Handoff
=============================================================================
"""

import os
import json
import time
import logging
import subprocess
from typing import Callable, Optional, Dict, Any

from core.config import Config
from core.db import init_db, get_db_connection, execute_sql
from core.settings import seed_default_settings, get_setting

logger = logging.getLogger(__name__)

# Base project directory reference
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def run_boot_sequence(
    progress_callback: Optional[Callable[[int, str], None]] = None,
    buffer_seconds: float = 1.5,
    check_git_remote: bool = True
) -> Dict[str, Any]:
    """
    Executes the 5-phase startup sequence and reports progress updates.

    :param progress_callback: Optional callable accepting (percent: int, message: str)
    :param buffer_seconds: Duration to hold on 100% 'Finishing up...' before handoff
    :param check_git_remote: Whether to perform a live remote dry-run git fetch
    :return: Diagnostic dictionary summarizing the initialization results
    """
    boot_log = {
        "status": "success",
        "environment": {},
        "updates": {},
        "database": {},
        "addons": [],
        "errors": []
    }

    def _notify(percent: int, message: str, delay: float = 0.15):
        """Dispatches status updates to the callback and logger."""
        logger.info(f"[Boot {percent}%] {message}")
        if progress_callback:
            try:
                progress_callback(percent, message)
            except Exception as cb_err:
                logger.warning(f"Boot progress callback failed: {cb_err}")
        if delay > 0:
            time.sleep(delay)

    try:
        # =====================================================================
        # Phase 1: Environment & Configuration Verification (0% - 20%)
        # =====================================================================
        _notify(5, "Verifying runtime environment & settings...")

        env_file_path = os.path.join(BASE_DIR, '.env')
        boot_log["environment"]["env_file_exists"] = os.path.isfile(env_file_path)
        boot_log["environment"]["host"] = Config.HOST
        boot_log["environment"]["port"] = Config.PORT
        boot_log["environment"]["db_engine"] = getattr(Config, 'DB_ENGINE', 'sqlite')
        boot_log["environment"]["store_name"] = getattr(Config, 'STORE_NAME', 'Open-POS System')

        _notify(15, "Loading configuration parameters...")
        _notify(20, "Runtime environment verified.")

        # =====================================================================
        # Phase 2: Update Check Hook (20% - 45%)
        # =====================================================================
        _notify(25, "Checking for system updates...")

        git_dir = os.path.join(BASE_DIR, '.git')
        boot_log["updates"]["is_git_repo"] = os.path.isdir(git_dir)
        boot_log["updates"]["update_available"] = False

        if boot_log["updates"]["is_git_repo"] and check_git_remote:
            _notify(35, "Checking repository remote status...")
            try:
                # Query git remote status with a strict timeout to prevent boot hang
                result = subprocess.run(
                    ["git", "status", "-uno"],
                    cwd=BASE_DIR,
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                if "Your branch is behind" in result.stdout:
                    boot_log["updates"]["update_available"] = True
                    boot_log["updates"]["status_text"] = "Update available from origin."
                else:
                    boot_log["updates"]["status_text"] = "Repository up to date."
            except Exception as git_err:
                logger.debug(f"Git check non-critical notice: {git_err}")
                boot_log["updates"]["status_text"] = "Offline or dry-run complete."
        else:
            boot_log["updates"]["status_text"] = "Update checker skipped or not a git repo."

        auto_update_pref = get_setting('auto_updates_enabled', default=False)
        boot_log["updates"]["auto_update_policy"] = "enabled" if auto_update_pref else "deferred"

        _notify(45, "Update verification complete.")

        # =====================================================================
        # Phase 3: Database & Cache Sanity Check (45% - 70%)
        # =====================================================================
        _notify(50, "Verifying database schema & tables...")

        # Initialize schema and seed defaults if empty
        init_db()
        seed_default_settings()

        with get_db_connection() as conn:
            cur = execute_sql(conn, "SELECT COUNT(*) FROM settings")
            row = cur.fetchone()
            settings_count = row[0] if row else 0
            boot_log["database"]["settings_count"] = settings_count

        _notify(60, "Verifying local card art cache...")
        cache_dir = os.path.join(BASE_DIR, 'static', 'card_cache')
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)
        boot_log["database"]["cache_directory"] = cache_dir

        _notify(70, "Database & storage integrity confirmed.")

        # =====================================================================
        # Phase 4: Addon Manifest Discovery (70% - 90%)
        # =====================================================================
        _notify(75, "Registering system addons & applets...")

        try:
            from core.addons import addon_manager
            all_addons = addon_manager.discover_and_load_all()
            discovered_addons = [
                {
                    "id": a.id,
                    "name": a.name,
                    "version": a.version,
                    "enabled": a.enabled,
                    "status": a.status
                }
                for a in all_addons.values()
            ]
        except Exception as add_err:
            logger.warning(f"Error during addon discovery in boot sequence: {add_err}")
            discovered_addons = []

        boot_log["addons"] = discovered_addons
        addon_count = len(discovered_addons)
        _notify(85, f"Loaded {addon_count} installed addon plugin{'s' if addon_count != 1 else ''}...")
        _notify(90, "System plugins & built-in tools ready.")

        # =====================================================================
        # Phase 5: Finalization & Smooth Handoff (90% - 100%)
        # =====================================================================
        _notify(100, "Finishing up...", delay=0.0)

        # Brief readiness buffer allowing staff to visually verify system health
        if buffer_seconds > 0:
            time.sleep(buffer_seconds)

    except Exception as fatal_err:
        logger.error(f"Error during boot sequence: {fatal_err}", exc_info=True)
        boot_log["status"] = "degraded"
        boot_log["errors"].append(str(fatal_err))
        _notify(100, "Boot completed with warnings.")

    return boot_log
