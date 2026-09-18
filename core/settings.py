import json
import logging
from core.db import get_db_connection, execute_sql, init_db

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "store_name": "Open-POS System",
    "store_legal_entity": "Open-POS Retail LLC",
    "store_location": "Local Network",
    "tax_rate": 8.25,
    "currency_symbol": "$",
    "cash_payout_rate": 60.0,
    "credit_payout_rate": 80.0,
    "daily_trade_limit": 10,
    "condition_multipliers": '{"NM": 1.0, "LP": 0.85, "MP": 0.70, "HP": 0.50, "DMG": 0.30}',
    "store_logo_url": "",
    "pinned_tools": '["branding", "database"]',
    "addon_catalog_url": "https://raw.githubusercontent.com/Cave404/Open-POS/main/addons_catalog.json",
    "default_pos_view": "default-retail",
}

def seed_default_settings(force: bool = False) -> None:
    """
    Seeds default configuration settings into the settings table.
    Ensures missing default keys are inserted without overwriting existing user configuration.
    """
    init_db()
    with get_db_connection() as conn:
        for key, val in DEFAULT_SETTINGS.items():
            str_val = json.dumps(val) if isinstance(val, (dict, list)) else str(val)
            if force:
                execute_sql(
                    conn,
                    """
                    INSERT INTO settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT (key) DO UPDATE SET value = excluded.value
                    """,
                    (key, str_val),
                )
            else:
                execute_sql(
                    conn,
                    """
                    INSERT INTO settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    (key, str_val),
                )

def get_setting(key: str, default: any = None) -> any:
    """
    Retrieves a setting by key. Seeds defaults on initial access if empty.
    Casts to default's type if default is provided, or preserves standard types.
    """
    seed_default_settings()
    try:
        with get_db_connection() as conn:
            cur = execute_sql(conn, "SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            if row is None:
                return default
            raw_val = row['value'] if hasattr(row, '__getitem__') and not isinstance(row, tuple) else row[0]
    except Exception as e:
        logger.error(f"Error reading setting '{key}': {e}")
        return default

    if raw_val is None:
        return default

    # If an explicit default of a specific type is provided, cast raw_val to that type
    if default is not None:
        try:
            if isinstance(default, bool):
                return str(raw_val).strip().lower() in ('true', '1', 'yes')
            if isinstance(default, int):
                return int(float(raw_val))
            if isinstance(default, float):
                return float(raw_val)
            if isinstance(default, (dict, list)):
                return json.loads(raw_val) if isinstance(raw_val, str) else raw_val
            if isinstance(default, str):
                return str(raw_val)
        except Exception:
            return default

    # If default is None, convert standard known numeric keys
    if key in ('cash_payout_rate', 'credit_payout_rate', 'tax_rate'):
        try:
            return float(raw_val)
        except (ValueError, TypeError):
            return raw_val
    if key == 'daily_trade_limit':
        try:
            return int(raw_val)
        except (ValueError, TypeError):
            return raw_val

    return raw_val

def set_setting(key: str, value: any) -> bool:
    """
    Persists a setting key-value pair into the database.
    Serializes dicts/lists to JSON strings.
    """
    seed_default_settings()
    if isinstance(value, (dict, list)):
        str_val = json.dumps(value)
    elif value is None:
        str_val = ""
    else:
        str_val = str(value)

    try:
        with get_db_connection() as conn:
            execute_sql(
                conn,
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT (key) DO UPDATE SET value = excluded.value
                """,
                (key, str_val),
            )
        return True
    except Exception as e:
        logger.error(f"Failed to persist setting '{key}': {e}")
        return False

# Convenient alias for set_setting
update_setting = set_setting

def get_all_settings() -> dict:
    """
    Returns a dictionary of all active configuration keys and values.
    """
    seed_default_settings()
    result = {}
    try:
        with get_db_connection() as conn:
            cur = execute_sql(conn, "SELECT key, value FROM settings")
            rows = cur.fetchall()
            for row in rows:
                k = row['key'] if hasattr(row, '__getitem__') and not isinstance(row, tuple) else row[0]
                v = row['value'] if hasattr(row, '__getitem__') and not isinstance(row, tuple) else row[1]

                if k in ('cash_payout_rate', 'credit_payout_rate', 'tax_rate'):
                    try:
                        v = float(v)
                    except (ValueError, TypeError):
                        pass
                elif k == 'daily_trade_limit':
                    try:
                        v = int(v)
                    except (ValueError, TypeError):
                        pass

                result[k] = v
    except Exception as e:
        logger.error(f"Failed to fetch all settings: {e}")
        return dict(DEFAULT_SETTINGS)

    return result
