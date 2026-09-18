"""
core/services/settings_service.py
==================================
File-backed store configuration and preferences management service.
Synchronizes file-based preferences in data/config/store_settings.json
with the primary SQLite Open-POS database.
"""

import os
import json
import logging
from typing import Dict, Any, Optional

from core.config import Config
from core.settings import get_setting as core_get_setting, set_setting as core_set_setting

logger = logging.getLogger(__name__)

DEFAULT_STORE_CONFIG: Dict[str, Any] = {
    "default_pos_view": "default-retail",
    "store_name": "Open-POS System",
    "store_legal_entity": "Open-POS Retail LLC",
    "store_location": "Local Network",
    "tax_rate": 8.25,
    "currency_symbol": "$"
}


def get_config_file_path() -> str:
    """Returns absolute path to store_settings.json."""
    config_dir = getattr(Config, 'CONFIG_DIR', os.path.join(Config.DATA_DIR, 'config'))
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, 'store_settings.json')


def get_store_settings() -> Dict[str, Any]:
    """
    Loads configuration from data/config/store_settings.json.
    Ensures all default keys exist and falls back safely if the file is missing or corrupted.
    """
    file_path = get_config_file_path()
    settings = dict(DEFAULT_STORE_CONFIG)

    if os.path.isfile(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    settings.update(data)
        except Exception as err:
            logger.error(f"[SETTINGS_SERVICE] Failed to parse {file_path}: {err}", exc_info=True)

    # Sync default_pos_view from database if available
    db_default_view = core_get_setting("default_pos_view", None)
    if db_default_view and "default_pos_view" not in settings:
        settings["default_pos_view"] = db_default_view

    return settings


def save_store_settings(settings: Dict[str, Any]) -> bool:
    """
    Saves given dictionary into data/config/store_settings.json,
    and synchronizes key settings with the database.
    """
    file_path = get_config_file_path()
    try:
        current = get_store_settings()
        current.update(settings)

        # Write to disk atomically / safely
        temp_path = f"{file_path}.tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(current, f, indent=2)
        os.replace(temp_path, file_path)

        # Synchronize default_pos_view to database
        if "default_pos_view" in current:
            core_set_setting("default_pos_view", str(current["default_pos_view"]))

        return True
    except Exception as err:
        logger.error(f"[SETTINGS_SERVICE] Failed to save {file_path}: {err}", exc_info=True)
        return False


def get_setting(key: str, default: Any = None) -> Any:
    """
    Retrieves a setting by key from store_settings.json,
    falling back to SQLite settings if not found in file.
    """
    settings = get_store_settings()
    if key in settings:
        return settings[key]
    return core_get_setting(key, default)


def set_setting(key: str, value: Any) -> bool:
    """
    Sets a setting key-value pair and persists it both to store_settings.json and database.
    """
    settings = get_store_settings()
    settings[key] = value
    saved_file = save_store_settings(settings)
    saved_db = core_set_setting(key, str(value) if not isinstance(value, (dict, list)) else json.dumps(value))
    return saved_file and saved_db


def get_default_pos_view() -> str:
    """Returns the configured default register view (e.g. 'default-retail' or an addon ID)."""
    return str(get_setting("default_pos_view", "default-retail"))


def set_default_pos_view(view_id: str) -> bool:
    """Updates the default register view."""
    return set_setting("default_pos_view", view_id)
