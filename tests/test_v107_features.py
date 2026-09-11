"""
Unit & Integration Tests for Open-POS v1.0.7 Features:
1. Absolute Test Data Isolation (autouse temp DB fixtures & non-destructive settings init)
2. Global Styled 404/500 Error Handlers & Addon Route Resolution
3. Single Unified Lockout Screen & Persistent Manager Session
4. Decoupled TCG Rules to Addon & Generic Retail Branding
5. Addon Lifecycle Management: Import ZIP, Configure, & Uninstall
6. Version Milestone Bump to v1.0.7
"""

import io
import json
import os
import hashlib
import zipfile
import pytest
from app import create_app
from core.config import Config
from core.addons import addon_manager, STATE_ACTIVE, STATE_DISABLED, STATE_ERROR
from core.settings import get_all_settings, get_setting, set_setting, update_setting, seed_default_settings, get_db_connection


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ============================================================================
# 1. Milestone Versioning (v1.0.7)
# ============================================================================

def test_v107_version_milestone(client):
    """Asserts that Config.VERSION and API credits strictly reflect v1.0.7."""
    assert Config.VERSION == "v1.0.7"

    res_credits = client.get("/api/system/credits")
    assert res_credits.status_code == 200
    assert res_credits.get_json()["version"] == "v1.0.7"

    # Verify templates render v1.0.7
    routes = [
        "/manager",
        "/manager/about",
        "/manager/branding",
        "/manager/configure_manager",
        "/manager/database",
        "/manager/logs",
        "/manager/addons",
    ]
    for route in routes:
        res = client.get(route, follow_redirects=True)
        assert res.status_code == 200, f"Route {route} failed with {res.status_code}"
        assert "v1.0.7" in res.get_data(as_text=True), f"Route {route} missing v1.0.7 badge"


# ============================================================================
# 2. Test Isolation & Data Protection
# ============================================================================

def test_data_isolation_does_not_touch_production_db():
    """Asserts that tests run against isolated temp database, not production."""
    assert "test_isolated.db" in Config.DB_PATH
    assert os.path.isabs(Config.DB_PATH)


def test_seed_default_settings_preserves_existing_user_configuration():
    """Asserts that seed_default_settings NEVER overwrites user-configured settings."""
    # Write custom user settings
    update_setting("store_name", "My Unique Custom Comic Store")
    update_setting("currency_symbol", "£")
    update_setting("tax_rate", 20.0)

    # Re-run seed_default_settings
    seed_default_settings(force=False)

    # Verify user values are completely preserved
    assert get_setting("store_name") == "My Unique Custom Comic Store"
    assert get_setting("currency_symbol") == "£"
    assert float(get_setting("tax_rate")) == 20.0


# ============================================================================
# 3. Global Styled Error Handlers & Addon Route Resolution
# ============================================================================

def test_global_404_error_handler_renders_styled_page(client):
    """Asserts that requesting a non-existent route returns styled error.html with return button."""
    res = client.get("/this_route_definitely_does_not_exist_404")
    assert res.status_code == 404
    html = res.get_data(as_text=True)

    # Must contain OpenPOS branding, 404 error code, requested path, and Return to System Manager button
    assert "404" in html
    assert "Not Found" in html
    assert "/this_route_definitely_does_not_exist_404" in html
    assert "Return to System Manager" in html
    assert 'href="/manager"' in html
    assert "manager.css" in html


def test_global_500_error_handler(client):
    """Asserts that an unhandled 500 error returns styled error.html with status 500."""
    app = client.application
    app.config["PROPAGATE_EXCEPTIONS"] = False

    # Simulate an endpoint raising an error
    def broken_view():
        raise RuntimeError("Simulated runtime error for 500 test")

    app.add_url_rule("/test_force_500_route", "test_force_500_route", broken_view)

    res = client.get("/test_force_500_route")
    assert res.status_code == 500
    html = res.get_data(as_text=True)
    assert "500" in html
    assert "Internal Server Failure" in html or "500" in html
    assert "Return to System Manager" in html


def test_list_applets_fallback_for_unregistered_routes(client):
    """Asserts that list_applets falls back unregistered addon routes to /manager/placeholder/<addon_id>."""
    res = client.get("/manager/api/applets")
    assert res.status_code == 200
    applets = res.get_json()
    assert isinstance(applets, list)
    assert len(applets) >= 1

    # Check each applet's target - none should point to a raw unhandled 404 route
    for applet in applets:
        target = applet.get("target")
        assert target is not None
        # Either the target is registered, or it points to /manager/placeholder/
        res_target = client.get(target, follow_redirects=True)
        assert res_target.status_code in (200, 302, 503), f"Applet '{applet.get('name')}' target '{target}' returned {res_target.status_code}"


# ============================================================================
# 4. Single Unified Lockout Screen & Session Persistence
# ============================================================================

def test_session_cookie_configuration(client):
    """Asserts that Flask session cookies are configured for security and persistence."""
    app = client.application
    assert app.config.get("SESSION_PERMANENT") is False
    assert app.config.get("SESSION_COOKIE_HTTPONLY") is True
    assert app.config.get("SESSION_COOKIE_SAMESITE") == "Lax"


def test_persistent_manager_session_authentication(client, tmp_path, monkeypatch):
    """Asserts that session['manager_authenticated'] persists and bypasses repeated prompts."""
    salt = "testsalt123"
    pwd = "adminsecretpassword"
    pwd_hash = hashlib.sha256((salt + pwd).encode("utf-8")).hexdigest()

    auth_file = tmp_path / "manager_auth.json"
    with open(auth_file, "w", encoding="utf-8") as f:
        json.dump({
            "require_password": True,
            "password_hash": pwd_hash,
            "salt": salt,
            "protected_sections": ["branding", "database", "admin"]
        }, f)
    monkeypatch.setattr("manager.routes.AUTH_CONFIG_PATH", str(auth_file))

    # 1. Before authentication: status endpoint reports not authenticated
    res_status1 = client.get("/api/admin/auth/status")
    assert res_status1.status_code == 200
    assert res_status1.get_json()["authenticated"] is False

    # 2. Authenticate via verify_password
    res_auth = client.post("/api/settings/verify_password", json={"password": pwd})
    assert res_auth.status_code == 200
    assert res_auth.get_json()["authorized"] is True

    # 3. After authentication: status endpoint reports authenticated = True
    res_status2 = client.get("/api/admin/auth/status")
    assert res_status2.status_code == 200
    data2 = res_status2.get_json()
    assert data2["authenticated"] is True
    assert data2["authorized"] is True

    # 4. Navigating to manager subviews succeeds with session preserved
    res_branding = client.get("/manager/branding")
    assert res_branding.status_code == 200


# ============================================================================
# 5. Decouple TCG Rules from Core Store Branding
# ============================================================================

def test_branding_template_is_generic_retail(client):
    """Asserts that Trade-In & Buylist Rules and Condition Multipliers are removed from core branding."""
    res = client.get("/manager/branding")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Core generic retail fields must be present
    assert "Store Identity" in html
    assert "Retail &amp; Currency Localization" in html or "Retail & Currency Localization" in html
    assert "currency_symbol" in html
    assert "tax_rate" in html
    assert "Store Logo" in html

    # TCG-specific rules MUST be absent
    assert "Trade-In &amp; Buylist Rules" not in html
    assert "Trade-In & Buylist Rules" not in html
    assert "Condition Multipliers" not in html
    assert "payout_cash" not in html
    assert "mult_nm" not in html


def test_decoupled_tcg_rules_schema_file():
    """Asserts that addons/tcg_pos/default_rules.json exists with proper trade-in and condition rules."""
    tcg_rules_path = os.path.join(Config.BASE_DIR, "addons", "tcg_pos", "default_rules.json")
    assert os.path.isfile(tcg_rules_path), f"TCG rules file not found at {tcg_rules_path}"

    with open(tcg_rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)

    assert "cash_payout_rate" in rules
    assert "credit_payout_rate" in rules
    assert "condition_multipliers" in rules
    assert rules["cash_payout_rate"] == 60.0
    assert rules["credit_payout_rate"] == 80.0
    assert rules["condition_multipliers"]["NM"] == 1.0
    assert rules["condition_multipliers"]["LP"] == 0.85
    assert rules["condition_multipliers"]["HP"] == 0.50


def test_update_retail_settings_api(client):
    """Asserts that /api/settings accepts currency_symbol and tax_rate."""
    payload = {
        "store_name": "Antigravity Mega Store",
        "store_legal_entity": "Antigravity Enterprises LLC",
        "store_location": "Austin, TX",
        "currency_symbol": "€",
        "tax_rate": 7.5
    }
    res = client.post("/api/settings", json=payload)
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"

    # Verify persistence
    assert get_setting("currency_symbol") == "€"
    assert float(get_setting("tax_rate")) == 7.5
    assert get_setting("store_name") == "Antigravity Mega Store"


# ============================================================================
# 6. Addon Lifecycle Management: Import, Configure, Uninstall
# ============================================================================

def test_addons_html_contains_import_and_remove_controls(client):
    """Asserts that manager/templates/addons.html contains Import button and Remove action."""
    res = client.get("/manager/addons")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Import Addon (.zip)
    assert "Import Addon (.zip)" in html
    assert "addonZipInput" in html
    assert "handleZipUpload" in html

    # Remove controls
    assert "removeConfirmModal" in html
    assert "confirmRemoveAddon" in html
    assert "btn-remove" in html


def test_addon_import_zip_and_uninstall_pipeline(client, tmp_path):
    """Asserts that POST /api/addons/import installs an addon ZIP, and DELETE /api/addons/<id> uninstalls it."""
    # 1. Build an in-memory ZIP containing a valid custom addon
    addon_id = "custom_test_bundle"
    manifest = {
        "id": addon_id,
        "name": "Custom Test Bundle",
        "version": "1.0.0",
        "entrypoint": "plugin.py",
        "author": "Test Lab",
        "description": "Custom imported addon testing bundle.",
        "settings_route": "/addons/custom_test_bundle/settings"
    }
    entrypoint_code = """
from flask import Blueprint, jsonify

blueprint = Blueprint('custom_test_bundle', __name__)

@blueprint.route('/settings')
def settings():
    return jsonify({"status": "ok", "addon": "custom_test_bundle"})
"""

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{addon_id}/manifest.json", json.dumps(manifest))
        zf.writestr(f"{addon_id}/plugin.py", entrypoint_code)
    zip_buffer.seek(0)

    # 2. Upload and import the ZIP archive via POST /api/addons/import
    data = {
        "file": (zip_buffer, "custom_test_bundle.zip")
    }
    res_import = client.post("/api/addons/import", data=data, content_type="multipart/form-data")
    assert res_import.status_code == 200
    import_json = res_import.get_json()
    assert import_json["success"] is True
    assert import_json["id"] == addon_id

    # 3. Verify the addon is discovered and mounted in the manager
    rec = addon_manager.get_addon(addon_id)
    assert rec is not None
    assert rec["name"] == "Custom Test Bundle"
    assert rec["dir_type"] == "custom"

    # 4. Protection check: Attempting to delete a built-in addon must be rejected
    res_delete_builtin = client.delete("/api/addons/test_addon")
    assert res_delete_builtin.status_code == 400
    assert "Cannot remove built-in" in res_delete_builtin.get_json()["error"]

    # 5. Uninstall custom addon via DELETE /api/addons/<addon_id>
    res_delete_custom = client.delete(f"/api/addons/{addon_id}")
    assert res_delete_custom.status_code == 200
    assert res_delete_custom.get_json()["success"] is True

    # 6. Verify addon is purged from addon manager
    assert addon_manager.get_addon(addon_id) is None
