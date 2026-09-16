"""
=============================================================================
Tests: In-App Self-Updater (core/updater/)
=============================================================================
Verifies:
  1. Semver ordering handles v-prefixes and triple-dot notation correctly.
  2. Network failure in check_for_updates() returns graceful non-throwing dict.
  3. Snapshot excludes data/ and venv/ directories.
  4. Health check subprocess returns True on exit code 0.
  5. Health check failure triggers rollback invocation.
=============================================================================
"""

import os
import sys
import json
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _touch(path: str):
    """Creates a file (and its parent dirs) with empty content."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('')


# ---------------------------------------------------------------------------
# 1. Semver Ordering Tests
# ---------------------------------------------------------------------------
class TestSemverOrdering(unittest.TestCase):
    """Verifies _parse_semver and _is_newer cover standard version edge cases."""

    def setUp(self):
        from core.updater.checker import _parse_semver, _is_newer
        self._parse = _parse_semver
        self._newer = _is_newer

    def test_v_prefix_stripped(self):
        self.assertEqual(self._parse("v1.0.9"), (1, 0, 9))

    def test_no_prefix(self):
        self.assertEqual(self._parse("1.0.10"), (1, 0, 10))

    def test_two_part_version(self):
        self.assertEqual(self._parse("v2.1"), (2, 1, 0))

    def test_newer_patch_version(self):
        self.assertTrue(self._newer("v1.0.10", "v1.0.9"))

    def test_newer_minor_version(self):
        self.assertTrue(self._newer("v1.1.0", "v1.0.9"))

    def test_same_version_not_newer(self):
        self.assertFalse(self._newer("v1.0.9", "v1.0.9"))

    def test_older_not_newer(self):
        self.assertFalse(self._newer("v1.0.8", "v1.0.9"))

    def test_major_bump(self):
        self.assertTrue(self._newer("v2.0.0", "v1.9.9"))


# ---------------------------------------------------------------------------
# 2. Network Failure — Graceful Degradation
# ---------------------------------------------------------------------------
class TestCheckForUpdatesNetworkFailure(unittest.TestCase):
    """check_for_updates() must never raise — all failures surface in 'error' key."""

    @patch("core.updater.checker.requests.get")
    def test_connection_error_returns_graceful_dict(self, mock_get):
        import requests as _req
        mock_get.side_effect = _req.exceptions.ConnectionError("No route to host")

        from core.updater.checker import check_for_updates
        result = check_for_updates()

        self.assertIsInstance(result, dict)
        self.assertFalse(result["available"])
        self.assertTrue(result["checked"])
        self.assertIsNotNone(result["error"])
        self.assertIn("internet", result["error"].lower())

    @patch("core.updater.checker.requests.get")
    def test_timeout_returns_graceful_dict(self, mock_get):
        import requests as _req
        mock_get.side_effect = _req.exceptions.Timeout("timeout")

        from core.updater.checker import check_for_updates
        result = check_for_updates()

        self.assertFalse(result["available"])
        self.assertIsNotNone(result["error"])
        self.assertIn("timed out", result["error"].lower())

    @patch("core.updater.checker.requests.get")
    def test_unexpected_exception_does_not_raise(self, mock_get):
        mock_get.side_effect = RuntimeError("Unknown catastrophic error")

        from core.updater.checker import check_for_updates
        # Must not raise — returns dict with error key
        result = check_for_updates()
        self.assertFalse(result["available"])
        self.assertIsNotNone(result["error"])


# ---------------------------------------------------------------------------
# 3. Snapshot Excludes data/ and venv/
# ---------------------------------------------------------------------------
class TestSnapshotExcludesDataAndVenv(unittest.TestCase):
    """Snapshot must copy source files but never include data/ or venv/ contents."""

    def setUp(self):
        self.base_dir = tempfile.mkdtemp(prefix="openpos_test_base_")
        self.snapshot_dir = tempfile.mkdtemp(prefix="openpos_test_snap_")

        # Create fake project structure
        _touch(os.path.join(self.base_dir, "app.py"))
        _touch(os.path.join(self.base_dir, "run.py"))
        _touch(os.path.join(self.base_dir, "core", "config.py"))
        _touch(os.path.join(self.base_dir, "manager", "routes.py"))

        # Files that MUST be excluded
        _touch(os.path.join(self.base_dir, "data", "config", ".env"))
        _touch(os.path.join(self.base_dir, "data", "db", "pos_store.db"))
        _touch(os.path.join(self.base_dir, "venv", "Scripts", "python.exe"))
        _touch(os.path.join(self.base_dir, ".git", "HEAD"))

    def tearDown(self):
        shutil.rmtree(self.base_dir, ignore_errors=True)
        shutil.rmtree(self.snapshot_dir, ignore_errors=True)

    def test_snapshot_excludes_data_and_venv(self):
        from core.updater.installer import create_snapshot, _should_exclude

        # Verify exclusion logic directly
        self.assertTrue(_should_exclude("data/config/.env"))
        self.assertTrue(_should_exclude("venv/Scripts/python.exe"))
        self.assertTrue(_should_exclude(".git/HEAD"))
        self.assertFalse(_should_exclude("core/config.py"))
        self.assertFalse(_should_exclude("app.py"))
        self.assertFalse(_should_exclude("manager/routes.py"))

    def test_snapshot_counts_only_core_files(self):
        from core.updater import installer as inst_mod
        from core.updater.installer import create_snapshot

        # Temporarily patch BASE_DIR inside installer to use our temp dir
        original_base = inst_mod.Config.BASE_DIR
        inst_mod.Config.BASE_DIR = self.base_dir

        try:
            result = create_snapshot(snapshot_dir=self.snapshot_dir)
            self.assertTrue(result["success"], msg=result.get("error"))

            # Confirm data/ files NOT in snapshot
            data_env = os.path.join(self.snapshot_dir, "data", "config", ".env")
            self.assertFalse(os.path.isfile(data_env), "data/ should not be snapshotted")

            # Confirm core files ARE in snapshot
            app_py = os.path.join(self.snapshot_dir, "app.py")
            self.assertTrue(os.path.isfile(app_py), "app.py should be in snapshot")
        finally:
            inst_mod.Config.BASE_DIR = original_base


# ---------------------------------------------------------------------------
# 4. Health Check — Pass Case
# ---------------------------------------------------------------------------
class TestHealthCheckPass(unittest.TestCase):
    """run_health_check() returns True when subprocess exits with code 0 and HEALTH_OK."""

    @patch("core.updater.installer.subprocess.run")
    def test_health_check_pass(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "HEALTH_OK\n"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        from core.updater.installer import run_health_check
        result = run_health_check()
        self.assertTrue(result)

    @patch("core.updater.installer.subprocess.run")
    def test_health_check_fail_bad_exit_code(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "ImportError: cannot import name 'create_app'"
        mock_run.return_value = mock_proc

        from core.updater.installer import run_health_check
        result = run_health_check()
        self.assertFalse(result)

    @patch("core.updater.installer.subprocess.run")
    def test_health_check_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="python", timeout=20)

        from core.updater.installer import run_health_check
        result = run_health_check()
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# 5. Health Check Failure Triggers Rollback
# ---------------------------------------------------------------------------
class TestHealthCheckFailureTriggerRollback(unittest.TestCase):
    """install_update() must call rollback() if run_health_check() returns False."""

    @patch("core.updater.installer.rollback")
    @patch("core.updater.installer.run_health_check", return_value=False)
    @patch("core.updater.installer.apply_update", return_value={"success": True, "message": "Applied."})
    @patch("core.updater.installer.create_snapshot", return_value={
        "success": True,
        "snapshot_path": "/tmp/fake_snapshot",
        "files_count": 42,
        "error": None
    })
    def test_failed_health_check_invokes_rollback(
        self,
        mock_snapshot,
        mock_apply,
        mock_health,
        mock_rollback,
    ):
        mock_rollback.return_value = {"success": True, "message": "Rollback OK."}

        from core.updater.installer import install_update
        result = install_update("https://example.com/fake.zip")

        self.assertFalse(result["success"])
        self.assertTrue(result["rolled_back"])
        mock_rollback.assert_called_once_with("/tmp/fake_snapshot")

    @patch("core.updater.installer.rollback")
    @patch("core.updater.installer.run_health_check", return_value=True)
    @patch("core.updater.installer.apply_update", return_value={"success": True, "message": "Applied."})
    @patch("core.updater.installer.create_snapshot", return_value={
        "success": True,
        "snapshot_path": "/tmp/fake_snapshot",
        "files_count": 42,
        "error": None
    })
    def test_successful_health_check_skips_rollback(
        self,
        mock_snapshot,
        mock_apply,
        mock_health,
        mock_rollback,
    ):
        from core.updater.installer import install_update
        result = install_update("https://example.com/fake.zip")

        self.assertTrue(result["success"])
        self.assertFalse(result["rolled_back"])
        mock_rollback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
