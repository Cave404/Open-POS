"""
=============================================================================
Open-POS Schema Migration Engine (storage/migrations.py)
=============================================================================
Centralized execution of core database schema migrations for SQLite and PostgreSQL.
Idempotent and resilient across packaged standalone builds and dev environments.
=============================================================================
"""

import os
import logging
from core.config import Config
from storage.database import get_db_connection, execute_sql

logger = logging.getLogger("openpos.storage.migrations")


def _find_migration_file(filename: str) -> str:
    """Resolves migration file in storage/migrations or migrations directory."""
    candidates = [
        os.path.join(Config.BASE_DIR, "storage", "migrations", filename),
        os.path.join(Config.BASE_DIR, "migrations", filename),
        os.path.join(os.path.dirname(__file__), "migrations", filename),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(f"Migration file '{filename}' not found in candidates: {candidates}")


def run_customer_migrations() -> None:
    """Executes customer identity and store credit ledger migrations."""
    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    is_pg = engine in ('postgres', 'postgresql')
    filename = 'core_002_add_customers.pgsql.sql' if is_pg else 'core_002_add_customers.sqlite.sql'

    try:
        sql_path = _find_migration_file(filename)
        with open(sql_path, 'r', encoding='utf-8') as f:
            sql_script = f.read()

        with get_db_connection() as conn:
            if is_pg:
                cur = conn.cursor()
                cur.execute(sql_script)
            else:
                conn.executescript(sql_script)
        logger.info(f"Customer migrations executed successfully from {filename}.")
    except Exception as e:
        logger.error(f"Failed to execute customer migrations: {e}", exc_info=True)
        raise


def run_pos_migrations() -> None:
    """Executes POS register transactions and double-entry ledger migrations."""
    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    is_pg = engine in ('postgres', 'postgresql')
    filename = 'core_003_add_pos_register.pgsql.sql' if is_pg else 'core_003_add_pos_register.sqlite.sql'

    try:
        sql_path = _find_migration_file(filename)
        with open(sql_path, 'r', encoding='utf-8') as f:
            sql_script = f.read()

        with get_db_connection() as conn:
            if is_pg:
                execute_sql(conn, sql_script)
            else:
                conn.executescript(sql_script)
        logger.info(f"POS register migrations executed successfully from {filename}.")
    except Exception as e:
        logger.error(f"Failed to execute POS register migrations: {e}", exc_info=True)
        raise


def run_all_migrations() -> None:
    """Runs all core migrations in topological order."""
    run_customer_migrations()
    run_pos_migrations()
