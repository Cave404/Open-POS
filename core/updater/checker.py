"""
=============================================================================
Open-POS Release Checker
=============================================================================
Polls the GitHub Releases API for Cave404/Open-POS to determine whether
a newer version of the application is available.

Features:
  - Semver-aware version comparison (handles v-prefix and patch omission).
  - Changelog section parsing from GitHub release body markdown.
  - Graceful network failure handling — never blocks startup or the wizard.
  - In-memory result cache shared across the process.
  - Optional background polling thread (started once per application lifetime).
=============================================================================
"""

import re
import json
import logging
import threading
import time

import requests

from core.config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GITHUB_REPO          = "Cave404/Open-POS"
RELEASES_API_URL     = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
REQUEST_TIMEOUT_SEC  = 8
POLL_INTERVAL_SEC    = 3600        # 1 hour between background checks
BOOT_DELAY_SEC       = 30          # Delay first check after startup

# ---------------------------------------------------------------------------
# In-memory update cache (shared across requests within one process)
# ---------------------------------------------------------------------------
_update_cache: dict = {
    "checked": False,
    "available": False,
    "current_version": Config.VERSION,
    "latest_version": None,
    "release_date": None,
    "changelog": [],
    "download_url": None,
    "html_url": None,
    "error": None,
}
_cache_lock = threading.Lock()
_checker_started = False
_checker_lock   = threading.Lock()


# ---------------------------------------------------------------------------
# Semver Helpers
# ---------------------------------------------------------------------------
def _parse_semver(version_str: str) -> tuple:
    """
    Parses a semantic version string into a (major, minor, patch) integer tuple.
    Strips any leading 'v' prefix. Defaults missing patch to 0.

    Examples:
        "v1.0.9"  -> (1, 0, 9)
        "1.0.10"  -> (1, 0, 10)
        "v2.1"    -> (2, 1, 0)
    """
    clean = version_str.strip().lstrip("vV")
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
def _parse_changelog(body: str) -> list:
    """
    Parses a GitHub release body markdown string into a list of section dicts:
        [{"heading": "What's Changed", "items": ["Added X", "Fixed Y"]}, ...]

    Falls back to splitting by line if no headings are detected.
    """
    if not body or not body.strip():
        return []

    sections = []
    current_heading = "Release Notes"
    current_items   = []

    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Detect markdown headings (## or ###)
        heading_match = re.match(r"^#{1,3}\s+(.+)$", stripped)
        if heading_match:
            if current_items:
                sections.append({"heading": current_heading, "items": current_items})
            current_heading = heading_match.group(1).strip()
            current_items   = []
        elif stripped.startswith(("-", "*", "+")):
            # Bullet point
            item_text = re.sub(r"^[-*+]\s+", "", stripped)
            if item_text:
                current_items.append(item_text)
        else:
            # Plain paragraph line — include as-is
            current_items.append(stripped)

    if current_items:
        sections.append({"heading": current_heading, "items": current_items})

    return sections


# ---------------------------------------------------------------------------
# Core Check Function
# ---------------------------------------------------------------------------
def check_for_updates(repo: str = GITHUB_REPO) -> dict:
    """
    Queries the GitHub Releases API to determine if a newer version exists.

    Returns a dict:
        {
            "checked":         True,
            "available":       bool,
            "current_version": str,      # e.g. "v1.0.9"
            "latest_version":  str|None, # e.g. "v1.0.10"
            "release_date":    str|None, # ISO 8601
            "changelog":       list,     # parsed sections
            "download_url":    str|None, # zipball URL for installer
            "html_url":        str|None, # GitHub release page URL
            "error":           str|None  # human-readable error on failure
        }

    Never raises — all exceptions are caught and surfaced via "error" key.
    """
    global _update_cache

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    logger.info(f"[UPDATER] Checking for updates at: {url}")

    result = {
        "checked":         True,
        "available":       False,
        "current_version": Config.VERSION,
        "latest_version":  None,
        "release_date":    None,
        "changelog":       [],
        "download_url":    None,
        "html_url":        None,
        "error":           None,
    }

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT_SEC,
            headers={
                "Accept":     "application/vnd.github+json",
                "User-Agent": f"Open-POS/{Config.VERSION}",
            }
        )
        response.raise_for_status()
        release = response.json()

        latest_tag  = release.get("tag_name", "").strip()
        html_url    = release.get("html_url", "")
        zipball_url = release.get("zipball_url", "")
        release_at  = release.get("published_at", release.get("created_at", ""))
        body        = release.get("body", "")

        result["latest_version"] = latest_tag
        result["html_url"]       = html_url
        result["download_url"]   = zipball_url
        result["release_date"]   = release_at
        result["changelog"]      = _parse_changelog(body)
        result["available"]      = _is_newer(latest_tag, Config.VERSION)

        if result["available"]:
            logger.info(
                f"[UPDATER] Update available: {Config.VERSION} → {latest_tag}"
            )
        else:
            logger.info(
                f"[UPDATER] Already on latest version ({Config.VERSION})."
            )

    except requests.exceptions.ConnectionError:
        result["error"] = "No internet connection or GitHub is unreachable."
        logger.warning("[UPDATER] Network error: could not reach GitHub.")
    except requests.exceptions.Timeout:
        result["error"] = f"GitHub API timed out after {REQUEST_TIMEOUT_SEC}s."
        logger.warning("[UPDATER] Timeout connecting to GitHub Releases API.")
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "?"
        result["error"] = f"GitHub API returned HTTP {status}."
        logger.warning(f"[UPDATER] HTTP error from GitHub: {e}")
    except Exception as e:
        result["error"] = f"Unexpected error checking for updates: {e}"
        logger.exception("[UPDATER] Unexpected exception during update check.")

    with _cache_lock:
        _update_cache.update(result)

    return result


# ---------------------------------------------------------------------------
# Cache Accessor
# ---------------------------------------------------------------------------
def get_update_status() -> dict:
    """
    Returns the cached update check result without hitting GitHub.
    If no check has been performed yet, returns the initial unchecked state.
    """
    with _cache_lock:
        return dict(_update_cache)


# ---------------------------------------------------------------------------
# Background Polling Thread
# ---------------------------------------------------------------------------
def _background_loop():
    """Worker function: waits for boot delay, then polls hourly."""
    logger.info(f"[UPDATER] Background checker sleeping {BOOT_DELAY_SEC}s before first check.")
    time.sleep(BOOT_DELAY_SEC)

    while True:
        try:
            check_for_updates()
        except Exception as e:
            logger.exception(f"[UPDATER] Uncaught exception in background loop: {e}")
        time.sleep(POLL_INTERVAL_SEC)


def start_background_checker(app=None, interval_seconds: int = POLL_INTERVAL_SEC):
    """
    Spawns a daemon thread that checks for updates at boot (after a 30-second
    delay) and then every `interval_seconds` thereafter.

    Idempotent — calling multiple times will not spawn duplicate threads.

    Args:
        app:              Flask app instance (unused; reserved for future context use).
        interval_seconds: Override the polling interval (default: 3600).
    """
    global _checker_started

    with _checker_lock:
        if _checker_started:
            logger.debug("[UPDATER] Background checker already running — skipping duplicate start.")
            return
        _checker_started = True

    t = threading.Thread(
        target=_background_loop,
        name="openpos-update-checker",
        daemon=True
    )
    t.start()
    logger.info("[UPDATER] Background update checker thread started.")
