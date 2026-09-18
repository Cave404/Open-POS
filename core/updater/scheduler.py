"""
=============================================================================
Open-POS Update Scheduler Daemon (core/updater/scheduler.py)
=============================================================================
Governs maintenance window execution and update preferences:
  - Configuration persistence in data/config/update_preferences.json
  - Idle cart detection to safeguard active POS checkout sessions
  - Day-of-week and time-of-day maintenance window calculation
  - Background daemon thread executing scheduled atomic updates
  - Full audit logging to data/logs/updater.log
=============================================================================
"""

import os
import json
import time
import threading
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from core.config import Config
from core.logger import logger
from core.updater.checker import check_for_system_updates
from core.updater.engine import apply_system_update, restart_openpos

PREFERENCES_FILE = os.path.join(Config.DATA_DIR, "config", "update_preferences.json")

DEFAULT_PREFERENCES: Dict[str, Any] = {
    "auto_check": True,
    "check_interval_hours": 6,
    "auto_install": False,
    "schedule_day": "monday",
    "schedule_time": "03:00",
    "require_empty_cart": True
}

_scheduler_thread: Optional[threading.Thread] = None
_scheduler_started = False
_scheduler_lock = threading.Lock()
_last_executed_window_key: Optional[str] = None


def _log_to_updater_file(msg: str, level: str = "INFO") -> None:
    """Appends an ISO-timestamped audit record to data/logs/updater.log."""
    try:
        log_file = os.path.join(Config.DATA_DIR, "logs", "updater.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")
    except Exception:
        pass


def get_update_preferences() -> Dict[str, Any]:
    """
    Retrieves the scheduled update configuration from disk.
    If the file does not exist, writes and returns DEFAULT_PREFERENCES.
    """
    if os.path.exists(PREFERENCES_FILE):
        try:
            with open(PREFERENCES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_PREFERENCES)
            merged.update(data)
            return merged
        except Exception as e:
            logger.warning(f"[SCHEDULER] Error loading {PREFERENCES_FILE}: {e}")

    # Initialize default configuration file
    try:
        os.makedirs(os.path.dirname(PREFERENCES_FILE), exist_ok=True)
        with open(PREFERENCES_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PREFERENCES, f, indent=2)
    except Exception as e:
        logger.warning(f"[SCHEDULER] Could not persist default preferences: {e}")

    return dict(DEFAULT_PREFERENCES)


def save_update_preferences(prefs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates and persists updated scheduler preferences to disk.
    """
    current = get_update_preferences()

    if "auto_check" in prefs:
        current["auto_check"] = bool(prefs["auto_check"])
    if "check_interval_hours" in prefs:
        try:
            val = int(prefs["check_interval_hours"])
            current["check_interval_hours"] = max(1, min(val, 168))
        except (ValueError, TypeError):
            pass
    if "auto_install" in prefs:
        current["auto_install"] = bool(prefs["auto_install"])
    if "schedule_day" in prefs:
        day_str = str(prefs["schedule_day"]).strip().lower()
        valid_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "everyday", "daily"}
        if day_str in valid_days:
            current["schedule_day"] = day_str
    if "schedule_time" in prefs:
        time_str = str(prefs["schedule_time"]).strip()
        parts = time_str.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            hour = int(parts[0])
            minute = int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                current["schedule_time"] = f"{hour:02d}:{minute:02d}"
    if "require_empty_cart" in prefs:
        current["require_empty_cart"] = bool(prefs["require_empty_cart"])

    os.makedirs(os.path.dirname(PREFERENCES_FILE), exist_ok=True)
    with open(PREFERENCES_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)

    _log_to_updater_file(f"Updated preferences: auto_install={current.get('auto_install')}, schedule={current.get('schedule_day')}@{current.get('schedule_time')}")
    return current


def is_cart_idle() -> bool:
    """
    Checks if any active register cart in memory currently contains line items
    or has an outstanding balance. Returns True if cart is completely idle.
    """
    try:
        from core.services.cart_service import CartService
        svc = CartService.get_instance()
        with svc._lock:
            for cart_id, cart in svc._carts.items():
                items = cart.get("items", [])
                grand_total = float(cart.get("grand_total", 0.0))
                if items or grand_total > 0:
                    return False
        return True
    except Exception as e:
        logger.warning(f"[SCHEDULER] Could not inspect CartService status: {e}")
        return True


def is_window_due(prefs: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """
    Determines whether the maintenance window is active for the current minute.
    Guarantees that a maintenance window only fires once per matching minute.
    """
    global _last_executed_window_key
    if now is None:
        now = datetime.now()

    target_day = prefs.get("schedule_day", "monday").strip().lower()
    target_time = prefs.get("schedule_time", "03:00").strip()

    current_day = now.strftime("%A").lower()
    current_time = now.strftime("%H:%M")

    # Match day
    day_matches = (target_day in {"everyday", "daily"}) or (target_day == current_day)
    time_matches = (target_time == current_time)

    if day_matches and time_matches:
        window_key = f"{now.strftime('%Y-%m-%d')}_{current_time}"
        if _last_executed_window_key == window_key:
            return False  # Already executed this minute
        _last_executed_window_key = window_key
        return True

    return False


def _scheduler_worker(app=None) -> None:
    """Background daemon loop for update checking and scheduled maintenance execution."""
    logger.info("[SCHEDULER] Update scheduler daemon started.")
    last_auto_check_ts = 0.0

    while True:
        try:
            prefs = get_update_preferences()
            now_ts = time.time()
            check_interval_sec = prefs.get("check_interval_hours", 6) * 3600

            # 1. Periodic background update check
            if prefs.get("auto_check", True) and (now_ts - last_auto_check_ts >= check_interval_sec):
                last_auto_check_ts = now_ts
                check_for_system_updates(force=False)

            # 2. Maintenance window auto-install
            if prefs.get("auto_install", False):
                if is_window_due(prefs):
                    _log_to_updater_file("Maintenance window arrived. Evaluating execution preconditions...")
                    logger.info("[SCHEDULER] Maintenance window arrived. Evaluating preconditions...")

                    # Check cart state if required
                    if prefs.get("require_empty_cart", True) and not is_cart_idle():
                        msg = "Scheduled maintenance window deferred: Active POS cart session in progress."
                        logger.warning(f"[SCHEDULER] {msg}")
                        _log_to_updater_file(msg, level="WARNING")
                    else:
                        _log_to_updater_file("Cart is idle. Checking for available system release...")
                        info = check_for_system_updates(force=True)
                        if info.get("update_available") and info.get("download_url"):
                            new_ver = info.get("latest_version")
                            dl_url = info.get("download_url")
                            _log_to_updater_file(f"Applying scheduled update to {new_ver}...")
                            logger.info(f"[SCHEDULER] Applying scheduled update to {new_ver}...")

                            success = apply_system_update(dl_url, new_ver)
                            if success:
                                _log_to_updater_file(f"Scheduled update to {new_ver} succeeded. Restarting OpenPOS...")
                                logger.info("[SCHEDULER] Scheduled update succeeded. Restarting OpenPOS...")
                                restart_openpos()
                            else:
                                _log_to_updater_file(f"Scheduled update to {new_ver} failed and was rolled back.", level="ERROR")
                        else:
                            _log_to_updater_file("Maintenance window check: System is already up to date.")

        except Exception as e:
            logger.error(f"[SCHEDULER] Exception in scheduler worker: {e}", exc_info=True)

        time.sleep(30)


def start_update_scheduler_daemon(app=None) -> Optional[threading.Thread]:
    """
    Initializes and starts the update scheduler daemon thread if not already running.
    """
    global _scheduler_thread, _scheduler_started

    with _scheduler_lock:
        if _scheduler_started and _scheduler_thread and _scheduler_thread.is_alive():
            return _scheduler_thread

        _scheduler_thread = threading.Thread(
            target=_scheduler_worker,
            args=(app,),
            name="openpos-update-scheduler",
            daemon=True
        )
        _scheduler_thread.start()
        _scheduler_started = True
        return _scheduler_thread
