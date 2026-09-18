"""
=============================================================================
Open-POS Atomic Engine Updater & Process Restarter (core/updater/engine.py)
=============================================================================
Governs the physical update transaction:
  1. Pre-update snapshot of core engine files to data/backups/
     (strictly excluding data/, venv/, and .git/).
  2. Streaming download of GitHub release archive to staging.
  3. Archive unnesting and atomic overwrite of application files.
  4. Post-update health verification via isolated python subprocess:
     python -c "import core; from core.config import Config; print('HEALTHY')"
  5. Automatic rollback on health verification failure or unexpected error.
  6. Audit logging to data/logs/updater.log.
  7. Detached process launcher (Start_POS.bat) on Windows (creationflags 0x00000008)
     and clean process termination.
=============================================================================
"""

import os
import sys
import shutil
import zipfile
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from core.config import Config
from core.logger import logger


def _log_to_updater_file(msg: str, level: str = "INFO") -> None:
    """Appends an ISO-timestamped audit record to data/logs/updater.log."""
    try:
        log_file = os.path.join(Config.DATA_DIR, "logs", "updater.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")
    except Exception:
        pass


def apply_system_update(download_url: str, new_version: str) -> bool:
    """
    Applies a system update by snapshotting current engine files, downloading
    the GitHub release archive, unnesting its payload, overwriting core source
    files while strictly protecting data/ and venv/, and executing a health
    check. If verification fails, an automatic rollback is performed.

    Returns:
        bool: True if the update succeeded and passed verification, False otherwise.
    """
    timestamp = int(time.time())
    staging_dir = os.path.join(Config.DATA_DIR, "cache", "update_staging")
    backup_dir = os.path.join(Config.DATA_DIR, "backups", f"engine_pre_update_{Config.VERSION}_{timestamp}")
    zip_target = os.path.join(staging_dir, "release.zip")

    os.makedirs(staging_dir, exist_ok=True)
    os.makedirs(backup_dir, exist_ok=True)

    _log_to_updater_file(f"Initiating system update to {new_version} from {download_url}")
    logger.info(f"[UPDATER] Initiating system update to {new_version}")

    try:
        # 1. Snapshot core files (Never copy data/, venv/, or .git/)
        core_targets = ["core", "manager", "static", "templates", "migrations", "run.py", "Start_POS.bat", "app.py"]
        snapshotted_count = 0

        for item in core_targets:
            s = os.path.join(Config.BASE_DIR, item)
            d = os.path.join(backup_dir, item)
            if not os.path.exists(s):
                continue
            if os.path.isdir(s):
                shutil.copytree(
                    s, d, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache")
                )
            elif os.path.isfile(s):
                shutil.copy2(s, d)
            snapshotted_count += 1

        _log_to_updater_file(f"Created pre-update backup snapshot at {backup_dir} ({snapshotted_count} targets)")
        logger.info(f"[UPDATER] Pre-update snapshot created at: {backup_dir}")

        # 2. Download release zip
        logger.info(f"[UPDATER] Downloading update archive from {download_url}")
        resp = requests.get(
            download_url,
            stream=True,
            timeout=30,
            headers={"User-Agent": f"OpenPOS-Updater/{Config.VERSION}"}
        )
        resp.raise_for_status()
        with open(zip_target, "wb") as f:
            shutil.copyfileobj(resp.raw, f)

        # 3. Extract and unnest
        extract_to = os.path.join(staging_dir, "extracted")
        if os.path.exists(extract_to):
            shutil.rmtree(extract_to, ignore_errors=True)
        os.makedirs(extract_to, exist_ok=True)

        with zipfile.ZipFile(zip_target, "r") as z:
            z.extractall(extract_to)

        # GitHub release archives enclose files in a single root wrapper directory
        subfolders = [f.path for f in os.scandir(extract_to) if f.is_dir()]
        root_payload = subfolders[0] if len(subfolders) == 1 else extract_to

        # 4. Overwrite core files (strictly guarding protected directories)
        protected_entries = {"data", "venv", ".git", ".env"}
        applied_count = 0

        for item in os.listdir(root_payload):
            if item in protected_entries:
                continue  # Critical data protection guard

            src = os.path.join(root_payload, item)
            dst = os.path.join(Config.BASE_DIR, item)

            if os.path.isdir(src):
                shutil.copytree(
                    src, dst, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache")
                )
            else:
                shutil.copy2(src, dst)
            applied_count += 1

        _log_to_updater_file(f"Applied {applied_count} payload elements from {new_version}")

        # 5. Sanity health check
        py_exec = sys.executable
        health_cmd = [py_exec, "-c", "import core; from core.config import Config; print('HEALTHY')"]
        check = subprocess.run(
            health_cmd,
            cwd=Config.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=15
        )

        if check.returncode != 0 or "HEALTHY" not in (check.stdout or ""):
            error_details = (check.stderr or check.stdout or "").strip()
            raise RuntimeError(f"Engine health verification failed (exit {check.returncode}): {error_details}")

        logger.info(f"[UPDATER] Successfully upgraded OpenPOS to {new_version}")
        _log_to_updater_file(f"Successfully upgraded OpenPOS to {new_version}. Health check verified OK.")

        # Staging cleanup
        try:
            if os.path.exists(staging_dir):
                shutil.rmtree(staging_dir, ignore_errors=True)
        except Exception:
            pass

        return True

    except Exception as e:
        err_msg = f"Update failed: {e}. Executing automatic rollback..."
        logger.error(f"[UPDATER] {err_msg}", exc_info=True)
        _log_to_updater_file(err_msg, level="ERROR")

        # Restore from snapshot
        try:
            if os.path.exists(backup_dir):
                for item in os.listdir(backup_dir):
                    if item in {"data", "venv", ".git"}:
                        continue
                    src = os.path.join(backup_dir, item)
                    dst = os.path.join(Config.BASE_DIR, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                logger.info(f"[UPDATER] Automatic rollback completed successfully from {backup_dir}")
                _log_to_updater_file(f"Automatic rollback completed successfully from {backup_dir}", level="INFO")
        except Exception as rb_err:
            logger.critical(f"[UPDATER] Critical: Automatic rollback failed: {rb_err}", exc_info=True)
            _log_to_updater_file(f"Critical: Automatic rollback failed: {rb_err}", level="CRITICAL")

        return False


def restart_openpos() -> None:
    """
    Launches detached Start_POS.bat (or platform fallback) and cleanly closes
    the current application instance. Uses DETACHED_PROCESS (0x00000008) on
    Windows to prevent port locks and child termination.
    """
    _log_to_updater_file("Supervisor initiating detached OpenPOS restart")
    logger.info("[UPDATER] Initiating detached OpenPOS restart...")

    bat_path = os.path.join(Config.BASE_DIR, "Start_POS.bat")
    creationflags = 0x00000008 if sys.platform == "win32" else 0

    try:
        if sys.platform == "win32" and os.path.exists(bat_path):
            subprocess.Popen(["cmd.exe", "/c", bat_path], creationflags=creationflags, close_fds=True)
        else:
            # Platform fallback
            run_py = os.path.join(Config.BASE_DIR, "run.py")
            subprocess.Popen([sys.executable, run_py], creationflags=creationflags, close_fds=True)
    except Exception as e:
        logger.error(f"[UPDATER] Failed to spawn detached launcher: {e}")
        _log_to_updater_file(f"Failed to spawn detached launcher: {e}", level="ERROR")

    # Clean termination
    os._exit(0)
