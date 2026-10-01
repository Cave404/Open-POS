"""
=============================================================================
Test Suite: Unified Admin Authentication & Single Source of Truth Elevation
Tests Phase 1, Phase 2, and Phase 3 requirements:
  - 15-minute rolling session elevation TTL
  - Clean server-side lock screen (auth/manager_lock.html)
  - Seamless navigation between protected sections without re-prompting
  - Inactivity expiration & clean logout re-locking
  - Elimination of dual-modal client-side interceptor collisions
=============================================================================
"""

import time
import json
import hashlib
import pytest
from app import create_app
from core.auth import (
    is_manager_elevated,
    refresh_elevation,
    revoke_elevation,
    SESSION_ELEVATION_TTL,
)
from core.services.security_service import verify_admin_pin


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-12345"
    with app.test_client() as client:
        yield client


@pytest.fixture
def configure_auth_credentials(tmp_path, monkeypatch):
    """Configures a temporary, isolated manager_auth.json with PIN 4321."""
    salt = "somesalt123"
    pin = "4321"
    hashed = hashlib.sha256((salt + pin).encode("utf-8")).hexdigest()

    auth_file = str(tmp_path / "manager_auth.json")
    pin_file = str(tmp_path / "admin_pin.hash")

    with open(auth_file, "w", encoding="utf-8") as f:
        json.dump({
            "require_password": True,
            "password_hash": hashed,
            "salt": salt,
            "protected_sections": ["branding", "database", "admin"],
            "bypass_manager_on_boot": False
        }, f)

    with open(pin_file, "w", encoding="utf-8") as f:
        f.write(hashlib.sha256(pin.encode("utf-8")).hexdigest())

    monkeypatch.setattr("manager.routes.AUTH_CONFIG_PATH", auth_file)
    monkeypatch.setattr("core.setup.wizard.AUTH_CONFIG_PATH", auth_file)
    monkeypatch.setattr("core.services.security_service.AUTH_CONFIG_PATH", auth_file)
    return pin


def test_elevation_helpers_and_expiration(client):
    """Verifies is_manager_elevated, refresh_elevation, and revoke_elevation."""
    app = client.application
    with app.test_request_context("/"):
        from flask import session
        assert not is_manager_elevated()

        # Refresh sets 15-minute elevation
        refresh_elevation()
        assert is_manager_elevated()
        assert session.get("manager_elevated_until") > time.time() + 800

        # Simulate expiration
        session["manager_elevated_until"] = time.time() - 10
        assert not is_manager_elevated()

        # Revoke clears tokens
        refresh_elevation()
        revoke_elevation()
        assert not is_manager_elevated()
        assert "manager_elevated_until" not in session


def test_verify_admin_pin_service(configure_auth_credentials):
    """Verifies that verify_admin_pin validates credentials against isolated config."""
    correct_pin = configure_auth_credentials

    assert verify_admin_pin(correct_pin) is True
    assert verify_admin_pin("wrongpin") is False
    assert verify_admin_pin("") is False
    assert verify_admin_pin(None) is False


def test_unauthenticated_protected_route_renders_single_lock_screen(client, configure_auth_credentials):
    """
    Verifies that accessing an unauthenticated protected view returns the unified
    manager_lock.html access gate without client-side modal interceptors.
    """
    res = client.get("/manager/database")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Clean lock screen elements must be present
    assert "Manager Authentication Required" in html
    assert 'id="managerLockForm"' in html
    assert 'id="adminPinInput"' in html
    assert 'id="btnSubmitUnlock"' in html
    assert "Return to Dashboard" in html
    assert 'value="/manager/database"' in html

    # Redundant client-side interceptor scripts must NOT be present
    assert 'lockout_guard.js' not in html
    assert 'lockout_modal.html' not in html


def test_unauthenticated_api_request_returns_401(client, configure_auth_credentials):
    """Verifies that JSON requests to protected routes receive 401 JSON instead of HTML."""
    res = client.get("/manager/database", headers={"Accept": "application/json"})
    assert res.status_code == 401
    data = res.get_json()
    assert data["success"] is False
    assert data["auth_required"] is True


def test_verify_pin_endpoint_validation_and_elevation(client, configure_auth_credentials):
    """
    Tests /auth/verify-pin and /manager/auth/verify-pin:
      - 400 on blank PIN
      - 403 on wrong PIN
      - 200 on correct PIN with 15-minute elevation and redirect_url
    """
    correct_pin = configure_auth_credentials

    # 1. Blank PIN -> 400
    res_blank = client.post("/auth/verify-pin", json={"pin": "", "next_url": "/manager/database"})
    assert res_blank.status_code == 400
    assert res_blank.get_json()["success"] is False

    # 2. Invalid PIN -> 403
    res_bad = client.post("/auth/verify-pin", json={"pin": "9999", "next_url": "/manager/database"})
    assert res_bad.status_code == 403
    assert res_bad.get_json()["success"] is False

    # 3. Correct PIN -> 200 and redirect
    res_ok = client.post("/auth/verify-pin", json={"pin": correct_pin, "next_url": "/manager/database"})
    assert res_ok.status_code == 200
    data = res_ok.get_json()
    assert data["success"] is True
    assert data["redirect_url"] == "/manager/database"

    # Confirm elevation timestamp is populated in session
    with client.session_transaction() as sess:
        assert sess.get("manager_elevated_until") > time.time() + 850


def test_elevated_session_bypasses_all_protected_subviews(client, configure_auth_credentials):
    """
    Verifies that once elevated, navigation between Database Tools, Controls & Branding,
    and Administration succeeds immediately without repeated PIN challenges.
    """
    correct_pin = configure_auth_credentials

    # Step 1: Elevate via /auth/verify-pin
    res_auth = client.post("/auth/verify-pin", json={"pin": correct_pin, "next_url": "/manager/database"})
    assert res_auth.status_code == 200

    # Step 2: Access Database Tools -> rendered immediately
    res_db = client.get("/manager/database")
    assert res_db.status_code == 200
    html_db = res_db.get_data(as_text=True)
    assert "Database Tools" in html_db
    assert "Switch Engine / Migrate Database" in html_db
    assert 'id="managerLockForm"' not in html_db

    # Step 3: Navigate directly to Branding -> rendered immediately without PIN prompt
    res_brand = client.get("/manager/branding")
    assert res_brand.status_code == 200
    html_brand = res_brand.get_data(as_text=True)
    assert "Store Identity" in html_brand
    assert 'id="managerLockForm"' not in html_brand

    # Step 4: Navigate directly to Administration / Configure Manager
    res_admin = client.get("/manager/configure_manager")
    assert res_admin.status_code == 200
    html_admin = res_admin.get_data(as_text=True)
    assert "Configure Manager" in html_admin
    assert 'id="managerLockForm"' not in html_admin

    # Step 5: Route aliases (/manager/db and /manager/admin) also work seamlessly
    res_alias_db = client.get("/manager/db")
    assert res_alias_db.status_code == 200
    assert "Database Tools" in res_alias_db.get_data(as_text=True)

    res_alias_admin = client.get("/manager/admin")
    assert res_alias_admin.status_code == 200
    assert "Configure Manager" in res_alias_admin.get_data(as_text=True)


def test_elevation_expiration_relocks_routes(client, configure_auth_credentials):
    """
    Verifies that when the elevation timestamp expires (simulating 15 minutes of inactivity),
    the single lock screen reappears appropriately.
    """
    correct_pin = configure_auth_credentials

    # Authenticate
    client.post("/auth/verify-pin", json={"pin": correct_pin, "next_url": "/manager/database"})

    # Manually expire the session timestamp
    with client.session_transaction() as sess:
        sess["manager_elevated_until"] = time.time() - 5

    # Requesting protected route should now render the clean lock screen again
    res = client.get("/manager/database")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Manager Authentication Required" in html
    assert 'id="managerLockForm"' in html
    assert "Database Tools" not in html


def test_logout_revokes_elevation(client, configure_auth_credentials):
    """Verifies that POST /api/settings/logout revokes elevation and re-locks routes."""
    correct_pin = configure_auth_credentials

    # Authenticate
    client.post("/auth/verify-pin", json={"pin": correct_pin, "next_url": "/manager/database"})

    # Logout
    res_logout = client.post("/api/settings/logout")
    assert res_logout.status_code == 200

    # Protected route should now be locked
    res_relocked = client.get("/manager/database")
    assert res_relocked.status_code == 200
    html = res_relocked.get_data(as_text=True)
    assert "Manager Authentication Required" in html
    assert 'id="managerLockForm"' in html
