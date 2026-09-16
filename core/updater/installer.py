"""
=============================================================================
Open-POS In-Place Update Installer
=============================================================================
Implements the full update pipeline:

  1. create_snapshot()   -- Copy core source tree (excluding data/, venv/, .git/)
                            into data/backups/engine_snapshot_{timestamp}/.
  2. apply_update()      -- Download release ZIP from GitHub and unpack it
                            in-place over the core source tree, never touching
                            data/ or venv/.
  3. run_health_check()  -- Spawn a detached Python subprocess that imports
                            create_app() to verify the updated codebase boots.
  4. rollback()          -- Restore snapshot contents back to BASE_DIR on failure.
  5. install_update()    -- Orchestrate the full snapshot → apply → health-check
                            → rollback-on-failure pipeline with SSE-compatible
                            progress callbacks.
=============================================================================
"""

import os
import sys
import shutil
import zipfile
import logging
import subprocess
import time

import requests

from core.config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DOWNLOAD_TIMEOUT_SEC   = 60          # Max seconds for ZIP download
HEALTH_CHECK_TIMEOUT   = 20          # Max seconds for health-check subprocess
BACKUP_DIR             = os.path.join(Config.DATA_DIR, "backups")

# Directories/files that must NEVER be included in snapshots or overwritten by updates
EXCLUDED_DIRS = {"data", "venv", ".git", "__pycache__", ".pytest_cache", "node_modules"}
EXCLUDED_FILES = {".env", "*.pyc", "*.pyo"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _should_exclude(rel_path: str) -> bool:
    """Returns True if the given relative path should be excluded from copy operations."""
    parts = rel_path.replace("\\", "/").split("/")
    # Exclude if any path component is a top-level excluded dir
    if parts and parts[0] in EXCLUDED_DIRS:
        return True
    # Exclude compiled Python files
    if rel_path.endswith((".pyc", ".pyo")):
        return True
    return False


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------------------
# 1. Snapshot
# ---------------------------------------------------------------------------
def create_snapshot(snapshot_dir: str = None) -> dict:
    """
    Copies all core source files (excluding data/, venv/, .git/, __pycache__)
    into `data/backups/engine_snapshot_{timestamp}/`.

    Args:
        snapshot_dir: Override destination directory. Auto-generated if None.

    Returns:
        {
            "success":       bool,
            "snapshot_path": str,
            "files_count":   int,
            "error":         str|None
        }
    """
    if not snapshot_dir:
        snapshot_dir = os.path.join(BACKUP_DIR, f"engine_snapshot_{_timestamp()}")

    try:
        os.makedirs(snapshot_dir, exist_ok=True)
        base = Config.BASE_DIR
        files_count = 0

        for root, dirs, files in os.walk(base):
            rel_root = os.path.relpath(root, base)

            # Prune excluded directories from os.walk descent
            dirs[:] = [
                d for d in dirs
                if not _should_exclude(os.path.join(rel_root, d).lstrip(".\\/"))
            ]

            for filename in files:
                src_rel = os.path.join(rel_root, filename)
                if _should_exclude(src_rel.lstrip(".\\")):
                    continue

                src_path  = os.path.join(root, filename)
                dest_path = os.path.join(snapshot_dir, src_rel)

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(src_path, dest_path)
                files_count += 1

        logger.info(f"[UPDATER] Snapshot created: {snapshot_dir} ({files_count} files)")
        return {
            "success":       True,
            "snapshot_path": snapshot_dir,
            "files_count":   files_count,
            "error":         None,
        }

    except Exception as e:
        logger.exception(f"[UPDATER] Snapshot failed: {e}")
        return {
            "success":       False,
            "snapshot_path": snapshot_dir,
            "files_count":   0,
            "error":         str(e),
        }


# ---------------------------------------------------------------------------
# 2. Apply Update
# ---------------------------------------------------------------------------
def apply_update(download_url: str, progress_cb=None) -> dict:
    """
    Downloads a GitHub release ZIP from `download_url`, extracts it,
    and copies all core files into BASE_DIR — never touching data/ or venv/.

    GitHub zips have a top-level wrapper folder (e.g. `Cave404-Open-POS-abc123/`)
    which is detected and flattened automatically.

    Args:
        download_url: URL to the GitHub zipball.
        progress_cb:  Optional callable(pct: int, msg: str) for SSE progress.

    Returns:
        {"success": bool, "message": str}
    """
    def _emit(pct, msg):
        if progress_cb:
            try:
                progress_cb(pct, msg)
            except Exception:
                pass
        logger.info(f"[UPDATER] [{pct}%] {msg}")

    staging_zip  = os.path.join(Config.CACHE_DIR, "update_staging.zip")
    staging_dir  = os.path.join(Config.CACHE_DIR, "update_staging_extract")

    try:
        # -- Download --
        _emit(5, "Downloading update package from GitHub...")
        os.makedirs(Config.CACHE_DIR, exist_ok=True)

        with requests.get(download_url, stream=True, timeout=DOWNLOAD_TIMEOUT_SEC,
                          headers={"User-Agent": f"Open-POS/{Config.VERSION}"}) as r:
            r.raise_for_status()
            total   = int(r.headers.get("content-length", 0))
            written = 0
            with open(staging_zip, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)
                        if total:
                            pct = min(30, 5 + int(25 * written / total))
                            _emit(pct, f"Downloading... {written // 1024} KB / {total // 1024} KB")

        _emit(35, "Download complete. Extracting archive...")

        # -- Extract to staging --
        if os.path.isdir(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)
        os.makedirs(staging_dir, exist_ok=True)

        with zipfile.ZipFile(staging_zip, "r") as zf:
            zf.extractall(staging_dir)

        # -- Detect and flatten GitHub wrapper folder --
        entries = os.listdir(staging_dir)
        source_dir = staging_dir
        if len(entries) == 1 and os.path.isdir(os.path.join(staging_dir, entries[0])):
            source_dir = os.path.join(staging_dir, entries[0])
            logger.info(f"[UPDATER] Detected wrapper folder '{entries[0]}', flattening...")

        _emit(50, "Applying update to core source tree...")

        # -- Copy files to BASE_DIR, excluding data/ and venv/ --
        base      = Config.BASE_DIR
        overwritten = 0

        for root, dirs, files in os.walk(source_dir):
            rel_root = os.path.relpath(root, source_dir)

            dirs[:] = [
                d for d in dirs
                if not _should_exclude(os.path.join(rel_root, d).lstrip(".\\/"))
            ]

            for filename in files:
                src_rel = os.path.join(rel_root, filename)
                if _should_exclude(src_rel.lstrip(".\\")):
                    continue

                src_path  = os.path.join(root, filename)
                dest_path = os.path.join(base, src_rel)

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(src_path, dest_path)
                overwritten += 1

        _emit(85, f"Applied {overwritten} files. Cleaning up staging area...")

        # -- Cleanup --
        try:
            os.remove(staging_zip)
        except OSError:
            pass
        try:
            shutil.rmtree(staging_dir, ignore_errors=True)
        except OSError:
            pass

        _emit(90, "Update applied successfully.")
        return {"success": True, "message": f"Applied {overwritten} files successfully."}

    except requests.exceptions.ConnectionError:
        msg = "Cannot download update: no internet connection."
        logger.error(f"[UPDATER] {msg}")
        return {"success": False, "message": msg}
    except requests.exceptions.Timeout:
        msg = f"Update download timed out after {DOWNLOAD_TIMEOUT_SEC}s."
        logger.error(f"[UPDATER] {msg}")
        return {"success": False, "message": msg}
    except zipfile.BadZipFile:
        msg = "Downloaded archive is corrupt or not a valid ZIP file."
        logger.error(f"[UPDATER] {msg}")
        return {"success": False, "message": msg}
    except Exception as e:
        logger.exception(f"[UPDATER] apply_update failed: {e}")
        return {"success": False, "message": str(e)}


# ---------------------------------------------------------------------------
# 3. Health Check
# ---------------------------------------------------------------------------
def run_health_check() -> bool:
    """
    Verifies that the updated codebase can successfully boot by spawning a
    subprocess that imports create_app().

    Returns True if the subprocess exits with code 0 within HEALTH_CHECK_TIMEOUT seconds.
    Returns False on any error, timeout, or non-zero exit.
    """
    cmd = [
        sys.executable, "-c",
        "from app import create_app; app = create_app(); print('HEALTH_OK')"
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=Config.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=HEALTH_CHECK_TIMEOUT,
        )
        passed = result.returncode == 0 and "HEALTH_OK" in result.stdout
        if passed:
            logger.info("[UPDATER] Health check PASSED.")
        else:
            logger.warning(
                f"[UPDATER] Health check FAILED (exit={result.returncode}). "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return passed
    except subprocess.TimeoutExpired:
        logger.error(f"[UPDATER] Health check timed out after {HEALTH_CHECK_TIMEOUT}s.")
        return False
    except Exception as e:
        logger.exception(f"[UPDATER] Health check exception: {e}")
        return False


# ---------------------------------------------------------------------------
# 4. Rollback
# ---------------------------------------------------------------------------
def rollback(snapshot_path: str) -> dict:
    """
    Restores the core source tree from `snapshot_path` by copying all snapshot
    files back into BASE_DIR.  Never modifies data/ or venv/.

    Args:
        snapshot_path: Absolute path to the engine snapshot directory.

    Returns:
        {"success": bool, "message": str}
    """
    if not snapshot_path or not os.path.isdir(snapshot_path):
        return {"success": False, "message": f"Snapshot path not found: {snapshot_path}"}

    try:
        base        = Config.BASE_DIR
        restored    = 0

        for root, dirs, files in os.walk(snapshot_path):
            rel_root = os.path.relpath(root, snapshot_path)

            dirs[:] = [
                d for d in dirs
                if not _should_exclude(os.path.join(rel_root, d).lstrip(".\\/"))
            ]

            for filename in files:
                src_rel = os.path.join(rel_root, filename)
                if _should_exclude(src_rel.lstrip(".\\")):
                    continue

                src_path  = os.path.join(root, filename)
                dest_path = os.path.join(base, src_rel)

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(src_path, dest_path)
                restored += 1

        logger.info(f"[UPDATER] Rollback complete: {restored} files restored from {snapshot_path}")
        return {"success": True, "message": f"Rollback successful — {restored} files restored."}

    except Exception as e:
        logger.exception(f"[UPDATER] Rollback failed: {e}")
        return {"success": False, "message": str(e)}


# ---------------------------------------------------------------------------
# 5. Orchestrated Install Pipeline
# ---------------------------------------------------------------------------
def install_update(download_url: str, progress_cb=None) -> dict:
    """
    Orchestrates the complete update lifecycle:

        1. Pre-flight snapshot  (data/ and venv/ excluded)
        2. Apply update ZIP     (data/ and venv/ never touched)
        3. Health check         (boot verification subprocess)
        4. Rollback on failure  (automatic if health check fails)

    Args:
        download_url: GitHub zipball URL from checker.check_for_updates().
        progress_cb:  Optional callable(pct: int, msg: str) for SSE streaming.

    Returns:
        {
            "success":       bool,
            "message":       str,
            "snapshot_path": str|None,
            "rolled_back":   bool,
        }
    """
    def _emit(pct, msg):
        if progress_cb:
            try:
                progress_cb(pct, msg)
            except Exception:
                pass
        logger.info(f"[UPDATER] [{pct}%] {msg}")

    snapshot_path = None
    rolled_back   = False

    try:
        # -- Step 1: Snapshot --
        _emit(2, "Creating pre-update snapshot (excluding data/ and venv/)...")
        snap_result = create_snapshot()
        if not snap_result["success"]:
            return {
                "success":       False,
                "message":       f"Snapshot failed: {snap_result['error']}",
                "snapshot_path": None,
                "rolled_back":   False,
            }
        snapshot_path = snap_result["snapshot_path"]
        _emit(10, f"Snapshot created ({snap_result['files_count']} files): {snapshot_path}")

        # -- Step 2: Apply update --
        apply_result = apply_update(download_url, progress_cb=progress_cb)
        if not apply_result["success"]:
            return {
                "success":       False,
                "message":       apply_result["message"],
                "snapshot_path": snapshot_path,
                "rolled_back":   False,
            }

        # -- Step 3: Health check --
        _emit(92, "Running post-update health verification...")
        healthy = run_health_check()

        if not healthy:
            # -- Step 4: Auto-rollback --
            _emit(94, "Health check failed — initiating automatic rollback...")
            rb_result  = rollback(snapshot_path)
            rolled_back = rb_result["success"]
            return {
                "success":       False,
                "message":       (
                    "Update applied but health check failed. "
                    + ("Automatic rollback succeeded." if rolled_back else "Rollback also failed — manual restore required.")
                ),
                "snapshot_path": snapshot_path,
                "rolled_back":   rolled_back,
            }

        _emit(100, "Update installed successfully. Please restart Open-POS.")
        return {
            "success":       True,
            "message":       "Update installed successfully. A system restart is required.",
            "snapshot_path": snapshot_path,
            "rolled_back":   False,
        }

    except Exception as e:
        logger.exception(f"[UPDATER] install_update orchestration failed: {e}")
        return {
            "success":       False,
            "message":       f"Unexpected installer error: {e}",
            "snapshot_path": snapshot_path,
            "rolled_back":   rolled_back,
        }
