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


def _get_local_git_sha() -> Optional[str]:
    """Retrieves current git commit SHA or build SHA for the local installation."""
    env_sha = os.environ.get("OPENPOS_GIT_SHA") or os.environ.get("BUILD_SHA") or getattr(Config, "GIT_SHA", None)
    if env_sha:
        return str(env_sha).strip()

    for b_path in [os.path.join(Config.DATA_DIR, "build_info.json"), os.path.join(Config.BASE_DIR, "build_info.json")]:
        if os.path.isfile(b_path):
            try:
                with open(b_path, "r", encoding="utf-8") as f:
                    bdata = json.load(f)
                sha = bdata.get("commit_sha") or bdata.get("sha")
                if sha:
                    return str(sha).strip()
            except Exception:
                pass

    try:
        import subprocess
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Config.BASE_DIR,
            stderr=subprocess.DEVNULL,
            timeout=3
        ).decode("utf-8").strip()
        if out:
            return out
    except Exception:
        pass

    return None


def _check_remote_branch_commit(repo: str = GITHUB_REPO, branch: str = "main") -> Optional[Dict[str, Any]]:
    """
    Fallback checker: queries GitHub Commits API for branch 'main'.
    If the remote commit SHA differs from the local build SHA, returns update payload.
    """
    commit_url = f"https://api.github.com/repos/{repo}/commits/{branch}"
    logger.info(f"[UPDATER] Checking GitHub fallback branch commit at: {commit_url}")
    try:
        c_res = requests.get(
            commit_url,
            timeout=REQUEST_TIMEOUT_SEC,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"OpenPOS-Updater/{Config.VERSION}"
            }
        )
        if c_res.status_code == 200:
            commit_data = c_res.json()
            remote_sha = commit_data.get("sha", "").strip()
            local_sha = _get_local_git_sha()
            commit_obj = commit_data.get("commit", {})
            commit_msg = commit_obj.get("message", "").strip()
            published_at = commit_obj.get("author", {}).get("date") or commit_obj.get("committer", {}).get("date", "")
            first_line = commit_msg.splitlines()[0] if commit_msg else f"Commit {remote_sha[:7]}"

            is_commit_ahead = False
            if remote_sha and local_sha:
                if not remote_sha.startswith(local_sha) and not local_sha.startswith(remote_sha):
                    is_commit_ahead = True

            short_sha = remote_sha[:7] if remote_sha else "unknown"
            result = {
                "checked": True,
                "update_available": is_commit_ahead,
                "available": is_commit_ahead,
                "current_version": Config.VERSION,
                "latest_version": f"rev-{short_sha}",
                "release_name": f"{branch.capitalize()} Branch: {first_line}",
                "published_at": published_at,
                "release_date": published_at,
                "download_url": f"https://github.com/{repo}/archive/refs/heads/{branch}.zip",
                "html_url": commit_data.get("html_url") or f"https://github.com/{repo}/tree/{branch}",
                "changelog": {"added": [], "changed": [first_line], "fixed": [], "removed": []},
                "raw_notes": commit_msg,
                "remote_sha": remote_sha,
                "local_sha": local_sha,
                "is_branch_fallback": True,
                "error": None
            }
            return result
    except Exception as ce:
        logger.warning(f"[UPDATER] Branch commit fallback query failed: {ce}")
    return None


# ---------------------------------------------------------------------------
# Core Check Function
# ---------------------------------------------------------------------------
def check_for_system_updates(force: bool = False, repo: str = GITHUB_REPO) -> Dict[str, Any]:
    """
    Queries GitHub Releases API for repo to check if a new version is available.
    Uses local file cache (2-hour TTL) to prevent API rate limiting unless force=True.
    Falls back to querying the remote main branch commit if no newer release tag is found.
    """
    os.makedirs(os.path.join(Config.DATA_DIR, "cache"), exist_ok=True)
    now = datetime.now(timezone.utc).timestamp()

    # 1. Check local file cache unless force=True
    if force:
        for cache_path in [UPDATE_CACHE_PATH, UPDATE_CHECK_CACHE_PATH]:
            try:
                if os.path.exists(cache_path):
                    os.remove(cache_path)
            except Exception as ce:
                logger.warning(f"[UPDATER] Failed to purge cache file {cache_path}: {ce}")
        with _cache_lock:
            _update_cache["checked"] = False
    else:
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

        result = None
        if res.status_code == 200:
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

            # If release is not newer, fallback to comparing remote main branch commit
            if not is_newer:
                branch_check = _check_remote_branch_commit(repo=repo)
                if branch_check and branch_check.get("update_available"):
                    result = branch_check
        else:
            # Non-200 release status (e.g. 404): Try branch commit fallback
            branch_check = _check_remote_branch_commit(repo=repo)
            if branch_check:
                result = branch_check
            else:
                err_msg = f"GitHub API returned HTTP {res.status_code}"
                logger.warning(f"[UPDATER] {err_msg}")
                result = {
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

        # Cache valid results to disk
        if result and not result.get("error"):
            payload = {"cached_at": now, "data": result}
            for cpath in [UPDATE_CACHE_PATH, UPDATE_CHECK_CACHE_PATH]:
                try:
                    with open(cpath, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2)
                except Exception as ce:
                    logger.warning(f"[UPDATER] Failed to write cache {cpath}: {ce}")

        with _cache_lock:
            _update_cache.update(result)

        if result.get("update_available"):
            logger.info(f"[UPDATER] System update available: {Config.VERSION} -> {result.get('latest_version')}")
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


# ---------------------------------------------------------------------------
# Python Package Dependencies Scanner
# ---------------------------------------------------------------------------
def get_outdated_packages() -> List[Dict[str, Any]]:
    """
    Runs pip list --outdated --format=json in active virtual environment
    and returns available dependency updates for packages.
    """
    import sys
    import subprocess
    try:
        cmd = [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if proc.returncode == 0 and proc.stdout.strip():
            packages = json.loads(proc.stdout)
            if isinstance(packages, list):
                return packages
    except Exception as e:
        logger.warning(f"[UPDATER] Could not scan pip outdated packages: {e}")
    return []

