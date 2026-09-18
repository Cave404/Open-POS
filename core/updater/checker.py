"""
=============================================================================
Open-POS Core Release Checker & Changelog Parser
=============================================================================
Polls the GitHub Releases API for Cave404/Open-POS to determine whether
a newer version of the application is available.

Features:
  - Markdown changelog categorization: Added, Changed, Fixed, Removed.
  - 2-hour local rate-limit caching in data/cache/update_status.json.
  - Semver-aware version comparison.
  - Graceful network failure handling — never throws unhandled exceptions.
  - Background polling thread with configurable intervals.
=============================================================================
"""

import os
import re
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

import requests
from core.config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GITHUB_REPO          = "Cave404/Open-POS"
RELEASES_API_URL     = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
REQUEST_TIMEOUT_SEC  = 8
CACHE_TTL_SECONDS    = 7200        # 2 hours
POLL_INTERVAL_SEC    = 3600        # 1 hour between background checks
BOOT_DELAY_SEC       = 30          # Delay first check after startup

UPDATE_CACHE_PATH       = os.path.join(Config.DATA_DIR, "cache", "update_status.json")
UPDATE_CHECK_CACHE_PATH = os.path.join(Config.DATA_DIR, "cache", "update_check.json")

# In-memory shared state
_update_cache: Dict[str, Any] = {
    "checked": False,
    "available": False,
    "update_available": False,
    "current_version": Config.VERSION,
    "latest_version": None,
    "release_name": None,
    "published_at": None,
    "release_date": None,
    "changelog": {"added": [], "changed": [], "fixed": [], "removed": []},
    "raw_notes": "",
    "download_url": None,
    "html_url": None,
    "error": None,
}
_cache_lock = threading.Lock()
_checker_started = False
_checker_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Semver Helpers
# ---------------------------------------------------------------------------
def _parse_semver(version_str: str) -> Tuple[int, int, int]:
    """
    Parses a semantic version string into a (major, minor, patch) integer tuple.
    Strips any leading 'v' prefix. Defaults missing patch to 0.
    """
    if not version_str:
        return (0, 0, 0)
    clean = str(version_str).strip().lstrip("vV")
    parts = re.split(r"[.\-]", clean)
    try:
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except (ValueError, IndexError):
        return (0, 0, 0)


def _is_newer(candidate: str, current: str) -> bool:
    """Returns True if candidate version is strictly newer than current."""
    return _parse_semver(candidate) > _parse_semver(current)


# ---------------------------------------------------------------------------
# Changelog Parser
# ---------------------------------------------------------------------------
def parse_markdown_changelog(body: str) -> Dict[str, List[str]]:
    """
    Parses a GitHub release body markdown into categorized buckets:
    added, changed, fixed, and removed.
    """
    categories = {"added": [], "changed": [], "fixed": [], "removed": []}
    if not body or not body.strip():
        return categories

    current_cat = None

    for line in body.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue

        if re.match(r"^#{1,4}\s+(?:Added|Features|New)", line_clean, re.I):
            current_cat = "added"
        elif re.match(r"^#{1,4}\s+(?:Changed|Updates|Improvements)", line_clean, re.I):
            current_cat = "changed"
        elif re.match(r"^#{1,4}\s+(?:Fixed|Bug Fixes|Patches)", line_clean, re.I):
            current_cat = "fixed"
        elif re.match(r"^#{1,4}\s+(?:Removed|Deprecated|Breaking)", line_clean, re.I):
            current_cat = "removed"
        elif current_cat and line_clean.startswith(("-", "*", "+")):
            item = line_clean.lstrip("-*+ \t")
            if item:
                categories[current_cat].append(item)
        elif not current_cat and line_clean.startswith(("-", "*", "+")):
            # Fallback if no explicit category heading: treat as changed
            item = line_clean.lstrip("-*+ \t")
            if item:
                categories["changed"].append(item)

    return categories


# ---------------------------------------------------------------------------
# Core Check Function
# ---------------------------------------------------------------------------
def check_for_system_updates(force: bool = False, repo: str = GITHUB_REPO) -> Dict[str, Any]:
    """
    Queries GitHub Releases API for repo to check if a new version is available.
    Uses local file cache (2-hour TTL) to prevent API rate limiting unless force=True.
    """
    os.makedirs(os.path.join(Config.DATA_DIR, "cache"), exist_ok=True)
    now = datetime.now(timezone.utc).timestamp()

    # 1. Check local file cache
    if not force:
        for cache_path in [UPDATE_CACHE_PATH, UPDATE_CHECK_CACHE_PATH]:
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    cached_at = cached.get("cached_at", 0)
                    if now - cached_at < CACHE_TTL_SECONDS and "data" in cached:
                        with _cache_lock:
                            _update_cache.update(cached["data"])
                        return cached["data"]
                except Exception:
                    pass

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    logger.info(f"[UPDATER] Checking GitHub for system updates at: {url}")

    try:
        res = requests.get(
            url,
            timeout=REQUEST_TIMEOUT_SEC,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"OpenPOS-Updater/{Config.VERSION}"
            }
        )

        if res.status_code != 200:
            err_msg = f"GitHub API returned HTTP {res.status_code}"
            logger.warning(f"[UPDATER] {err_msg}")
            out = {
                "checked": True,
                "update_available": False,
                "available": False,
                "current_version": Config.VERSION,
                "latest_version": None,
                "release_name": None,
                "published_at": None,
                "release_date": None,
                "download_url": None,
                "html_url": None,
                "changelog": {"added": [], "changed": [], "fixed": [], "removed": []},
                "raw_notes": "",
                "error": err_msg
            }
            with _cache_lock:
                _update_cache.update(out)
            return out

        release = res.json()
        latest_tag = release.get("tag_name", "").strip()
        body = release.get("body", "")
        is_newer = _is_newer(latest_tag, Config.VERSION)

        parsed_changelog = parse_markdown_changelog(body)
        published_at = release.get("published_at", release.get("created_at", ""))

        result = {
            "checked": True,
            "update_available": is_newer,
            "available": is_newer,  # backwards-compatibility alias
            "current_version": Config.VERSION,
            "latest_version": latest_tag,
            "release_name": release.get("name") or latest_tag,
            "published_at": published_at,
            "release_date": published_at,  # backwards-compatibility alias
            "download_url": release.get("zipball_url"),
            "html_url": release.get("html_url"),
            "changelog": parsed_changelog,
            "raw_notes": body,
            "error": None
        }

        # Cache results to disk
        payload = {"cached_at": now, "data": result}
        for cpath in [UPDATE_CACHE_PATH, UPDATE_CHECK_CACHE_PATH]:
            try:
                with open(cpath, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
            except Exception as ce:
                logger.warning(f"[UPDATER] Failed to write cache {cpath}: {ce}")

        with _cache_lock:
            _update_cache.update(result)

        if is_newer:
            logger.info(f"[UPDATER] System update available: {Config.VERSION} -> {latest_tag}")
        else:
            logger.info(f"[UPDATER] System is up to date ({Config.VERSION}).")

        return result

    except requests.exceptions.ConnectionError:
        err = "No internet connection or GitHub is unreachable."
        logger.warning(f"[UPDATER] {err}")
    except requests.exceptions.Timeout:
        err = f"GitHub API timed out after {REQUEST_TIMEOUT_SEC}s."
        logger.warning(f"[UPDATER] {err}")
    except Exception as e:
        err = f"Failed to check for system updates: {e}"
        logger.warning(f"[UPDATER] {err}")

    fallback = {
        "checked": True,
        "update_available": False,
        "available": False,
        "current_version": Config.VERSION,
        "latest_version": None,
        "release_name": None,
        "published_at": None,
        "release_date": None,
        "download_url": None,
        "html_url": None,
        "changelog": {"added": [], "changed": [], "fixed": [], "removed": []},
        "raw_notes": "",
        "error": err
    }
    with _cache_lock:
        _update_cache.update(fallback)
    return fallback


# Backwards-compatible alias for existing callers/tests
def check_for_updates(repo: str = GITHUB_REPO) -> Dict[str, Any]:
    return check_for_system_updates(force=True, repo=repo)


def get_update_status() -> Dict[str, Any]:
    """Returns cached update state without hitting network."""
    # Check disk cache first if in-memory is unchecked
    with _cache_lock:
        if not _update_cache.get("checked"):
            if os.path.exists(UPDATE_CACHE_PATH):
                try:
                    with open(UPDATE_CACHE_PATH, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    if "data" in cached:
                        _update_cache.update(cached["data"])
                except Exception:
                    pass
        return dict(_update_cache)


# ---------------------------------------------------------------------------
# Background Polling Thread
# ---------------------------------------------------------------------------
def _background_loop():
    """Waits for initial boot delay, then checks periodically."""
    logger.info(f"[UPDATER] Background checker sleeping {BOOT_DELAY_SEC}s before initial check.")
    time.sleep(BOOT_DELAY_SEC)

    while True:
        try:
            check_for_system_updates(force=False)
        except Exception as e:
            logger.exception(f"[UPDATER] Uncaught exception in background check loop: {e}")
        time.sleep(POLL_INTERVAL_SEC)


def start_background_checker(app=None, interval_seconds: int = POLL_INTERVAL_SEC):
    """Spawns an idempotent background thread to monitor updates."""
    global _checker_started

    with _checker_lock:
        if _checker_started:
            return
        _checker_started = True

    t = threading.Thread(
        target=_background_loop,
        name="openpos-update-checker",
        daemon=True
    )
    t.start()
    logger.info("[UPDATER] Background update checker thread started.")
