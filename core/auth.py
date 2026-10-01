"""
=============================================================================
Open-POS Unified Manager Authentication Middleware (core/auth.py)
=============================================================================
Provides session-based elevation tokens, route decorators, and expiration
management for protected administrative views.
=============================================================================
"""

import time
from functools import wraps
from flask import request, redirect, render_template, session, url_for, jsonify
from core.services.security_service import verify_admin_pin, is_lockout_enabled

SESSION_ELEVATION_TTL = 900  # 15 minutes


def is_manager_elevated() -> bool:
    """
    Checks if current session has an active, unexpired elevation token.
    Evaluates session['manager_elevated_until'] timestamp against current time.
    """
    elevated_until = session.get("manager_elevated_until", 0)
    if elevated_until:
        if time.time() < elevated_until:
            return True
        # Timestamp expired - revoke tokens
        revoke_elevation()
        return False

    if session.get("manager_authenticated") is True:
        refresh_elevation()
        return True

    return False


def refresh_elevation():
    """
    Extends the manager elevation window by 15 minutes of rolling activity.
    """
    session["manager_elevated_until"] = time.time() + SESSION_ELEVATION_TTL
    session["manager_authenticated"] = True


def revoke_elevation():
    """
    Revokes elevated session permissions, locking administrative routes.
    """
    session.pop("manager_elevated_until", None)
    session.pop("manager_authenticated", None)


def manager_required(f):
    """
    Route decorator ensuring administrative access is gated behind session elevation.
    Bypasses access gate if setup wizard is incomplete or if lockout is unconfigured.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Bypass check if system is not yet initialized (.setup_complete missing)
        from core.config import Config
        import os
        if not os.path.exists(os.path.join(Config.DATA_DIR, "config", ".setup_complete")):
            return f(*args, **kwargs)

        if is_manager_elevated():
            refresh_elevation()
            return f(*args, **kwargs)

        # Bypass check if lockout policy is disabled in configuration
        if not is_lockout_enabled():
            return f(*args, **kwargs)

        if (
            request.is_json
            or request.path.startswith("/api/")
            or request.path.startswith("/manager/api/")
            or request.headers.get("Accept") == "application/json"
        ):
            return jsonify({"success": False, "error": "Authentication required", "auth_required": True}), 401

        clean_next_url = request.full_path.rstrip('?') if request.full_path.endswith('?') else request.full_path
        # Render clean, non-duplicated lock screen with return redirect
        return render_template("auth/manager_lock.html", next_url=clean_next_url)
    return decorated_function
