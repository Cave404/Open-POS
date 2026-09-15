"""
Unit & Integration Tests for Open-POS v1.0.8 Features:
1. Version Milestone Bump to v1.0.8
2. Remote Addon Catalog Engine & 6-Hour Cache TTL
3. Resilient Network Fetching & Offline Fallback
4. Network Downloader & Unpack Pipeline (data/custom_addons/<addon_id>/)
5. Automated Database Migrations on Install (schema_sqlite.sql / schema_postgres.sql)
6. Addon Manager UI: "Online Catalog" Tab & Dynamic Installation
7. Setup Wizard Step 5 (Optional Addons) & Step 7 Finalizing
"""

import io
import json
import os
import time
import zipfile
import pytest
from unittest.mock import patch, MagicMock
import requests

from app import create_app
from core.config import Config
from core.addons import addon_manager
from core.addons.catalog import fetch_catalog, get_catalog_item, is_compatible, parse_version, _get_cache_path
from core.addons.installer import install_remote_addon
from core.db import get_db_connection


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ============================================================================
# 1. Milestone Versioning (v1.0.8)
# ============================================================================

def test_v108_version_milestone(client):
    """Asserts that Config.VERSION and API credits strictly reflect v1.0.8."""
    assert Config.VERSION == "v1.0.8"

    res_credits = client.get("/api/system/credits")
    assert res_credits.status_code == 200
    assert res_credits.get_json()["version"] == "v1.0.8"

    # Verify templates render v1.0.8
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
        assert "v1.0.8" in res.get_data(as_text=True), f"Route {route} missing v1.0.8 badge"


# ============================================================================
# 2. Remote Addon Catalog Specification & Caching
# ============================================================================

def test_catalog_version_parser_and_compatibility():
    """Asserts version parsing and semver compatibility checks."""
    assert parse_version("v1.0.8") == (1, 0, 8)
    assert parse_version("1.2") == (1, 2, 0)
    assert parse_version("2.0.1") == (2, 0, 1)

    assert is_compatible("1.0.0", "v1.0.8") is True
    assert is_compatible("1.0.8", "v1.0.8") is True
    assert is_compatible("1.0.9", "v1.0.8") is False
    assert is_compatible("2.0.0", "v1.0.8") is False


def test_catalog_caching_and_ttl(tmp_path, monkeypatch):
    """Asserts that fetch_catalog reads from cache if younger than 6 hours."""
    mock_catalog = [
        {
            "id": "tcg_pos",
            "name": "TCG POS & Singles Engine",
            "version": "1.0.0",
            "author": "Open-POS Community",
            "description": "Inventory, buylist trade-in calculator, and singles sales.",
            "category": "Desktop_Apps",
            "download_url": "https://example.com/tcg_pos.zip",
            "requires_db": True,
            "min_core_version": "1.0.0"
        }
    ]

    cache_file = _get_cache_path()
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(mock_catalog, f)

    # Calling fetch_catalog without force_refresh should hit cache without network requests
    with patch("requests.get") as mock_get:
        catalog = fetch_catalog(force_refresh=False)
        assert len(catalog) == 1
        assert catalog[0]["id"] == "tcg_pos"
        mock_get.assert_not_called()

    # Calling with force_refresh=True should call requests.get
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_catalog
    with patch("requests.get", return_value=mock_response) as mock_get:
        catalog_refreshed = fetch_catalog(force_refresh=True)
        assert len(catalog_refreshed) == 1
        mock_get.assert_called_once()


def test_catalog_offline_resilience(tmp_path, monkeypatch):
    """Asserts that network failures, timeouts, and offline status gracefully return cached data or []."""
    # 1. Stale cache fallback when network fails
    cache_file = _get_cache_path()
    stale_data = [{"id": "cached_addon", "name": "Cached Addon"}]
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(stale_data, f)

    with patch("requests.get", side_effect=requests.RequestException("DNS lookup failed")):
        result = fetch_catalog(force_refresh=True)
        assert len(result) == 1
        assert result[0]["id"] == "cached_addon"

    # 2. When no cache exists and network fails, returns empty list without raising exception
    if os.path.isfile(cache_file):
        os.remove(cache_file)

    with patch("requests.get", side_effect=requests.Timeout("Connection timed out")):
        result_empty = fetch_catalog(force_refresh=True)
        assert result_empty == []


# ============================================================================
# 3. Network Downloader & Unpack Pipeline
# ============================================================================

def test_installer_min_core_version_guard():
    """Asserts that an addon requiring a higher core version is rejected."""
    mock_item = {
        "id": "future_addon",
        "name": "Future Addon",
        "version": "2.0.0",
        "min_core_version": "9.9.9",
        "download_url": "https://example.com/future.zip"
    }
    with patch("core.addons.installer.get_catalog_item", return_value=mock_item):
        result = install_remote_addon("future_addon")
        assert result["status"] == "error"
        assert "requires OpenPOS 9.9.9 or higher" in result["message"]


def test_installer_pipeline_with_migrations_and_hot_mount(tmp_path):
    """Asserts that remote addon downloads, validates, migrates, and hot-mounts without restart."""
    addon_id = "test_remote_plugin"
    manifest = {
        "id": addon_id,
        "name": "Test Remote Plugin",
        "version": "1.0.0",
        "entrypoint": "plugin.py",
        "author": "Community Lab",
        "description": "Modular testing extension.",
        "requires_db": True,
        "min_core_version": "1.0.0"
    }

    entrypoint_code = """
from flask import Blueprint, jsonify

blueprint = Blueprint('test_remote_plugin', __name__)

@blueprint.route('/ping')
def ping():
    return jsonify({"status": "pong", "installed": True})
"""

    migration_sql = """
CREATE TABLE IF NOT EXISTS test_remote_plugin_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO test_remote_plugin_ledger (item_name) VALUES ('Initial Seed Item');
"""

    # Build mock zip in memory
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{addon_id}/manifest.json", json.dumps(manifest))
        zf.writestr(f"{addon_id}/plugin.py", entrypoint_code)
        zf.writestr(f"{addon_id}/migrations/schema_sqlite.sql", migration_sql)
    zip_bytes = zip_buf.getvalue()

    mock_catalog_item = {
        "id": addon_id,
        "name": "Test Remote Plugin",
        "version": "1.0.0",
        "min_core_version": "1.0.0",
        "requires_db": True,
        "download_url": "https://example.com/addons/test_remote_plugin.zip"
    }

    # Mock catalog and download stream
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_content.return_value = [zip_bytes]

    with patch("core.addons.installer.get_catalog_item", return_value=mock_catalog_item), \
         patch("requests.get", return_value=mock_resp):
        res = install_remote_addon(addon_id)
        assert res["status"] == "success"
        assert addon_id in res["message"]

    # Verify extracted into data/custom_addons/<addon_id>/
    custom_dir = Config.CUSTOM_ADDONS_DIR
    installed_dir = os.path.join(custom_dir, addon_id)
    assert os.path.isdir(installed_dir)
    assert os.path.isfile(os.path.join(installed_dir, "manifest.json"))
    assert os.path.isfile(os.path.join(installed_dir, "plugin.py"))

    # Verify database migration executed
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT item_name FROM test_remote_plugin_ledger")
        rows = cur.fetchall()
        assert len(rows) >= 1
        name = rows[0]["item_name"] if hasattr(rows[0], "__getitem__") and not isinstance(rows[0], tuple) else rows[0][0]
        assert name == "Initial Seed Item"

    # Verify hot-mounted in addon_manager
    rec = addon_manager.get_addon(addon_id)
    assert rec is not None
    assert rec["name"] == "Test Remote Plugin"
    assert rec["dir_type"] == "custom"


# ============================================================================
# 4. REST API Endpoints
# ============================================================================

def test_api_addons_catalog_endpoint(client):
    """Asserts that GET /api/addons/catalog returns catalog items enriched with status."""
    mock_catalog = [
        {
            "id": "sample_ext",
            "name": "Sample Extension",
            "version": "1.0.0",
            "author": "Tester",
            "description": "Sample catalog item",
            "min_core_version": "1.0.0",
            "download_url": "https://example.com/sample.zip"
        }
    ]

    with patch("core.addons.catalog.fetch_catalog", return_value=mock_catalog):
        res = client.get("/api/addons/catalog")
        assert res.status_code == 200
        items = res.get_json()
        assert len(items) >= 1
        first = items[0]
        assert first["id"] == "sample_ext"
        assert "is_installed" in first
        assert "is_compatible" in first
        assert first["is_compatible"] is True


def test_api_addons_install_remote_endpoint(client):
    """Asserts that POST /api/addons/install_remote handles requests and errors."""
    # 1. Missing addon_id
    res_missing = client.post("/api/addons/install_remote", json={})
    assert res_missing.status_code == 400

    # 2. Valid invocation
    with patch("core.addons.installer.install_remote_addon", return_value={"status": "success", "message": "Installed successfully"}):
        res_ok = client.post("/api/addons/install_remote", json={"addon_id": "test_ext"})
        assert res_ok.status_code == 200
        assert res_ok.get_json()["status"] == "success"


# ============================================================================
# 5. UI Views & Setup Wizard Step 5
# ============================================================================

def test_addons_html_contains_catalog_tab(client):
    """Asserts that addons.html contains the Segmented Control and Catalog view container."""
    res = client.get("/manager/addons")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "tabInstalledAddons" in html
    assert "tabAddonCatalog" in html
    assert "installedAddonsView" in html
    assert "catalogAddonsView" in html
    assert "catalogSearchInput" in html
    assert "catalogGrid" in html
    assert "installRemoteAddon" in html


def test_setup_wizard_step5_optional_addons(client, monkeypatch):
    """Asserts that setup_wizard.html provides Step 5 for optional addons in 7-step wizard."""
    monkeypatch.setattr("manager.routes.is_setup_complete", lambda: False)
    monkeypatch.setattr("manager.routes.check_existing_installation", lambda: {"exists": False, "has_password": False, "has_keys": False})

    res = client.get("/manager/setup")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # Stepper has 7 steps
    assert "stepIndicator5" in html
    assert "Optional Addons" in html
    assert "stepIndicator7" in html
    assert "Step 7 of 7 Complete" in html

    # Stage 5 elements
    assert 'id="stage5"' in html
    assert "Optional Integrations &amp; Addons" in html or "Optional Integrations & Addons" in html
    assert "wizardAddonsContainer" in html
    assert "loadWizardAddons" in html
    assert "Downloading and installing" in html
