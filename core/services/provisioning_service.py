"""
=============================================================================
Open-POS Silent Headless Provisioning Engine (core/services/provisioning_service.py)
=============================================================================
Performs unattended, non-interactive initialization of OpenPOS store settings,
administrative credentials, and database migrations for native installer hooks
and automated setups.
=============================================================================
"""

import os
import json
import logging
from core.config import Config
from core.services.security_service import set_admin_pin
from storage.migrations import run_sqlite_migrations, run_all_migrations

logger = logging.getLogger("openpos.provisioning")


def run_headless_provisioning(store_name: str, admin_pin: str, db_engine: str = "sqlite") -> bool:
    """Provisions database, branding, and manager security without loading a GUI."""
    try:
        Config.init_directories()

        # 1. Save store identity and engine preferences
        config_dir = os.path.join(Config.DATA_DIR, "config")
        os.makedirs(config_dir, exist_ok=True)
        settings_path = os.path.join(config_dir, "store_settings.json")
        clean_store_name = str(store_name).strip() if store_name else "OpenPOS Store"
        clean_engine = str(db_engine).lower().strip() if db_engine else "sqlite"

        settings_data = {
            "store_name": clean_store_name,
            "receipt_header": clean_store_name,
            "currency_symbol": "$",
            "database_engine": clean_engine
        }
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings_data, f, indent=2)

        # 2. Set master administrative PIN
        if admin_pin and str(admin_pin).strip():
            set_admin_pin(str(admin_pin).strip())

        # 3. Initialize SQLite database schema and run migrations
        if clean_engine == "sqlite":
            db_dir = os.path.join(Config.DATA_DIR, "db")
            os.makedirs(db_dir, exist_ok=True)
            db_paths = [
                os.path.join(db_dir, "openpos.sqlite"),
                getattr(Config, "DB_PATH", os.path.join(db_dir, "pos_store.db"))
            ]
            for target_path in set(db_paths):
                try:
                    run_sqlite_migrations(target_path)
                except Exception as me:
                    logger.warning(f"SQLite migration on {target_path}: {me}")
            try:
                run_all_migrations()
            except Exception as ae:
                logger.warning(f"Core migrations execution: {ae}")

        # 4. Write completion sentinel
        sentinel_path = os.path.join(config_dir, ".setup_complete")
        with open(sentinel_path, "w", encoding="utf-8") as f:
            f.write("PROVISIONED_VIA_INNO_SETUP\n")

        logger.info("Store headless provisioning completed successfully.")
        return True
    except Exception as err:
        logger.error(f"Headless provisioning failed: {err}", exc_info=True)
        return False
