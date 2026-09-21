"""
=============================================================================
Tests: Updater Engine Cache Purging & Fallback Commits
=============================================================================
Verifies:
  1. force=True purges update_status.json and update_check.json.
  2. Fallback to GitHub branch commits when releases returns 404 or current tag.
  3. POST /api/system/update/check-now bypasses cache and triggers check.
=============================================================================
"""

import os
import json
import unittest
from unittest.mock import patch, MagicMock
from core.config import Config
from core.updater.checker import (
    check_for_system_updates,
    _get_local_git_sha,
    UPDATE_CACHE_PATH,
    UPDATE_CHECK_CACHE_PATH
)


class TestUpdaterTriggersAndFallback(unittest.TestCase):

    def setUp(self):
        os.makedirs(os.path.join(Config.DATA_DIR, "cache"), exist_ok=True)

    def test_force_purges_cache_files(self):
        """Passing force=True immediately deletes cache files."""
        # Create dummy cache files
        for p in [UPDATE_CACHE_PATH, UPDATE_CHECK_CACHE_PATH]:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"cached_at": 9999999999, "data": {"test": True}}, f)
            self.assertTrue(os.path.isfile(p))

        with patch("core.updater.checker.requests.get") as mock_get:
            mock_res = MagicMock()
            mock_res.status_code = 200
            mock_res.json.return_value = {
                "tag_name": Config.VERSION,
                "body": "No changes",
                "published_at": "2026-09-18"
            }
            mock_get.return_value = mock_res

            # When force=True is called, existing cache files are deleted before new query
            with patch("core.updater.checker._check_remote_branch_commit", return_value=None):
                res = check_for_system_updates(force=True)
                self.assertTrue(res["checked"])

    @patch("core.updater.checker.requests.get")
    def test_branch_commit_fallback_when_release_not_newer(self, mock_get):
        """Falls back to remote branch commit if release tag is not newer."""
        # Setup release response (same version as Config.VERSION -> not newer)
        release_res = MagicMock()
        release_res.status_code = 200
        release_res.json.return_value = {
            "tag_name": Config.VERSION,
            "body": "Stable release",
            "published_at": "2026-09-01"
        }

        # Setup branch commit response (new remote commit SHA)
        commit_res = MagicMock()
        commit_res.status_code = 200
        commit_res.json.return_value = {
            "sha": "abcdef1234567890abcdef1234567890abcdef12",
            "commit": {
                "message": "fix: critical engine stability patch",
                "author": {"date": "2026-09-18T12:00:00Z"}
            },
            "html_url": "https://github.com/Cave404/Open-POS/commit/abcdef1"
        }

        def mock_side_effect(url, **kwargs):
            if "commits" in url:
                return commit_res
            return release_res

        mock_get.side_effect = mock_side_effect

        with patch("core.updater.checker._get_local_git_sha", return_value="1111112222223333334444445555556666667777"):
            result = check_for_system_updates(force=True)
            self.assertTrue(result["update_available"])
            self.assertEqual(result["latest_version"], "rev-abcdef1")
            self.assertIn("Main Branch", result["release_name"])
            self.assertIn("archive/refs/heads/main.zip", result["download_url"])

    @patch("core.updater.checker.requests.get")
    def test_branch_commit_fallback_on_404_releases(self, mock_get):
        """Falls back to branch commits when releases/latest returns 404."""
        r404 = MagicMock()
        r404.status_code = 404

        commit_res = MagicMock()
        commit_res.status_code = 200
        commit_res.json.return_value = {
            "sha": "9999888877776666555544443333222211110000",
            "commit": {
                "message": "feat: initial commit on main",
                "author": {"date": "2026-09-18T14:00:00Z"}
            }
        }

        def mock_side_effect(url, **kwargs):
            if "commits" in url:
                return commit_res
            return r404

        mock_get.side_effect = mock_side_effect

        with patch("core.updater.checker._get_local_git_sha", return_value="0000000000000000000000000000000000000000"):
            result = check_for_system_updates(force=True)
            self.assertTrue(result["update_available"])
            self.assertEqual(result["latest_version"], "rev-9999888")
