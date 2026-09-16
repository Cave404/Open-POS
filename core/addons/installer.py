"""
Open-POS Remote Addon Network Downloader & Unpack Pipeline
Handles fetching remote addon packages, verifying core compatibility,
extracting to untracked data/custom_addons/<id>/, running schema migrations,
and dynamically mounting blueprints.
"""

import os
import json
import shutil
import logging
import zipfile
from typing import Dict, Any
import requests

from core.config import Config
from core.db import get_db_connection
from core.addons.catalog import get_catalog_item, fetch_catalog, is_compatible
from core.addons.loader import addon_manager, load_single_addon, STATE_ERROR

logger = logging.getLogger(__name__)


def _execute_addon_migrations(addon_dir: str) -> None:
    """
    Executes database-agnostic schema migrations for the addon prior to mounting.
    Detects active engine via Config.DB_ENGINE (sqlite vs postgres).
    """
    migrations_dir = os.path.join(addon_dir, 'migrations')
    if not os.path.isdir(migrations_dir):
        return

    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    if engine in ('postgres', 'postgresql'):
        sql_filename = 'schema_postgres.sql'
    else:
        sql_filename = 'schema_sqlite.sql'

    sql_path = os.path.join(migrations_dir, sql_filename)
    if not os.path.isfile(sql_path):
        fallback_path = os.path.join(migrations_dir, 'schema.sql')
        if os.path.isfile(fallback_path):
            sql_path = fallback_path
        else:
            return

    logger.info(f"Executing database migration {sql_filename} in {addon_dir}...")
    with open(sql_path, 'r', encoding='utf-8') as f:
        sql_content = f.read().strip()

    if not sql_content:
        return

    with get_db_connection() as conn:
        if hasattr(conn, 'executescript'):
            conn.executescript(sql_content)
        else:
            cur = conn.cursor()
            cur.execute(sql_content)
    logger.info(f"Database migration completed successfully for {sql_filename}.")


def extract_addon_zip(zip_path: str, target_dir: str) -> Dict[str, Any]:
    """
    Extracts an addon zip archive with GitHub wrapper folder flattening:
    1. Extracts into a temporary staging folder in data/cache/temp_extract/.
    2. Inspects the extracted contents:
       - If root contains a single directory (e.g., Open-POS-TCG-main/) and it contains manifest.json:
         Moves the contents of that inner directory directly into target_dir.
       - If manifest.json is already at the root of temp_extract:
         Moves all files directly into target_dir.
    3. Cleans up temp_extract.
    """
    cache_dir = getattr(Config, 'CACHE_DIR', os.path.join(Config.DATA_DIR, 'cache'))
    temp_extract = os.path.join(cache_dir, f"temp_extract_{os.getpid()}")
    if os.path.isdir(temp_extract):
        shutil.rmtree(temp_extract, ignore_errors=True)
    os.makedirs(temp_extract, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            resolved_staging = os.path.realpath(temp_extract)
            for member in zf.infolist():
                member_path = member.filename.replace('\\', '/')
                dest_file = os.path.join(temp_extract, *member_path.split('/'))
                dest_real = os.path.realpath(dest_file)
                # Zip-slip path traversal guard
                if not (dest_real == resolved_staging or dest_real.startswith(resolved_staging + os.sep)):
                    continue
                if member.is_dir():
                    os.makedirs(dest_file, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                    with zf.open(member) as src, open(dest_file, 'wb') as dst:
                        shutil.copyfileobj(src, dst)

        # Inspect temp_extract structure
        entries = [e for e in os.listdir(temp_extract) if not e.startswith('.')]
        source_dir = temp_extract

        if len(entries) == 1:
            single_entry = os.path.join(temp_extract, entries[0])
            if os.path.isdir(single_entry) and os.path.isfile(os.path.join(single_entry, 'manifest.json')):
                source_dir = single_entry
        elif not os.path.isfile(os.path.join(temp_extract, 'manifest.json')):
            for entry in entries:
                sub = os.path.join(temp_extract, entry)
                if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, 'manifest.json')):
                    source_dir = sub
                    break

        manifest_file = os.path.join(source_dir, 'manifest.json')
        if not os.path.isfile(manifest_file):
            return {
                "status": "error",
                "message": "Invalid addon package: manifest.json not found in ZIP archive."
            }

        try:
            with open(manifest_file, 'r', encoding='utf-8') as mf:
                manifest_data = json.load(mf)
        except Exception as je:
            return {
                "status": "error",
                "message": f"Invalid manifest.json inside ZIP archive: {je}"
            }

        # Clear target_dir and move files
        if os.path.isdir(target_dir):
            shutil.rmtree(target_dir, ignore_errors=True)
        os.makedirs(target_dir, exist_ok=True)

        for item in os.listdir(source_dir):
            src_item = os.path.join(source_dir, item)
            dst_item = os.path.join(target_dir, item)
            shutil.move(src_item, dst_item)

        return {
            "status": "success",
            "manifest": manifest_data,
            "target_dir": target_dir
        }

    finally:
        if os.path.isdir(temp_extract):
            shutil.rmtree(temp_extract, ignore_errors=True)


def install_remote_addon(addon_id: str) -> Dict[str, Any]:
    """
    Installs a remote addon by ID from the catalog:
    1. Fetches catalog entry and validates min_core_version.
    2. Downloads the .zip package to a temporary cache file.
    3. Unpacks and flattens archive to data/custom_addons/<addon_id>/ via extract_addon_zip().
    4. Executes schema migrations if requires_db is True.
    5. Dynamically registers addon via core.addons.loader.load_single_addon().
    6. Cleans up temp download file.
    """
    # 1. Fetch catalog entry
    item = get_catalog_item(addon_id)
    if not item:
        fetch_catalog(force_refresh=True)
        item = get_catalog_item(addon_id)

    if not item:
        return {
            "status": "error",
            "message": f"Addon '{addon_id}' not found in the remote addon catalog."
        }

    # 2. Check version compatibility
    min_ver = item.get("min_core_version", "1.0.0")
    if not is_compatible(min_ver, Config.VERSION):
        return {
            "status": "error",
            "message": f"Addon '{item.get('name', addon_id)}' requires OpenPOS {min_ver} or higher (current: {Config.VERSION})."
        }

    download_url = item.get("download_url")
    if not download_url:
        return {
            "status": "error",
            "message": f"Addon '{addon_id}' does not specify a valid download_url."
        }

    # 3. Stream download the .zip archive to data/cache/
    cache_dir = getattr(Config, 'CACHE_DIR', os.path.join(Config.DATA_DIR, 'cache'))
    os.makedirs(cache_dir, exist_ok=True)
    temp_zip_path = os.path.join(cache_dir, f"temp_{addon_id}_{os.getpid()}.zip")

    try:
        logger.info(f"Downloading addon '{addon_id}' from {download_url}...")
        resp = requests.get(download_url, stream=True, timeout=20)
        if resp.status_code != 200:
            return {
                "status": "error",
                "message": f"Failed to download addon package from {download_url} (HTTP {resp.status_code})."
            }

        with open(temp_zip_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    except Exception as e:
        logger.error(f"Error downloading addon package: {e}", exc_info=True)
        if os.path.isfile(temp_zip_path):
            try:
                os.remove(temp_zip_path)
            except Exception:
                pass
        return {
            "status": "error",
            "message": f"Network error downloading addon: {str(e)}"
        }

    # 4. Extract and flatten to data/custom_addons/<addon_id>/
    custom_dir = getattr(Config, 'CUSTOM_ADDONS_DIR', os.path.join(Config.DATA_DIR, 'custom_addons'))
    os.makedirs(custom_dir, exist_ok=True)
    target_dir = os.path.join(custom_dir, addon_id)

    try:
        extract_res = extract_addon_zip(temp_zip_path, target_dir)
        if extract_res.get("status") != "success":
            return extract_res

        manifest_data = extract_res.get("manifest", {})

        # 5. Database migrations if declared in manifest or catalog
        requires_db = bool(manifest_data.get("requires_db", item.get("requires_db", False)))
        if requires_db:
            try:
                _execute_addon_migrations(target_dir)
            except Exception as me:
                logger.error(f"Migration error for {addon_id}: {me}", exc_info=True)
                return {
                    "status": "error",
                    "message": f"Database migration failed: {str(me)}"
                }

        # 6. Dynamically register via core.addons.loader.load_single_addon()
        record = load_single_addon(target_dir, dir_type="custom")
        if record.status == STATE_ERROR:
            return {
                "status": "error",
                "message": f"Addon installed but failed to initialize: {record.error}"
            }

        return {
            "status": "success",
            "message": f"{addon_id} installed and activated successfully",
            "addon_id": addon_id,
            "version": record.version
        }

    except Exception as exc:
        logger.error(f"Failed to unpack/install addon '{addon_id}': {exc}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to install addon '{addon_id}': {str(exc)}"
        }
    finally:
        # 7. Clean up downloaded temp zip
        if os.path.isfile(temp_zip_path):
            try:
                os.remove(temp_zip_path)
            except Exception:
                pass

