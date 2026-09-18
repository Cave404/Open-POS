"""
=============================================================================
Open-POS System REST API Controller (core/routes/system_routes.py)
=============================================================================
Provides REST endpoints for core auto-updater management, GitHub release inspection,
maintenance window scheduling, and process restarting:
  - GET  /api/system/update/status
  - POST /api/system/update/check-now
  - POST /api/system/update/preferences
  - POST /api/system/update/apply
=============================================================================
"""

import time
import threading
import logging
from flask import Blueprint, jsonify, request

from core.config import Config
from core.updater.checker import check_for_system_updates
from core.updater.engine import apply_system_update, restart_openpos
from core.updater.scheduler import (
    get_update_preferences,
    save_update_preferences,
    is_cart_idle,
)

logger = logging.getLogger(__name__)

system_bp = Blueprint('system', __name__, url_prefix='/api/system')


@system_bp.route('/update/status', methods=['GET'])
def api_update_status():
    """
    Returns current engine version, cached update check result (2h TTL),
    maintenance window schedule preferences, and active cart idle status.
    """
    try:
        update_info = check_for_system_updates(force=False)
        preferences = get_update_preferences()
        cart_idle = is_cart_idle()

        return jsonify({
            "status": "success",
            "success": True,
            "current_version": Config.VERSION,
            "update_available": update_info.get("update_available", False),
            "latest_version": update_info.get("latest_version"),
            "release_name": update_info.get("release_name"),
            "published_at": update_info.get("published_at"),
            "changelog": update_info.get("changelog", {"added": [], "changed": [], "fixed": [], "removed": []}),
            "raw_notes": update_info.get("raw_notes", ""),
            "download_url": update_info.get("download_url"),
            "update_info": update_info,
            "preferences": preferences,
            "cart_idle": cart_idle,
        }), 200
    except Exception as e:
        logger.error(f"[SYSTEM_API] Failed to get update status: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "success": False,
            "message": str(e),
            "current_version": Config.VERSION,
            "update_available": False,
        }), 500


@system_bp.route('/update/check-now', methods=['POST'])
def api_update_check_now():
    """
    Bypasses the local 2-hour cache and executes an immediate check against
    the GitHub Releases API.
    """
    try:
        update_info = check_for_system_updates(force=True)
        return jsonify({
            "status": "success",
            "success": True,
            "current_version": Config.VERSION,
            "update_available": update_info.get("update_available", False),
            "latest_version": update_info.get("latest_version"),
            "release_name": update_info.get("release_name"),
            "published_at": update_info.get("published_at"),
            "changelog": update_info.get("changelog", {"added": [], "changed": [], "fixed": [], "removed": []}),
            "download_url": update_info.get("download_url"),
            "update_info": update_info,
        }), 200
    except Exception as e:
        logger.error(f"[SYSTEM_API] Force check failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "success": False,
            "message": str(e)
        }), 500


@system_bp.route('/update/preferences', methods=['POST'])
def api_update_preferences():
    """
    Updates schedule preferences (auto_check, auto_install, schedule_day,
    schedule_time, check_interval_hours, require_empty_cart).
    """
    try:
        data = request.get_json(silent=True) or {}
        saved = save_update_preferences(data)
        return jsonify({
            "status": "success",
            "success": True,
            "preferences": saved,
            "message": "Update preferences saved successfully."
        }), 200
    except Exception as e:
        logger.error(f"[SYSTEM_API] Error saving preferences: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "success": False,
            "message": str(e)
        }), 500


@system_bp.route('/update/apply', methods=['POST'])
def api_update_apply():
    """
    Applies the downloaded update in-place. If successful, spawns a detached
    restart via Start_POS.bat and exits. If verification fails, automatically
    rolls back to the pre-update snapshot.
    """
    try:
        data = request.get_json(silent=True) or {}
        download_url = data.get("download_url")
        new_version = data.get("new_version")

        if not download_url:
            cached = check_for_system_updates(force=False)
            download_url = cached.get("download_url")
            if not new_version:
                new_version = cached.get("latest_version")

        if not download_url:
            return jsonify({
                "status": "error",
                "success": False,
                "message": "No download URL available. Please check for updates first."
            }), 400

        target_version = new_version or "latest"
        logger.info(f"[SYSTEM_API] Triggering update to {target_version}")

        success = apply_system_update(download_url, target_version)
        if success:
            # Spawn detached restart after response completes
            def _delayed_restart():
                time.sleep(1.0)
                restart_openpos()

            threading.Thread(target=_delayed_restart, daemon=True).start()

            return jsonify({
                "status": "success",
                "success": True,
                "message": f"Update to {target_version} applied successfully. System is restarting...",
                "new_version": target_version
            }), 200
        else:
            return jsonify({
                "status": "error",
                "success": False,
                "message": "Update failed and system was rolled back to previous state. Check logs/updater.log for details."
            }), 500

    except Exception as e:
        logger.error(f"[SYSTEM_API] Error applying update: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "success": False,
            "message": str(e)
        }), 500
