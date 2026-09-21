"""
=============================================================================
Tests: Schema-Driven Addon Configuration Subsystem & Version Polling
=============================================================================
Verifies:
  1. GET /api/addons/<id>/config returns schema and default/saved values.
  2. POST /api/addons/<id>/config validates fields, persists to data/config/addons/<id>.json.
  3. Schema validation rejects invalid numbers, out-of-range values, and bad select options.
  4. Active addon module's on_config_updated hook is invoked.
  5. GET /api/addons/updates returns version polling map.
=============================================================================
"""

import os
import json
import pytest
from app import create_app
from core.config import Config
from core.addons.loader import addon_manager, AddonRecord, STATE_ACTIVE
from core.addons.catalog import check_addon_updates


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def configured_test_addon(tmp_path, monkeypatch):
    """Sets up an addon with config_schema.json in a test directory."""
    addons_dir = tmp_path / "custom_addons"
    addons_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Config, "CUSTOM_ADDONS_DIR", str(addons_dir))

    config_storage_dir = tmp_path / "config" / "addons"
    config_storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Config, "ADDONS_CONFIG_DIR", str(config_storage_dir))
    monkeypatch.setattr(Config, "CONFIG_DIR", str(tmp_path / "config"))

    test_addon_dir = addons_dir / "test_schema_addon"
    test_addon_dir.mkdir()

    manifest = {
        "id": "test_schema_addon",
        "name": "Test Schema Addon",
        "version": "1.0.0",
        "entrypoint": "plugin.py",
        "repo_url": "https://github.com/Cave404/Test-Addon"
    }
    with open(test_addon_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    schema = {
        "title": "Test Addon Config",
        "fields": [
            {
                "name": "api_token",
                "label": "API Token",
                "type": "secret",
                "default": "default-token"
            },
            {
                "name": "markup_percent",
                "label": "Markup (%)",
                "type": "number",
                "default": 10,
                "min": 0,
                "max": 100
            },
            {
                "name": "auto_print",
                "label": "Auto Print",
                "type": "boolean",
                "default": True
            },
            {
                "name": "market_feed",
                "label": "Market Feed",
                "type": "select",
                "default": "standard",
                "options": [
                    {"value": "standard", "label": "Standard Feed"},
                    {"value": "premium", "label": "Premium Feed"}
                ]
            }
        ]
    }
    with open(test_addon_dir / "config_schema.json", "w", encoding="utf-8") as f:
        json.dump(schema, f)

    # Plugin with hook tracking
    plugin_py = """
updated_configs = []

def on_config_updated(cfg):
    updated_configs.append(cfg)
    return True
"""
    with open(test_addon_dir / "plugin.py", "w", encoding="utf-8") as f:
        f.write(plugin_py)

    # Register in addon_manager
    rec = addon_manager.load_addon(str(test_addon_dir), dir_type="custom")
    rec.status = STATE_ACTIVE
    return rec


def test_get_addon_config_schema_and_defaults(client, configured_test_addon):
    """GET /api/addons/<id>/config returns schema and default values."""
    res = client.get("/api/addons/test_schema_addon/config")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["addon_id"] == "test_schema_addon"
    assert "schema" in data
    assert len(data["schema"]["fields"]) == 4
    assert data["values"]["api_token"] == "default-token"
    assert data["values"]["markup_percent"] == 10
    assert data["values"]["auto_print"] is True
    assert data["values"]["market_feed"] == "standard"


def test_post_addon_config_persists_and_invokes_hook(client, configured_test_addon):
    """POST /api/addons/<id>/config validates, persists, and triggers on_config_updated."""
    payload = {
        "api_token": "secret_abc_123",
        "markup_percent": 25,
        "auto_print": False,
        "market_feed": "premium"
    }
    res = client.post("/api/addons/test_schema_addon/config", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["values"]["markup_percent"] == 25
    assert data["values"]["auto_print"] is False

    # Verify persisted on disk
    val_path = os.path.join(Config.ADDONS_CONFIG_DIR, "test_schema_addon.json")
    assert os.path.isfile(val_path)
    with open(val_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["api_token"] == "secret_abc_123"
    assert saved["markup_percent"] == 25
    assert saved["auto_print"] is False
    assert saved["market_feed"] == "premium"

    # Verify on_config_updated hook ran on active module
    assert len(configured_test_addon.module.updated_configs) > 0
    assert configured_test_addon.module.updated_configs[-1]["markup_percent"] == 25


def test_post_addon_config_validation_rejection(client, configured_test_addon):
    """Validates that out-of-range numbers and invalid select choices are rejected."""
    # Out of range (> 100)
    bad_number = {"markup_percent": 150}
    res1 = client.post("/api/addons/test_schema_addon/config", json=bad_number)
    assert res1.status_code == 400
    assert "at most 100" in res1.get_json()["error"]

    # Invalid select option
    bad_select = {"market_feed": "invalid_feed"}
    res2 = client.post("/api/addons/test_schema_addon/config", json=bad_select)
    assert res2.status_code == 400
    assert "Invalid choice" in res2.get_json()["error"]


def test_get_addon_updates_endpoint(client, monkeypatch):
    """GET /api/addons/updates returns status map."""
    monkeypatch.setattr("core.addons.catalog.check_addon_updates", lambda: {
        "tcg_pos": {
            "has_update": True,
            "installed_version": "1.0.0",
            "latest_version": "1.0.1",
            "download_url": "https://example.com/tcg_pos.zip"
        }
    })
    res = client.get("/api/addons/updates")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "tcg_pos" in data["updates"]
    assert data["updates"]["tcg_pos"]["has_update"] is True
    assert data["updates"]["tcg_pos"]["latest_version"] == "1.0.1"
