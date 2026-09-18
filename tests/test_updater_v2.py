"""
=============================================================================
Tests: Core POS Auto-Updater, Changelog Inspector & Maintenance Scheduler
(tests/test_updater_v2.py)
=============================================================================
Verifies:
  1. Changelog parser buckets: Added, Changed, Fixed, Removed.
  2. 2-Hour cache mechanism in data/cache/update_status.json & update_check.json.
  3. Pre-update snapshot creation, exclusion guards (data/, venv/, .git/).
  4. Engine update apply, health check verification, and automatic rollback on failure.
  5. Maintenance scheduler preferences persistence & window calculation.
  6. Active cart idle guard during maintenance windows.
  7. System REST API endpoints (/api/system/update/*) and /manager/updates view.
=============================================================================
"""

import os
import sys
import json
import time
import shutil
import zipfile
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from core.config import Config
from core.updater.checker import (
    parse_markdown_changelog,
    check_for_system_updates,
    _parse_semver,
    _is_newer,
    UPDATE_CACHE_PATH,
    UPDATE_CHECK_CACHE_PATH
)
from core.updater.engine import apply_system_update, _log_to_updater_file
from core.updater.scheduler import (
    get_update_preferences,
    save_update_preferences,
    is_cart_idle,
    is_window_due,
    PREFERENCES_FILE
)


class TestChangelogParser(unittest.TestCase):
    """Verifies that release notes are categorized into Added, Changed, Fixed, Removed."""

    def test_parse_standard_markdown_changelog(self):
        body = """
        # Release Notes v1.1.0

        ### Added
        - Added hardware receipt printer auto-detection
        - Added store credit barcode scanner support

        ### Changed
        * Improved SQLite concurrency handling
        * Updated navigation sidebar aesthetics

        ### Fixed
        - Fixed split tender negative change calculation
        - Fixed customer loyalty lookup timeout

        ### Removed
        - Deprecated legacy XML catalog exporter
        """
        result = parse_markdown_changelog(body)
        self.assertEqual(len(result["added"]), 2)
        self.assertIn("Added hardware receipt printer auto-detection", result["added"])
        self.assertEqual(len(result["changed"]), 2)
        self.assertIn("Improved SQLite concurrency handling", result["changed"])
        self.assertEqual(len(result["fixed"]), 2)
        self.assertIn("Fixed split tender negative change calculation", result["fixed"])
        self.assertEqual(len(result["removed"]), 1)
        self.assertIn("Deprecated legacy XML catalog exporter", result["removed"])

    def test_parse_synonym_headers(self):
        body = """
        ## Features
        - New customer profile search modal

        ## Improvements
        - Faster cart recalculation

        ## Bug Fixes
        - Resolved tax rounding discrepancy

        ## Deprecated
        - Removed legacy v1 API endpoints
        """
        result = parse_markdown_changelog(body)
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(len(result["changed"]), 1)
        self.assertEqual(len(result["fixed"]), 1)
        self.assertEqual(len(result["removed"]), 1)

    def test_empty_or_malformed_body(self):
        self.assertEqual(
            parse_markdown_changelog(""),
            {"added": [], "changed": [], "fixed": [], "removed": []}
        )
        self.assertEqual(
            parse_markdown_changelog(None),
            {"added": [], "changed": [], "fixed": [], "removed": []}
        )


class TestUpdateCheckerAndCache(unittest.TestCase):
    """Verifies rate-limit caching and GitHub release querying."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.cache_file = os.path.join(self.test_dir, "update_status.json")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_semver_comparisons(self):
        self.assertTrue(_is_newer("v1.1.0", "v1.0.9"))
        self.assertTrue(_is_newer("v1.0.10", "v1.0.9"))
        self.assertTrue(_is_newer("v2.0.0", "v1.9.9"))
        self.assertFalse(_is_newer("v1.0.9", "v1.0.9"))
        self.assertFalse(_is_newer("v1.0.8", "v1.0.9"))

    @patch("core.updater.checker.requests.get")
    def test_check_for_system_updates_cache_hit(self, mock_get):
        now = datetime.now(timezone.utc).timestamp()
        cached_payload = {
            "cached_at": now,
            "data": {
                "checked": True,
                "update_available": True,
                "current_version": "v1.0.9",
                "latest_version": "v1.1.0",
                "release_name": "OpenPOS v1.1.0",
                "download_url": "https://example.com/release.zip",
                "changelog": {"added": ["Feature A"], "changed": [], "fixed": [], "removed": []},
                "error": None
            }
        }
        os.makedirs(os.path.dirname(UPDATE_CACHE_PATH), exist_ok=True)
        with open(UPDATE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cached_payload, f)

        # Should return cached data without invoking requests.get
        data = check_for_system_updates(force=False)
        self.assertEqual(data["latest_version"], "v1.1.0")
        mock_get.assert_not_called()

    @patch("core.updater.checker.requests.get")
    def test_check_for_system_updates_force_bypass(self, mock_get):
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {
            "tag_name": "v1.2.0",
            "name": "OpenPOS 1.2.0 Release",
            "published_at": "2026-09-18T00:00:00Z",
            "zipball_url": "https://example.com/v1.2.0.zip",
            "body": "### Added\n- Cloud Backup"
        }
        mock_get.return_value = mock_res

        data = check_for_system_updates(force=True)
        self.assertTrue(data["update_available"])
        self.assertEqual(data["latest_version"], "v1.2.0")
        mock_get.assert_called_once()


class TestEngineAtomicUpdateAndRollback(unittest.TestCase):
    """Tests pre-update snapshotting, archive unnesting, health check verification, and rollback."""

    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.base_dir = os.path.join(self.temp_root, "app_base")
        self.data_dir = os.path.join(self.base_dir, "data")
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

        # Create simulated app files
        os.makedirs(os.path.join(self.base_dir, "core"), exist_ok=True)
        with open(os.path.join(self.base_dir, "core", "test_file.py"), "w") as f:
            f.write("# Version 1.0.0 code\nORIGINAL = True\n")

        with open(os.path.join(self.base_dir, "app.py"), "w") as f:
            f.write("# App entrypoint\n")

        # Create protected data and venv files
        os.makedirs(os.path.join(self.data_dir, "db"), exist_ok=True)
        with open(os.path.join(self.data_dir, "db", "pos_sales.sqlite"), "w") as f:
            f.write("SQLITE_DATABASE_DATA_NEVER_OVERWRITE")

        os.makedirs(os.path.join(self.base_dir, "venv"), exist_ok=True)
        with open(os.path.join(self.base_dir, "venv", "pyvenv.cfg"), "w") as f:
            f.write("VENV_CONFIG")

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _create_mock_zip(self, new_code: str, is_nested: bool = True) -> str:
        zip_path = os.path.join(self.temp_root, "mock_release.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            prefix = "Cave404-Open-POS-abc123/" if is_nested else ""
            zf.writestr(f"{prefix}core/test_file.py", new_code)
            zf.writestr(f"{prefix}core/new_feature.py", "# New Feature Module\n")
            # Attacker/accidental file in data/ or venv/
            zf.writestr(f"{prefix}data/db/pos_sales.sqlite", "CORRUPTED_OVERWRITE_ATTEMPT")
            zf.writestr(f"{prefix}venv/pyvenv.cfg", "CORRUPTED_VENV")
        return zip_path

    @patch("core.updater.engine.Config")
    @patch("core.updater.engine.requests.get")
    @patch("core.updater.engine.subprocess.run")
    def test_apply_system_update_success(self, mock_subprocess, mock_requests_get, mock_config):
        mock_config.BASE_DIR = self.base_dir
        mock_config.DATA_DIR = self.data_dir
        mock_config.VERSION = "v1.0.9"

        # Mock release zip download
        zip_file = self._create_mock_zip("# Version 1.1.0 code\nUPGRADED = True\n", is_nested=True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raw = open(zip_file, "rb")
        mock_requests_get.return_value = mock_resp

        # Mock health check success
        mock_check = MagicMock()
        mock_check.returncode = 0
        mock_check.stdout = "HEALTHY"
        mock_subprocess.return_value = mock_check

        success = apply_system_update("https://example.com/release.zip", "v1.1.0")
        self.assertTrue(success)

        # Verify core file was updated
        with open(os.path.join(self.base_dir, "core", "test_file.py"), "r") as f:
            content = f.read()
        self.assertIn("UPGRADED = True", content)

        # Verify data/ was strictly protected
        with open(os.path.join(self.data_dir, "db", "pos_sales.sqlite"), "r") as f:
            data_content = f.read()
        self.assertEqual(data_content, "SQLITE_DATABASE_DATA_NEVER_OVERWRITE")

        # Verify venv/ was strictly protected
        with open(os.path.join(self.base_dir, "venv", "pyvenv.cfg"), "r") as f:
            venv_content = f.read()
        self.assertEqual(venv_content, "VENV_CONFIG")

    @patch("core.updater.engine.Config")
    @patch("core.updater.engine.requests.get")
    @patch("core.updater.engine.subprocess.run")
    def test_apply_system_update_health_failure_triggers_rollback(self, mock_subprocess, mock_requests_get, mock_config):
        mock_config.BASE_DIR = self.base_dir
        mock_config.DATA_DIR = self.data_dir
        mock_config.VERSION = "v1.0.9"

        # Create zip with broken code
        zip_file = self._create_mock_zip("SYNTAX_ERROR_BROKEN_CODE = ((\n", is_nested=True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raw = open(zip_file, "rb")
        mock_requests_get.return_value = mock_resp

        # Health check fails
        mock_check = MagicMock()
        mock_check.returncode = 1
        mock_check.stdout = ""
        mock_check.stderr = "SyntaxError: unexpected EOF"
        mock_subprocess.return_value = mock_check

        success = apply_system_update("https://example.com/release.zip", "v1.1.0")
        self.assertFalse(success)

        # Verify automatic rollback restored original code
        with open(os.path.join(self.base_dir, "core", "test_file.py"), "r") as f:
            content = f.read()
        self.assertIn("ORIGINAL = True", content)

        # Verify updater.log recorded the rollback
        log_file = os.path.join(self.data_dir, "logs", "updater.log")
        self.assertTrue(os.path.exists(log_file))
        with open(log_file, "r", encoding="utf-8") as f:
            logs = f.read()
        self.assertIn("Automatic rollback completed successfully", logs)


class TestMaintenanceScheduler(unittest.TestCase):
    """Verifies update preferences management, cart idle checking, and maintenance window calculations."""

    def test_preferences_save_and_get(self):
        new_prefs = {
            "auto_check": False,
            "check_interval_hours": 12,
            "auto_install": True,
            "schedule_day": "wednesday",
            "schedule_time": "04:30",
            "require_empty_cart": True
        }
        saved = save_update_preferences(new_prefs)
        self.assertEqual(saved["schedule_day"], "wednesday")
        self.assertEqual(saved["schedule_time"], "04:30")
        self.assertEqual(saved["check_interval_hours"], 12)
        self.assertFalse(saved["auto_check"])
        self.assertTrue(saved["auto_install"])

        loaded = get_update_preferences()
        self.assertEqual(loaded["schedule_day"], "wednesday")
        self.assertEqual(loaded["schedule_time"], "04:30")

    def test_is_cart_idle_check(self):
        from core.services.cart_service import CartService
        svc = CartService.get_instance()

        # Ensure empty
        with svc._lock:
            svc._carts.clear()

        self.assertTrue(is_cart_idle())

        # Add active cart with item
        with svc._lock:
            svc._carts["test_cart"] = {
                "cart_id": "test_cart",
                "items": [{"item_id": "1", "name": "Item A", "price": 10.0, "quantity": 1}],
                "grand_total": 10.0
            }

        self.assertFalse(is_cart_idle())

        # Clear cart back to idle
        with svc._lock:
            svc._carts.clear()
        self.assertTrue(is_cart_idle())

    def test_is_window_due_evaluation(self):
        prefs = {
            "schedule_day": "monday",
            "schedule_time": "03:00"
        }
        # Matching Monday at 03:00
        matching_dt = datetime(2026, 9, 21, 3, 0, 0)  # Sep 21 2026 is Monday
        self.assertTrue(is_window_due(prefs, now=matching_dt))

        # Repeated call in same minute must return False (deduplication)
        self.assertFalse(is_window_due(prefs, now=matching_dt))

        # Wrong day
        tuesday_dt = datetime(2026, 9, 22, 3, 0, 0)
        self.assertFalse(is_window_due(prefs, now=tuesday_dt))

        # Wrong time
        wrong_time_dt = datetime(2026, 9, 21, 3, 1, 0)
        self.assertFalse(is_window_due(prefs, now=wrong_time_dt))


class TestSystemRoutes(unittest.TestCase):
    """Verifies REST endpoints and manager update views."""

    def setUp(self):
        from app import create_app
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_get_update_status_endpoint(self):
        res = self.client.get('/api/system/update/status')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("current_version", data)
        self.assertIn("preferences", data)
        self.assertIn("cart_idle", data)

    @patch("core.routes.system_routes.check_for_system_updates")
    def test_post_check_now_endpoint(self, mock_checker):
        mock_checker.return_value = {
            "update_available": True,
            "latest_version": "v1.2.0",
            "release_name": "v1.2.0",
            "published_at": "2026-09-18",
            "changelog": {"added": ["New Feature"], "changed": [], "fixed": [], "removed": []},
            "download_url": "https://example.com/dl.zip"
        }
        res = self.client.post('/api/system/update/check-now')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["update_available"])
        self.assertEqual(data["latest_version"], "v1.2.0")

    def test_post_preferences_endpoint(self):
        payload = {
            "auto_check": True,
            "check_interval_hours": 4,
            "auto_install": False,
            "schedule_day": "friday",
            "schedule_time": "02:00",
            "require_empty_cart": True
        }
        res = self.client.post('/api/system/update/preferences', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["preferences"]["schedule_day"], "friday")
        self.assertEqual(data["preferences"]["schedule_time"], "02:00")

    def test_manager_updates_view(self):
        res = self.client.get('/manager/updates')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Core Auto-Updater &amp; Maintenance", html)
        self.assertIn("Active Version", html)
        self.assertIn("Maintenance Window &amp; Scheduler Preferences", html)
        self.assertIn("Python Environment &amp; Installed Dependencies", html)

    @patch("core.routes.system_routes.apply_system_update")
    @patch("core.routes.system_routes.restart_openpos")
    def test_post_apply_endpoint_success(self, mock_restart, mock_apply):
        mock_apply.return_value = True
        payload = {
            "download_url": "https://example.com/update.zip",
            "new_version": "v1.2.0"
        }
        res = self.client.post('/api/system/update/apply', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["new_version"], "v1.2.0")
        mock_apply.assert_called_once_with("https://example.com/update.zip", "v1.2.0")

    @patch("core.routes.system_routes.check_for_system_updates")
    def test_post_apply_endpoint_no_url(self, mock_check):
        mock_check.return_value = {"download_url": None}
        res = self.client.post('/api/system/update/apply', json={})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])


if __name__ == "__main__":
    unittest.main()
