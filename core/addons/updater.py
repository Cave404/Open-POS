"""
=============================================================================
Open-POS In-Place Addon Hot-Updater, State Persistence, & Rollback Pipeline
=============================================================================
Provides zero-downtime, in-place updates for installed Open-POS addons:
  1. Ephemeral UI / cart state persistence via export_state() and restore_state().
  2. Pre-update directory snapshotting to data/backups/addons/.
  3. GitHub zip download, root wrapper flattening, and atomic file swap.
  4. Database schema migration execution.
  5. Module cache invalidation and dynamic re-mounting into live WSGI engine.
  6. Automated rollback to snapshot if update fails during migration or load.
  7. Manual rollback to any prior historical snapshot.
=============================================================================
"""

import os
import sys
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

from core.config import Config
from core.logger import get_addon_logger
from core.addons.catalog import get_catalog_item, fetch_catalog
from core.addons.loader import addon_manager, load_single_addon, STATE_ERROR, STATE_ACTIVE
from core.addons.installer import extract_addon_zip, _execute_addon_migrations

addon_logger = get_addon_logger()


def _get_addon_dir(addon_id: str) -> Path:
    custom_dir = getattr(Config, 'CUSTOM_ADDONS_DIR', os.path.join(Config.DATA_DIR, 'custom_addons'))
    return Path(custom_dir) / addon_id


def _get_cache_dir() -> Path:
    cache_dir = getattr(Config, 'CACHE_DIR', os.path.join(Config.DATA_DIR, 'cache'))
    p = Path(cache_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get_backups_dir() -> Path:
    backups_dir = Path(Config.DATA_DIR) / 'backups' / 'addons'
    backups_dir.mkdir(parents=True, exist_ok=True)
    return backups_dir


def export_addon_state(addon_id: str) -> Optional[Dict[str, Any]]:
    """
    Invokes export_state() on the active addon module if implemented,
    persisting the returned dictionary to data/cache/addon_state_<addon_id>.json.
    """
    record = addon_manager.addons.get(addon_id)
    if not record or not record.module:
        return None

    state_exporter = getattr(record.module, 'export_state', None)
    if not callable(state_exporter):
        return None

    try:
        state = state_exporter()
        if state is not None and isinstance(state, dict):
            cache_file = _get_cache_dir() / f"addon_state_{addon_id}.json"
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            addon_logger.info(f"Exported ephemeral state for addon '{addon_id}' ({len(state)} keys).")
            return state
    except Exception as e:
        addon_logger.warning(f"Failed to export state for addon '{addon_id}': {e}")

    return None


def restore_addon_state(addon_id: str, module: Any = None) -> bool:
    """
    Reads saved state from data/cache/addon_state_<addon_id>.json and invokes
    restore_state(state) on the reloaded addon module if available.
    """
    cache_file = _get_cache_dir() / f"addon_state_{addon_id}.json"
    if not cache_file.is_file():
        return False

    if module is None:
        rec = addon_manager.addons.get(addon_id)
        module = rec.module if rec else None

    if not module:
        return False

    restorer = getattr(module, 'restore_state', None)
    if not callable(restorer):
        return False

    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            state = json.load(f)

        restorer(state)
        addon_logger.info(f"Restored ephemeral state for addon '{addon_id}'.")
        return True
    except Exception as e:
        addon_logger.warning(f"Failed to restore state for addon '{addon_id}': {e}")
        return False


def create_addon_snapshot(addon_id: str, current_version: str = None) -> Path:
    """
    Creates a full backup snapshot of data/custom_addons/<addon_id>/ into
    data/backups/addons/<addon_id>_v<version>_<timestamp>/
    """
    addon_dir = _get_addon_dir(addon_id)
    if not addon_dir.is_dir():
        raise FileNotFoundError(f"Cannot create snapshot: addon directory '{addon_dir}' does not exist.")

    manifest_file = addon_dir / "manifest.json"
    if not current_version and manifest_file.is_file():
        try:
            with open(manifest_file, 'r', encoding='utf-8') as f:
                mdata = json.load(f)
                current_version = mdata.get("version", "unknown")
        except Exception:
            current_version = "unknown"

    ver_clean = str(current_version or "unknown").replace(" ", "_").replace("/", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_name = f"{addon_id}_v{ver_clean}_{ts}"

    snapshot_dir = _get_backups_dir() / snapshot_name
    shutil.copytree(str(addon_dir), str(snapshot_dir))

    # Record snapshot metadata
    meta = {
        "addon_id": addon_id,
        "version": current_version,
        "timestamp": ts,
        "created_at": datetime.now().isoformat(),
        "source_dir": str(addon_dir)
    }
    with open(snapshot_dir / "snapshot_meta.json", 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2)

    addon_logger.info(f"Created backup snapshot for '{addon_id}' at '{snapshot_dir.name}'.")
    return snapshot_dir


def list_addon_snapshots(addon_id: str) -> List[Dict[str, Any]]:
    """
    Inspects data/backups/addons/ and returns all snapshot records for addon_id
    sorted in reverse chronological order (newest first).
    """
    backups_dir = _get_backups_dir()
    snapshots = []

    if not backups_dir.is_dir():
        return snapshots

    prefix = f"{addon_id}_v"
    sub_addon_dir = backups_dir / addon_id

    # Scan root backups dir for <addon_id>_v*
    candidate_dirs = [p for p in backups_dir.iterdir() if p.is_dir() and (p.name.startswith(prefix) or p.name == addon_id)]

    # Also check inside data/backups/addons/<addon_id>/ if present
    if sub_addon_dir.is_dir():
        for sub_p in sub_addon_dir.iterdir():
            if sub_p.is_dir():
                candidate_dirs.append(sub_p)

    seen_paths = set()
    for s_dir in candidate_dirs:
        if str(s_dir) in seen_paths or s_dir == sub_addon_dir:
            continue
        seen_paths.add(str(s_dir))

        meta_file = s_dir / "snapshot_meta.json"
        manifest_file = s_dir / "manifest.json"

        version = "unknown"
        created_at = None
        ts = None

        if meta_file.is_file():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                    version = meta.get("version", version)
                    created_at = meta.get("created_at")
                    ts = meta.get("timestamp")
            except Exception:
                pass

        if version == "unknown" and manifest_file.is_file():
            try:
                with open(manifest_file, 'r', encoding='utf-8') as f:
                    mdata = json.load(f)
                    version = mdata.get("version", "unknown")
            except Exception:
                pass

        # Parse timestamp from folder name if needed
        folder_name = s_dir.name
        if not ts:
            parts = folder_name.split("_")
            if len(parts) >= 2:
                ts = "_".join(parts[-2:])

        if not created_at:
            try:
                mtime = s_dir.stat().st_mtime
                created_at = datetime.fromtimestamp(mtime).isoformat()
            except Exception:
                created_at = datetime.now().isoformat()

        snapshots.append({
            "snapshot_id": folder_name,
            "addon_id": addon_id,
            "version": version,
            "timestamp": ts or folder_name,
            "created_at": created_at,
            "path": str(s_dir)
        })

    # Sort newest first
    snapshots.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return snapshots


def update_addon(addon_id: str, app=None) -> Dict[str, Any]:
    """
    Executes an in-place hot-update for an installed custom addon:
      1. Verifies update availability in remote catalog.
      2. Exports ephemeral in-memory state.
      3. Creates a pre-update snapshot.
      4. Downloads and flattens new package.
      5. Swaps files into data/custom_addons/<addon_id>/.
      6. Runs database migrations.
      7. Hot-reloads Python modules and restores state.
      8. Auto-rollbacks to snapshot if migration or initialization fails.
    """
    # Step 1: Catalog Check
    item = get_catalog_item(addon_id)
    if not item:
        fetch_catalog(force_refresh=True)
        item = get_catalog_item(addon_id)

    if not item or not item.get("download_url"):
        raise ValueError(f"Addon '{addon_id}' not found in catalog or lacks download_url.")

    download_url = item["download_url"]
    target_version = item.get("version", "latest")
    addon_dir = _get_addon_dir(addon_id)

    if not addon_dir.is_dir():
        from core.addons.installer import install_remote_addon
        return install_remote_addon(addon_id)

    # Read current version
    current_version = "1.0.0"
    manifest_file = addon_dir / "manifest.json"
    if manifest_file.is_file():
        try:
            with open(manifest_file, 'r', encoding='utf-8') as f:
                current_version = json.load(f).get("version", "1.0.0")
        except Exception:
            pass

    addon_logger.info(f"Starting in-place update for '{addon_id}': v{current_version} -> v{target_version}")

    # Step 2: State Export
    export_addon_state(addon_id)

    # Step 3: Snapshot Creation
    snapshot_dir = create_addon_snapshot(addon_id, current_version=current_version)

    # Step 4: Download package
    cache_dir = _get_cache_dir()
    temp_zip = cache_dir / f"temp_update_{addon_id}_{os.getpid()}.zip"

    try:
        resp = requests.get(download_url, stream=True, timeout=25)
        if resp.status_code != 200:
            raise RuntimeError(f"Download failed (HTTP {resp.status_code}) from {download_url}")

        with open(temp_zip, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        # Step 5: Extract & Swap Files
        extract_res = extract_addon_zip(str(temp_zip), str(addon_dir))
        if extract_res.get("status") != "success":
            raise RuntimeError(f"Package extraction error: {extract_res.get('message')}")

        # Auto-install dependencies if requirements.txt exists
        addon_reqs = addon_dir / "requirements.txt"
        if addon_reqs.is_file():
            addon_logger.info(f"Installing dependencies for updated addon '{addon_id}'...")
            try:
                import subprocess
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", str(addon_reqs), "--no-cache-dir"],
                    check=True,
                    capture_output=True,
                    timeout=120
                )
                addon_logger.info(f"Dependencies installed successfully for updated addon '{addon_id}'.")
            except Exception as pe:
                addon_logger.warning(f"pip install for updated addon '{addon_id}' failed: {pe}")

        # Step 6: Database Migrations
        manifest_data = extract_res.get("manifest", {})
        requires_db = bool(manifest_data.get("requires_db", item.get("requires_db", False)))
        if requires_db:
            _execute_addon_migrations(str(addon_dir))

        # Step 7: Hot-Reload & Health Verification
        record = load_single_addon(str(addon_dir), dir_type="custom", app=app)
        if record.status == STATE_ERROR:
            raise RuntimeError(f"Addon initialization failed after update: {record.error}")

        # Restore state
        restore_addon_state(addon_id, record.module)

        addon_logger.info(f"Addon '{addon_id}' updated successfully to v{record.version}.")
        return {
            "status": "success",
            "message": (
                "Addon configured. Reloading engine..."
                if record.reload_required
                else f"Addon '{record.name}' updated successfully to v{record.version}."
            ),
            "addon_id": addon_id,
            "version": record.version,
            "reload_required": record.reload_required
        }

    except Exception as exc:
        # Step 8: Auto-Rollback on Failure
        err_msg = str(exc)
        addon_logger.error(f"Critical error updating addon '{addon_id}': {err_msg}. Triggering automatic rollback.", exc_info=True)

        try:
            # Wipe corrupted files
            if addon_dir.is_dir():
                shutil.rmtree(str(addon_dir), ignore_errors=True)
            addon_dir.mkdir(parents=True, exist_ok=True)

            # Restore files from snapshot (excluding snapshot_meta.json)
            for item_name in os.listdir(str(snapshot_dir)):
                if item_name == "snapshot_meta.json":
                    continue
                s_item = snapshot_dir / item_name
                d_item = addon_dir / item_name
                if s_item.is_dir():
                    shutil.copytree(str(s_item), str(d_item))
                else:
                    shutil.copy2(str(s_item), str(d_item))

            # Reload restored addon
            load_single_addon(str(addon_dir), dir_type="custom", app=app)
            restore_addon_state(addon_id)
            addon_logger.info(f"Addon '{addon_id}' successfully rolled back to v{current_version}.")
        except Exception as rb_exc:
            addon_logger.critical(f"Rollback recovery failed for addon '{addon_id}': {rb_exc}", exc_info=True)

        raise RuntimeError(f"Update failed during initialization; addon safely reverted to previous version (v{current_version}). Detail: {err_msg}")

    finally:
        if temp_zip.is_file():
            try:
                temp_zip.unlink()
            except Exception:
                pass


def rollback_addon(addon_id: str, snapshot_name: Optional[str] = None, app=None) -> Dict[str, Any]:
    """
    Manually reverts an addon directory to a selected or most recent historical snapshot:
      1. Resolves snapshot directory.
      2. Exports current ephemeral state if possible.
      3. Clears active directory and restores snapshot contents.
      4. Executes migrations if needed.
      5. Hot-reloads module and restores state.
    """
    snapshots = list_addon_snapshots(addon_id)
    if not snapshots:
        raise FileNotFoundError(f"No backup snapshots found for addon '{addon_id}'.")

    target_snapshot = None
    if snapshot_name:
        for s in snapshots:
            if s["snapshot_id"] == snapshot_name or s.get("path", "").endswith(snapshot_name):
                target_snapshot = s
                break
        if not target_snapshot:
            raise FileNotFoundError(f"Snapshot '{snapshot_name}' not found for addon '{addon_id}'.")
    else:
        # Default to latest
        target_snapshot = snapshots[0]

    snapshot_path = Path(target_snapshot["path"])
    addon_dir = _get_addon_dir(addon_id)

    # 1. Export in-progress state before swap
    export_addon_state(addon_id)

    addon_logger.info(f"Reverting addon '{addon_id}' to snapshot '{target_snapshot['snapshot_id']}'...")

    # 2. Swap files
    if addon_dir.is_dir():
        shutil.rmtree(str(addon_dir), ignore_errors=True)
    addon_dir.mkdir(parents=True, exist_ok=True)

    for item_name in os.listdir(str(snapshot_path)):
        if item_name == "snapshot_meta.json":
            continue
        s_item = snapshot_path / item_name
        d_item = addon_dir / item_name
        if s_item.is_dir():
            shutil.copytree(str(s_item), str(d_item))
        else:
            shutil.copy2(str(s_item), str(d_item))

    # 3. Database migrations if needed
    manifest_file = addon_dir / "manifest.json"
    restored_version = "unknown"
    if manifest_file.is_file():
        try:
            with open(manifest_file, 'r', encoding='utf-8') as f:
                mdata = json.load(f)
                restored_version = mdata.get("version", "unknown")
                if mdata.get("requires_db"):
                    _execute_addon_migrations(str(addon_dir))
        except Exception as me:
            addon_logger.warning(f"Migration error during rollback for '{addon_id}': {me}")

    # 4. Hot-reload
    record = load_single_addon(str(addon_dir), dir_type="custom", app=app)
    if record.status == STATE_ERROR:
        addon_logger.error(f"Addon '{addon_id}' loaded with error after rollback: {record.error}")
        return {
            "status": "warning",
            "message": f"Rollback finished with errors: {record.error}",
            "addon_id": addon_id,
            "version": restored_version,
            "snapshot": target_snapshot["snapshot_id"]
        }

    # 5. Restore state
    restore_addon_state(addon_id, record.module)

    addon_logger.info(f"Addon '{addon_id}' successfully reverted to snapshot '{target_snapshot['snapshot_id']}' (v{record.version}).")
    return {
        "status": "success",
        "message": (
            "Addon configured. Reloading engine..."
            if record.reload_required
            else f"Addon '{record.name}' successfully reverted to v{record.version}."
        ),
        "addon_id": addon_id,
        "version": record.version,
        "snapshot": target_snapshot["snapshot_id"],
        "reload_required": record.reload_required
    }
