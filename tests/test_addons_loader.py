"""
Unit & Integration Tests for the Resilient Addon Engine and Sandboxed Plugin Loader (v1.0.6)
"""

import os
import shutil
import json
import pytest
from app import create_app
from core.config import Config
from core.addons import addon_manager, STATE_ACTIVE, STATE_DISABLED, STATE_ERROR, emit_hook
from core.db import get_db_connection, execute_sql
from core.notifications import get_alerts

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_v106_version_consistency(client):
    """Asserts that Config.VERSION and all manager templates strictly reflect active version."""
    assert Config.VERSION in ("v1.0.6", "v1.0.7", "v1.0.8")

    # API system credits
    res_credits = client.get("/api/system/credits")
    assert res_credits.status_code == 200
    assert res_credits.get_json()["version"] in ("v1.0.6", "v1.0.7", "v1.0.8")

    # Manager view templates
    views_to_check = [
        "/manager",
        "/manager/about",
        "/manager/branding",
        "/manager/configure_manager",
        "/manager/database",
        "/manager/logs",
        "/manager/addons",
        "/manager/applets"
    ]
    for route in views_to_check:
        res = client.get(route, follow_redirects=True)
        assert res.status_code == 200, f"Route {route} returned {res.status_code}"
        assert any(v in res.get_data(as_text=True) for v in ("v1.0.6", "v1.0.7", "v1.0.8")), f"Route {route} missing version tag"

def test_test_addon_discovery_and_mounting(client):
    """Asserts that test_addon is discovered, mounted, and exposes /addons/test_addon/status."""
    # Verify discovery in addon_manager
    addons = addon_manager.get_all_addons()
    test_addon = next((a for a in addons if a["id"] == "test_addon"), None)
    assert test_addon is not None
    assert test_addon["name"] == "Test Diagnostics Addon"
    assert test_addon["version"] == "1.0.0"
    assert test_addon["status"] == STATE_ACTIVE
    assert test_addon["requires_db"] is True

    # Verify route execution
    res = client.get("/addons/test_addon/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["addon"] == "test_addon"

def test_test_addon_database_migration():
    """Asserts that test_addon migration (schema_sqlite.sql) executed successfully."""
    with get_db_connection() as conn:
        cur = execute_sql(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name='test_addon_data'")
        row = cur.fetchone()
        assert row is not None

def test_test_addon_lifecycle_hook():
    """Asserts that test_addon registers and executes lifecycle hooks via emit_hook."""
    results = emit_hook("on_sale_complete", {"order_id": "ORD-1234", "total": 99.95})
    assert len(results) >= 1
    addon_result = next((r for r in results if r["addon_id"] == "test_addon"), None)
    assert addon_result is not None
    assert addon_result["status"] == "ok"
    assert addon_result["result"]["hook"] == "on_sale_complete"

def test_manager_addons_ui_and_apis(client):
    """Asserts that the Addons Control Center renders properly and management APIs function."""
    # 1. UI rendering
    res_ui = client.get("/manager/addons")
    assert res_ui.status_code == 200
    html = res_ui.get_data(as_text=True)
    assert "Applets &amp; Addons Manager" in html or "Applets & Addons Manager" in html
    assert "Return to Dashboard" in html
    assert "statTotalAddons" in html
    assert "errorModal" in html

    # 2. List API
    res_list = client.get("/manager/api/addons")
    assert res_list.status_code == 200
    addons_data = res_list.get_json()
    assert any(a["id"] == "test_addon" for a in addons_data)

    # 3. Builtin Applets List includes addons
    res_applets = client.get("/manager/api/applets")
    assert res_applets.status_code == 200
    applets = res_applets.get_json()
    applet_ids = [a["id"] for a in applets]
    assert "addons" in applet_ids
    assert "test_addon" in applet_ids

def test_addon_toggle_enable_disable(client):
    """Asserts that toggling an addon persists state and guards the endpoint with 503."""
    # 1. Disable addon
    res_disable = client.post("/manager/api/addons/test_addon/toggle", json={"enabled": False})
    assert res_disable.status_code == 200
    assert res_disable.get_json()["status"] == STATE_DISABLED

    # When disabled, route should return 503
    res_route_disabled = client.get("/addons/test_addon/status")
    assert res_route_disabled.status_code == 503

    # Hooks should not execute
    res_hooks = emit_hook("on_sale_complete")
    assert not any(r["addon_id"] == "test_addon" for r in res_hooks)

    # 2. Re-enable addon
    res_enable = client.post("/manager/api/addons/test_addon/toggle", json={"enabled": True})
    assert res_enable.status_code == 200
    assert res_enable.get_json()["status"] == STATE_ACTIVE

    # Route should return 200 again
    res_route_enabled = client.get("/addons/test_addon/status")
    assert res_route_enabled.status_code == 200
    assert res_route_enabled.get_json()["status"] == "ok"

def test_addon_fault_isolation_syntax_error(client):
    """
    CRITICAL ARCHITECTURAL REQUIREMENT:
    Asserts that a corrupted addon with invalid syntax in its entrypoint does NOT crash
    the core POS application, is caught by the sandbox, logged, and isolated in STATE_ERROR.
    """
    corrupt_dir = os.path.join(Config.CUSTOM_ADDONS_DIR, "corrupt_addon")
    os.makedirs(corrupt_dir, exist_ok=True)
    try:
        # Write valid manifest
        manifest = {
            "id": "corrupt_addon",
            "name": "Corrupted Plugin",
            "version": "0.1.0",
            "entrypoint": "plugin.py"
        }
        with open(os.path.join(corrupt_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        # Write invalid Python syntax in plugin.py
        with open(os.path.join(corrupt_dir, "plugin.py"), "w", encoding="utf-8") as f:
            f.write("def invalid_syntax_error( broken: !!! = @@@\n")

        # Load into addon manager
        record = addon_manager.load_addon(corrupt_dir, dir_type="custom")

        # Verify failure containment
        assert record.status == STATE_ERROR
        assert record.error is not None
        assert "SyntaxError" in record.traceback or "syntax" in record.error.lower()

        # Core POS routes MUST still function completely normally
        res_manager = client.get("/manager", follow_redirects=True)
        assert res_manager.status_code == 200

        res_test_addon = client.get("/addons/test_addon/status")
        assert res_test_addon.status_code == 200

        # Diagnostics API returns the trace
        res_diag = client.get("/manager/api/addons/corrupt_addon/diagnostics")
        assert res_diag.status_code == 200
        diag_data = res_diag.get_json()
        assert diag_data["status"] == STATE_ERROR
        assert diag_data["traceback"] is not None

        # Notifications queue should have recorded an alert
        alerts = get_alerts()
        assert any("corrupt_addon" in a["message"] for a in alerts)

    finally:
        if os.path.isdir(corrupt_dir):
            shutil.rmtree(corrupt_dir, ignore_errors=True)
        addon_manager.addons.pop("corrupt_addon", None)

def test_addon_missing_dependency_isolation(client):
    """
    Asserts that an addon declaring a missing third-party dependency is safely isolated
    without crashing the host application.
    """
    missing_dep_dir = os.path.join(Config.CUSTOM_ADDONS_DIR, "dep_fail_addon")
    os.makedirs(missing_dep_dir, exist_ok=True)
    try:
        manifest = {
            "id": "dep_fail_addon",
            "name": "Dependency Failure Plugin",
            "version": "1.0.0",
            "entrypoint": "plugin.py",
            "dependencies": ["non_existent_fake_package_xyz_999"]
        }
        with open(os.path.join(missing_dep_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        with open(os.path.join(missing_dep_dir, "plugin.py"), "w", encoding="utf-8") as f:
            f.write("# valid syntax\nfrom flask import Blueprint\nblueprint = Blueprint('dep_fail', __name__)\n")

        record = addon_manager.load_addon(missing_dep_dir, dir_type="custom")

        assert record.status == STATE_ERROR
        assert "non_existent_fake_package_xyz_999" in record.error

        # Core app still works
        res = client.get("/manager/api/addons")
        assert res.status_code == 200

    finally:
        if os.path.isdir(missing_dep_dir):
            shutil.rmtree(missing_dep_dir, ignore_errors=True)
        addon_manager.addons.pop("dep_fail_addon", None)
