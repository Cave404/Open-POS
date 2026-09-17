"""
Unit and Integration Tests for Addon Import Resolution, Hot-Updater,
Rollback Engine, and Centralized Logging Pipeline
"""

import os
import sys
import json
import shutil
import zipfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app import create_app
from core.config import Config
from core.logger import (
    setup_system_logger,
    get_system_logger,
    get_addon_logger,
    install_global_excepthooks,
    log_event,
    read_system_logs,
    read_addon_logs,
    SYSTEM_LOG,
    ADDONS_LOG
)
from core.addons.loader import addon_manager, load_single_addon, STATE_ACTIVE, STATE_ERROR
from core.addons.updater import (
    create_addon_snapshot,
    list_addon_snapshots,
    export_addon_state,
    restore_addon_state,
    update_addon,
    rollback_addon
)


@pytest.fixture
def app():
    application = create_app()
    application.config['TESTING'] = True
    return application


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def test_addon_direct_and_relative_import_resolution(app):
    """
    Asserts that dynamic sys.path injection resolves:
    1. Direct imports: `import routes`
    2. Relative imports: `from .routes import custom_var`
    without raising 'No module named routes' or parent package errors.
    """
    custom_dir = getattr(Config, 'CUSTOM_ADDONS_DIR', os.path.join(Config.DATA_DIR, 'custom_addons'))
    test_pkg_dir = Path(custom_dir) / "test_import_pkg"
    if test_pkg_dir.exists():
        shutil.rmtree(str(test_pkg_dir), ignore_errors=True)
    test_pkg_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Create manifest
        manifest = {
            "id": "test_import_pkg",
            "name": "Test Import Package",
            "version": "1.0.0",
            "entrypoint": "plugin.py"
        }
        with open(test_pkg_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        # Create routes.py inside the addon
        with open(test_pkg_dir / "routes.py", "w", encoding="utf-8") as f:
            f.write("SAMPLE_CONST = 'ROUTES_OK'\n")

        # Create plugin.py with both direct and relative imports
        with open(test_pkg_dir / "plugin.py", "w", encoding="utf-8") as f:
            f.write(
                "from flask import Blueprint, jsonify\n"
                "import routes\n"  # Direct module import
                "from .routes import SAMPLE_CONST\n"  # Relative import
                "blueprint = Blueprint('test_import_pkg', __name__)\n"
                "@blueprint.route('/check')\n"
                "def check():\n"
                "    return jsonify({'direct': routes.SAMPLE_CONST, 'rel': SAMPLE_CONST})\n"
            )

        # Load addon into manager with app
        record = load_single_addon("test_import_pkg", app=app)
        assert record.status == STATE_ACTIVE, f"Addon failed to load: {record.error}"
        assert record.module is not None
        assert record.module.SAMPLE_CONST == "ROUTES_OK"

        # Verify route execution through Flask test client
        with app.test_client() as client:
            res = client.get("/addons/test_import_pkg/check")
            assert res.status_code == 200
            data = res.get_json()
            assert data["direct"] == "ROUTES_OK"
            assert data["rel"] == "ROUTES_OK"

    finally:
        if test_pkg_dir.exists():
            shutil.rmtree(str(test_pkg_dir), ignore_errors=True)
        addon_manager.addons.pop("test_import_pkg", None)


def test_centralized_logging_system():
    """
    Asserts rotating file handlers exist for both system and addons logs,
    and events are formatted and read correctly.
    """
    setup_system_logger()
    sys_log = get_system_logger()
    addon_log = get_addon_logger()

    # Verify log destinations exist
    assert SYSTEM_LOG.parent.is_dir()

    # Write test events
    test_token = f"TOKEN_{os.urandom(4).hex()}"
    log_event("INFO", f"Central system event {test_token}", "DIAGNOSTICS")
    addon_log.info(f"Addon subsystem event {test_token}")

    assert SYSTEM_LOG.is_file()
    assert ADDONS_LOG.is_file()

    # Read back through readers
    sys_records = read_system_logs(limit=50)
    addon_records = read_addon_logs(limit=50)

    found_sys = any(test_token in r.get("message", "") for r in sys_records)
    found_addon = any(test_token in r.get("message", "") for r in addon_records)

    assert found_sys, "System logger event was not written or parsed properly"
    assert found_addon, "Addon logger event was not written or parsed properly"


def test_global_excepthooks():
    """Asserts that install_global_excepthooks installs sys.excepthook that logs critical errors."""
    install_global_excepthooks()
    assert callable(sys.excepthook)

    # Simulate an uncaught exception
    try:
        raise ValueError("Simulated uncaught exception for logging test")
    except ValueError as e:
        exc_type, exc_val, exc_tb = sys.exc_info()
        sys.excepthook(exc_type, exc_val, exc_tb)

    sys_records = read_system_logs(limit=20)
    assert any("Simulated uncaught exception" in r.get("message", "") or "Uncaught Global Exception" in r.get("message", "") for r in sys_records)


def test_state_persistence_lifecycle(app):
    """
    Asserts export_state() serializes state to data/cache/addon_state_<addon_id>.json
    and restore_state() restores it upon reloading.
    """
    custom_dir = getattr(Config, 'CUSTOM_ADDONS_DIR', os.path.join(Config.DATA_DIR, 'custom_addons'))
    addon_dir = Path(custom_dir) / "test_state_addon"
    if addon_dir.exists():
        shutil.rmtree(str(addon_dir), ignore_errors=True)
    addon_dir.mkdir(parents=True, exist_ok=True)

    try:
        manifest = {
            "id": "test_state_addon",
            "name": "Test State Plugin",
            "version": "1.0.0",
            "entrypoint": "plugin.py"
        }
        with open(addon_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        # Addon that tracks in-memory state
        with open(addon_dir / "plugin.py", "w", encoding="utf-8") as f:
            f.write(
                "_STATE = {'cart': ['item_1', 'item_2'], 'counter': 99}\n"
                "def export_state():\n"
                "    return _STATE\n"
                "def restore_state(state):\n"
                "    global _STATE\n"
                "    _STATE = state\n"
                "    return True\n"
            )

        record = load_single_addon("test_state_addon", app=app)
        assert record.status == STATE_ACTIVE

        # Test export
        exported = export_addon_state("test_state_addon")
        assert exported == {'cart': ['item_1', 'item_2'], 'counter': 99}

        cache_file = Path(getattr(Config, 'CACHE_DIR', os.path.join(Config.DATA_DIR, 'cache'))) / "addon_state_test_state_addon.json"
        assert cache_file.is_file()

        # Reset in-memory state in module
        record.module._STATE = {}
        assert record.module._STATE == {}

        # Test restore
        restored = restore_addon_state("test_state_addon", record.module)
        assert restored is True
        assert record.module._STATE == {'cart': ['item_1', 'item_2'], 'counter': 99}

    finally:
        if addon_dir.exists():
            shutil.rmtree(str(addon_dir), ignore_errors=True)
        addon_manager.addons.pop("test_state_addon", None)


def test_snapshot_creation_and_listing():
    """
    Asserts create_addon_snapshot() creates a snapshot folder in data/backups/addons/
    and list_addon_snapshots() retrieves it with metadata.
    """
    custom_dir = getattr(Config, 'CUSTOM_ADDONS_DIR', os.path.join(Config.DATA_DIR, 'custom_addons'))
    addon_dir = Path(custom_dir) / "test_snapshot_addon"
    if addon_dir.exists():
        shutil.rmtree(str(addon_dir), ignore_errors=True)
    addon_dir.mkdir(parents=True, exist_ok=True)

    try:
        manifest = {
            "id": "test_snapshot_addon",
            "name": "Test Snapshot Plugin",
            "version": "1.2.3",
            "entrypoint": "plugin.py"
        }
        with open(addon_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        with open(addon_dir / "plugin.py", "w", encoding="utf-8") as f:
            f.write("# Snapshot plugin test\n")

        snapshot_dir = create_addon_snapshot("test_snapshot_addon", current_version="1.2.3")
        assert snapshot_dir.is_dir()
        assert (snapshot_dir / "snapshot_meta.json").is_file()
        assert (snapshot_dir / "manifest.json").is_file()

        snapshots = list_addon_snapshots("test_snapshot_addon")
        assert len(snapshots) >= 1
        latest = snapshots[0]
        assert latest["addon_id"] == "test_snapshot_addon"
        assert latest["version"] == "1.2.3"
        assert snapshot_dir.name == latest["snapshot_id"]

    finally:
        if addon_dir.exists():
            shutil.rmtree(str(addon_dir), ignore_errors=True)


def test_update_addon_auto_rollback_on_failure(app):
    """
    CRITICAL SAFETY REQUIREMENT:
    Asserts that if an addon update fails during module initialization
    (e.g., syntax error or unhandled exception in new version),
    the updater automatically catches the failure, logs it in openpos_addons.log,
    restores the previous working snapshot, and reloads the original version.
    """
    custom_dir = getattr(Config, 'CUSTOM_ADDONS_DIR', os.path.join(Config.DATA_DIR, 'custom_addons'))
    addon_dir = Path(custom_dir) / "test_flaky_addon"
    if addon_dir.exists():
        shutil.rmtree(str(addon_dir), ignore_errors=True)
    addon_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Establish Working v1.0.0
        v1_manifest = {
            "id": "test_flaky_addon",
            "name": "Flaky Test Addon",
            "version": "1.0.0",
            "entrypoint": "plugin.py"
        }
        with open(addon_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(v1_manifest, f)
        with open(addon_dir / "plugin.py", "w", encoding="utf-8") as f:
            f.write(
                "from flask import Blueprint\n"
                "blueprint = Blueprint('test_flaky', __name__)\n"
                "status_str = 'v1_working'\n"
            )

        record = load_single_addon("test_flaky_addon", app=app)
        assert record.status == STATE_ACTIVE
        assert record.module.status_str == "v1_working"

        # 2. Package a broken v2.0.0 into a zip file
        cache_dir = Path(getattr(Config, 'CACHE_DIR', os.path.join(Config.DATA_DIR, 'cache')))
        cache_dir.mkdir(parents=True, exist_ok=True)
        broken_zip_path = cache_dir / "test_broken_update.zip"

        with zipfile.ZipFile(str(broken_zip_path), 'w') as zf:
            v2_manifest = {
                "id": "test_flaky_addon",
                "name": "Flaky Test Addon",
                "version": "2.0.0",
                "entrypoint": "plugin.py"
            }
            # Wrap in github-style root folder
            zf.writestr("test_flaky_addon-main/manifest.json", json.dumps(v2_manifest))
            zf.writestr("test_flaky_addon-main/plugin.py", "raise RuntimeError('Broken v2.0.0 initialization!')\n")

        # 3. Mock catalog and requests to return the broken zip
        mock_item = {
            "id": "test_flaky_addon",
            "name": "Flaky Test Addon",
            "version": "2.0.0",
            "download_url": "https://example.com/fake_broken_addon.zip"
        }

        with patch("core.addons.updater.get_catalog_item", return_value=mock_item):
            with patch("requests.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                with open(broken_zip_path, "rb") as f:
                    content = f.read()
                mock_resp.iter_content = lambda chunk_size: [content]
                mock_get.return_value = mock_resp

                # 4. Trigger update and verify auto-rollback exception
                with pytest.raises(RuntimeError) as exc_info:
                    update_addon("test_flaky_addon", app=app)

                assert "reverted to previous version" in str(exc_info.value)

        # 5. Verify the addon directory has been safely restored to v1.0.0
        with open(addon_dir / "manifest.json", "r", encoding="utf-8") as f:
            restored_mdata = json.load(f)
        assert restored_mdata["version"] == "1.0.0"

        # Re-verify loaded module state
        current_record = addon_manager.addons.get("test_flaky_addon")
        assert current_record.status == STATE_ACTIVE
        assert current_record.module.status_str == "v1_working"

        # Verify error logged in openpos_addons.log
        addon_logs = read_addon_logs(limit=20)
        assert any("initiating automated rollback" in l.get("message", "") or "Critical error updating addon" in l.get("message", "") for l in addon_logs)

    finally:
        if addon_dir.exists():
            shutil.rmtree(str(addon_dir), ignore_errors=True)
        if broken_zip_path.exists():
            broken_zip_path.unlink()
        addon_manager.addons.pop("test_flaky_addon", None)


def test_addon_manager_rest_endpoints(client):
    """
    Asserts REST API endpoints:
      - GET /api/addons/<id>/snapshots
      - POST /api/addons/<id>/rollback
      - GET /api/addons/logs
    """
    # 1. Addon logs endpoint
    res_logs = client.get("/api/addons/logs")
    assert res_logs.status_code == 200
    logs_data = res_logs.get_json()
    assert "logs" in logs_data
    assert isinstance(logs_data["logs"], list)

    # 2. Snapshots listing
    res_snaps = client.get("/api/addons/test_snapshot_addon/snapshots")
    assert res_snaps.status_code == 200
    snaps_data = res_snaps.get_json()
    assert isinstance(snaps_data, list)

    # 3. Rollback non-existent addon returns 400
    res_rb_fail = client.post("/api/addons/non_existent_addon_xyz/rollback", json={})
    assert res_rb_fail.status_code == 400
    assert "error" in res_rb_fail.get_json()["status"]
