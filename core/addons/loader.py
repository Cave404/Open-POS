import os
import sys
import json
import logging
import importlib
import importlib.util
import traceback
from typing import Dict, Any, List, Optional, Callable
from flask import Flask, Blueprint, jsonify

from core.config import Config
from core.db import get_db_connection, execute_sql
from core.settings import get_setting, set_setting
from core.notifications import add_alert

logger = logging.getLogger(__name__)

# Addon runtime states
STATE_ACTIVE = "ACTIVE"
STATE_DISABLED = "DISABLED"
STATE_ERROR = "ERROR"

class HookBus:
    """
    In-memory lifecycle event dispatcher for OpenPOS plugins.
    Allows addons to subscribe to core POS actions (e.g. on_sale_complete, on_customer_lookup).
    """
    def __init__(self):
        # event_name -> list of tuples (addon_id, callback)
        self._listeners: Dict[str, List[tuple]] = {}

    def register(self, event_name: str, callback: Callable, addon_id: str) -> None:
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append((addon_id, callback))

    def unregister_for_addon(self, addon_id: str) -> None:
        for event_name in list(self._listeners.keys()):
            self._listeners[event_name] = [
                (aid, cb) for (aid, cb) in self._listeners[event_name] if aid != addon_id
            ]

    def emit(self, event_name: str, *args, **kwargs) -> List[Any]:
        results = []
        listeners = self._listeners.get(event_name, [])
        for addon_id, callback in listeners:
            try:
                res = callback(*args, **kwargs)
                results.append({"addon_id": addon_id, "result": res, "status": "ok"})
            except Exception as e:
                logger.error(f"Error executing hook '{event_name}' for addon '{addon_id}': {e}", exc_info=True)
                results.append({"addon_id": addon_id, "error": str(e), "status": "error"})
        return results


class AddonRecord:
    """
    In-memory record of an inspected addon extension.
    """
    def __init__(self, addon_id: str, manifest: Dict[str, Any], dir_path: str, dir_type: str = "builtin"):
        self.id = addon_id
        self.name = manifest.get("name", addon_id)
        self.version = manifest.get("version", "1.0.0")
        self.author = manifest.get("author", "Unknown")
        self.description = manifest.get("description", "")
        self.category = manifest.get("category", "Desktop_Apps")
        self.icon = manifest.get("icon", "puzzle.png")
        self.entrypoint = manifest.get("entrypoint", "plugin.py")
        self.requires_db = bool(manifest.get("requires_db", False))
        self.min_core_version = manifest.get("min_core_version", "1.0.0")
        self.dependencies = manifest.get("dependencies", [])
        self.settings_route = manifest.get("settings_route", None)
        self.dir_path = dir_path
        self.dir_type = dir_type
        self.manifest = manifest

        self.status = STATE_DISABLED
        self.enabled = True
        self.error: Optional[str] = None
        self.traceback: Optional[str] = None
        self.module = None
        self.blueprint: Optional[Blueprint] = None
        self.hooks: Dict[str, Callable] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "entrypoint": self.entrypoint,
            "requires_db": self.requires_db,
            "min_core_version": self.min_core_version,
            "dependencies": self.dependencies,
            "settings_route": self.settings_route,
            "dir_path": self.dir_path,
            "dir_type": self.dir_type,
            "status": self.status,
            "enabled": self.enabled,
            "error": self.error,
            "traceback": self.traceback,
            "has_settings": bool(self.settings_route),
        }


class AddonManager:
    """
    Central Supervisor for discovering, sandboxing, migrating, and mounting OpenPOS addons.
    Ensures complete failure isolation so corrupted or broken addons cannot crash the core system.
    """
    def __init__(self):
        self.app: Optional[Flask] = None
        self.hook_bus = HookBus()
        self.addons: Dict[str, AddonRecord] = {}
        self._initialized = False

    def init_app(self, app: Flask) -> None:
        """Binds the Flask application instance and executes initial discovery and registration."""
        self.app = app
        self.discover_and_load_all()
        self._initialized = True

    def get_search_directories(self) -> List[tuple]:
        """
        Returns list of (directory_path, dir_type) to scan.
        Scans both built-in Open-POS/addons and user data/custom_addons.
        """
        builtin_dir = os.path.abspath(os.path.join(Config.BASE_DIR, 'addons'))
        custom_dir = getattr(Config, 'CUSTOM_ADDONS_DIR', os.path.join(Config.DATA_DIR, 'custom_addons'))
        return [
            (builtin_dir, "builtin"),
            (custom_dir, "custom")
        ]

    def discover_and_load_all(self) -> Dict[str, AddonRecord]:
        """
        Scans discovery directories, parses manifests, and initializes all discovered addons.
        Isolates failures per addon.
        """
        for scan_dir, dir_type in self.get_search_directories():
            if not os.path.isdir(scan_dir):
                try:
                    os.makedirs(scan_dir, exist_ok=True)
                except Exception as e:
                    logger.warning(f"Could not create addons directory {scan_dir}: {e}")
                continue

            for entry in os.listdir(scan_dir):
                entry_path = os.path.join(scan_dir, entry)
                if not os.path.isdir(entry_path):
                    continue

                manifest_file = os.path.join(entry_path, 'manifest.json')
                if not os.path.isfile(manifest_file):
                    continue

                # Load and initialize the addon in isolation
                self.load_addon(entry_path, dir_type)

        return self.addons

    def load_addon(self, addon_dir: str, dir_type: str = "builtin") -> AddonRecord:
        """
        Loads, validates, migrates, and registers a single addon with full error containment.
        """
        manifest_path = os.path.join(addon_dir, 'manifest.json')
        addon_id = os.path.basename(addon_dir)

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except Exception as e:
            err_msg = f"Invalid manifest.json in {addon_dir}: {e}"
            tb = traceback.format_exc()
            logger.error(err_msg)
            add_alert("ERROR", f"Addon '{addon_id}' failed: Invalid manifest.json", subsystem="ADDONS")
            record = AddonRecord(addon_id, {"id": addon_id, "name": addon_id}, addon_dir, dir_type)
            record.status = STATE_ERROR
            record.error = err_msg
            record.traceback = tb
            self.addons[addon_id] = record
            return record

        addon_id = manifest.get("id", addon_id)
        record = AddonRecord(addon_id, manifest, addon_dir, dir_type)
        self.addons[addon_id] = record

        # Determine configured enabled state from database settings (falls back to manifest default)
        manifest_enabled = manifest.get("enabled", True)
        is_enabled = get_setting(f"addon_enabled_{addon_id}", default=manifest_enabled)
        record.enabled = is_enabled

        # Isolated initialization sandbox
        try:
            self._validate_manifest(manifest)
            self._verify_dependencies(record)

            if record.requires_db:
                self._run_migrations(record)

            self._mount_blueprint(record)
            self._register_hooks(record)

            if record.enabled:
                record.status = STATE_ACTIVE
            else:
                record.status = STATE_DISABLED
                self.hook_bus.unregister_for_addon(addon_id)

            logger.info(f"Addon '{addon_id}' loaded successfully (status: {record.status}).")

        except Exception as e:
            tb = traceback.format_exc()
            err_msg = str(e)
            record.status = STATE_ERROR
            record.error = err_msg
            record.traceback = tb
            logger.error(f"Error initializing addon '{addon_id}': {err_msg}\n{tb}")
            add_alert("ERROR", f"Addon '{addon_id}' failed: {err_msg}", subsystem="ADDONS")
            self.hook_bus.unregister_for_addon(addon_id)

        return record

    def _validate_manifest(self, manifest: Dict[str, Any]) -> None:
        """Validates the addon manifest schema against the OpenPOS Addon Specification."""
        required_fields = ["id", "name", "version", "entrypoint"]
        for field in required_fields:
            if not manifest.get(field):
                raise ValueError(f"Manifest missing required contract field '{field}'")

    def _verify_dependencies(self, record: AddonRecord) -> None:
        """Verifies that all third-party Python modules specified in dependencies can be imported."""
        for dep in record.dependencies:
            dep_clean = dep.strip()
            if not dep_clean:
                continue
            try:
                importlib.import_module(dep_clean)
            except Exception as err:
                raise RuntimeError(f"Missing or broken Python dependency '{dep_clean}': {err}")

    def _run_migrations(self, record: AddonRecord) -> None:
        """
        Executes database-agnostic schema migrations for the addon.
        Supports schema_sqlite.sql and schema_postgres.sql in <addon_dir>/migrations/.
        """
        migrations_dir = os.path.join(record.dir_path, 'migrations')
        if not os.path.isdir(migrations_dir):
            return

        engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
        if engine in ('postgres', 'postgresql'):
            sql_filename = 'schema_postgres.sql'
        else:
            sql_filename = 'schema_sqlite.sql'

        sql_path = os.path.join(migrations_dir, sql_filename)
        if not os.path.isfile(sql_path):
            # Also check fallback schema.sql if engine-specific file is absent
            fallback_path = os.path.join(migrations_dir, 'schema.sql')
            if os.path.isfile(fallback_path):
                sql_path = fallback_path
            else:
                return

        logger.info(f"Running database migration for addon '{record.id}' using {sql_filename}...")
        try:
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

            logger.info(f"Addon '{record.id}' migrations executed successfully.")
        except Exception as e:
            raise RuntimeError(f"Migration script '{sql_filename}' failed for addon '{record.id}': {e}")

    def _mount_blueprint(self, record: AddonRecord) -> None:
        """
        Dynamically imports the entrypoint file and mounts its Flask Blueprint under /addons/<addon_id>/.
        Adds an automatic enabled-status guard to return 503 if the addon is toggled off.
        """
        entrypoint_file = os.path.join(record.dir_path, record.entrypoint)
        if not os.path.isfile(entrypoint_file):
            raise FileNotFoundError(f"Addon entrypoint file '{record.entrypoint}' not found at {entrypoint_file}")

        module_name = f"openpos_addon_{record.id}"
        spec = importlib.util.spec_from_file_location(module_name, entrypoint_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for '{entrypoint_file}'")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        # Execute entrypoint module in isolated namespace
        spec.loader.exec_module(module)
        record.module = module

        # Locate Flask Blueprint
        bp = None
        if hasattr(module, 'blueprint') and isinstance(module.blueprint, Blueprint):
            bp = module.blueprint
        elif hasattr(module, 'bp') and isinstance(module.bp, Blueprint):
            bp = module.bp
        elif hasattr(module, 'get_blueprint') and callable(module.get_blueprint):
            candidate = module.get_blueprint()
            if isinstance(candidate, Blueprint):
                bp = candidate

        if bp is not None:
            record.blueprint = bp

            # Guard: check if addon is active before handling request
            addon_id = record.id
            def make_guard(a_id):
                def _guard():
                    rec = self.addons.get(a_id)
                    if rec and rec.status != STATE_ACTIVE:
                        return jsonify({
                            "error": f"Addon '{a_id}' is currently disabled.",
                            "status": "disabled"
                        }), 503
                return _guard

            bp.before_request(make_guard(addon_id))

            # Register on Flask app if bound
            if self.app is not None:
                # Check if blueprint is already registered
                if bp.name not in self.app.blueprints:
                    prefix = f"/addons/{record.id}"
                    was_handled = getattr(self.app, '_got_first_request', False)
                    if was_handled:
                        self.app._got_first_request = False
                    try:
                        self.app.register_blueprint(bp, url_prefix=prefix)
                        logger.info(f"Mounted blueprint '{bp.name}' for addon '{record.id}' at '{prefix}'.")
                    except Exception as bpe:
                        logger.warning(f"Could not register dynamic blueprint '{bp.name}' directly: {bpe}")
                    finally:
                        if was_handled:
                            self.app._got_first_request = True

    def _register_hooks(self, record: AddonRecord) -> None:
        """Extracts and registers lifecycle hook listeners defined in the addon entrypoint."""
        if not record.module:
            return

        # Clear any existing hooks for this addon
        self.hook_bus.unregister_for_addon(record.id)
        record.hooks = {}

        if hasattr(record.module, 'hooks') and isinstance(record.module.hooks, dict):
            for event_name, cb in record.module.hooks.items():
                if callable(cb):
                    self.hook_bus.register(event_name, cb, record.id)
                    record.hooks[event_name] = cb
        elif hasattr(record.module, 'register_hooks') and callable(record.module.register_hooks):
            record.module.register_hooks(self.hook_bus)

    def is_addon_active(self, addon_id: str) -> bool:
        """Returns True if the addon is loaded and actively enabled."""
        rec = self.addons.get(addon_id)
        return rec is not None and rec.status == STATE_ACTIVE

    def toggle_addon(self, addon_id: str, enable: bool) -> Dict[str, Any]:
        """
        Toggles an addon's enabled state, updates database persistence,
        and synchronizes hooks and status without restarting the server.
        """
        rec = self.addons.get(addon_id)
        if not rec:
            return {"success": False, "error": f"Addon '{addon_id}' not found."}

        # Persist toggle to database settings
        set_setting(f"addon_enabled_{addon_id}", enable)
        rec.enabled = enable

        if enable:
            if rec.status == STATE_ERROR:
                # Attempt to reload if it was in error
                return self.reload_addon(addon_id)
            else:
                rec.status = STATE_ACTIVE
                self._register_hooks(rec)
        else:
            rec.status = STATE_DISABLED
            self.hook_bus.unregister_for_addon(addon_id)

        return {
            "success": True,
            "id": addon_id,
            "status": rec.status,
            "enabled": rec.enabled
        }

    def reload_addon(self, addon_id: str) -> Dict[str, Any]:
        """Attempts to re-read manifest, re-import module, and recover an addon."""
        rec = self.addons.get(addon_id)
        if not rec:
            return {"success": False, "error": f"Addon '{addon_id}' not found."}

        # Clear existing hooks
        self.hook_bus.unregister_for_addon(addon_id)

        # Re-load
        updated = self.load_addon(rec.dir_path, rec.dir_type)
        return {
            "success": updated.status != STATE_ERROR,
            "id": addon_id,
            "status": updated.status,
            "enabled": updated.enabled,
            "error": updated.error
        }

    def get_all_addons(self) -> List[Dict[str, Any]]:
        """Returns a serialized list of all discovered addons."""
        return [record.to_dict() for record in self.addons.values()]

    def get_addon(self, addon_id: str) -> Optional[Dict[str, Any]]:
        """Returns a single serialized addon record or None."""
        rec = self.addons.get(addon_id)
        return rec.to_dict() if rec else None

    def emit_hook(self, event_name: str, *args, **kwargs) -> List[Any]:
        """Dispatches an event to all active subscribed addon listeners."""
        return self.hook_bus.emit(event_name, *args, **kwargs)

    def import_addon_zip(self, zip_source) -> Dict[str, Any]:
        """
        Extracts a .zip archive containing an addon extension, validates manifest.json,
        installs it into data/custom_addons/<addon_id>/, and mounts it into the runtime engine.
        """
        import zipfile
        import shutil

        try:
            with zipfile.ZipFile(zip_source, 'r') as zf:
                namelist = zf.namelist()
                manifest_entry = None
                prefix = ""
                for name in namelist:
                    parts = name.replace('\\', '/').split('/')
                    if parts[-1] == 'manifest.json':
                        manifest_entry = name
                        prefix = "/".join(parts[:-1])
                        if prefix:
                            prefix += "/"
                        break

                if not manifest_entry:
                    return {"success": False, "error": "Invalid addon package: manifest.json not found in ZIP archive."}

                try:
                    with zf.open(manifest_entry) as mf:
                        manifest_data = json.load(mf)
                except Exception as je:
                    return {"success": False, "error": f"Invalid manifest.json in ZIP archive: {je}"}

                self._validate_manifest(manifest_data)
                addon_id = manifest_data['id']

                custom_dir = getattr(Config, 'CUSTOM_ADDONS_DIR', os.path.join(Config.DATA_DIR, 'custom_addons'))
                os.makedirs(custom_dir, exist_ok=True)
                target_dir = os.path.join(custom_dir, addon_id)

                if os.path.isdir(target_dir):
                    shutil.rmtree(target_dir, ignore_errors=True)
                os.makedirs(target_dir, exist_ok=True)

                # Extract files with zip-slip path traversal prevention
                resolved_target = os.path.realpath(target_dir)
                for member in zf.infolist():
                    member_path = member.filename.replace('\\', '/')
                    if prefix and member_path.startswith(prefix):
                        rel_path = member_path[len(prefix):]
                    else:
                        rel_path = member_path

                    if not rel_path or rel_path.endswith('/'):
                        continue

                    dest_file = os.path.join(target_dir, *rel_path.split('/'))
                    dest_real = os.path.realpath(dest_file)
                    if not (dest_real == resolved_target or dest_real.startswith(resolved_target + os.sep)):
                        continue

                    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                    with zf.open(member) as src, open(dest_file, 'wb') as dst:
                        shutil.copyfileobj(src, dst)

                # Load into runtime
                record = self.load_addon(target_dir, dir_type="custom")
                return {
                    "success": record.status != STATE_ERROR,
                    "id": addon_id,
                    "name": record.name,
                    "status": record.status,
                    "error": record.error,
                    "message": f"Addon '{record.name}' installed successfully."
                }

        except Exception as e:
            logger.error(f"Failed to import addon ZIP: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def uninstall_addon(self, addon_id: str) -> Dict[str, Any]:
        """
        Uninstalls and safely deletes a custom addon from data/custom_addons/.
        Protects built-in core addons from deletion.
        """
        import shutil

        rec = self.addons.get(addon_id)
        if not rec:
            return {"success": False, "error": f"Addon '{addon_id}' not found."}

        if rec.dir_type != "custom":
            return {
                "success": False,
                "error": f"Cannot remove built-in core addon '{rec.name}'. You can disable it using the toggle instead."
            }

        # Unregister hooks
        self.hook_bus.unregister_for_addon(addon_id)

        # Remove files
        if os.path.isdir(rec.dir_path):
            try:
                shutil.rmtree(rec.dir_path, ignore_errors=True)
            except Exception as e:
                return {"success": False, "error": f"Failed to delete directory: {e}"}

        # Purge from registry
        self.addons.pop(addon_id, None)

        return {
            "success": True,
            "id": addon_id,
            "message": f"Addon '{rec.name}' has been uninstalled successfully."
        }


# Global singleton instance
addon_manager = AddonManager()
