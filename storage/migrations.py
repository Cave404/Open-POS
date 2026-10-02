"""
=============================================================================
Open-POS Schema Migration Engine (storage/migrations.py)
=============================================================================
Centralized execution of core database schema migrations for SQLite and PostgreSQL.
Idempotent and resilient across packaged standalone builds and dev environments.
Includes automated pre-migration SQLite snapshot protection.
=============================================================================
"""

import os
import shutil
import sqlite3
import logging
from datetime import datetime
from typing import Optional
from core.config import Config
from storage.database import get_db_connection, execute_sql

logger = logging.getLogger("openpos.storage.migrations")


def snapshot_database_before_migration(db_path: str, target_migration_version: str) -> str:
    """Creates a timestamped snapshot of the active SQLite database prior to running migrations."""
    if not os.path.exists(db_path):
        return ""

    backup_dir = os.path.join(Config.DATA_DIR, "backups", "db_migrations")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    version_tag = target_migration_version.lstrip("v")
    backup_filename = f"db_pre_v{version_tag}_{timestamp}.sqlite"
    backup_path = os.path.join(backup_dir, backup_filename)

    try:
        shutil.copy2(db_path, backup_path)
        logger.info(f"Database pre-migration snapshot created at: {backup_path}")
        return backup_path
    except Exception as e:
        logger.error(f"Failed to create database snapshot before migration: {e}")
        raise RuntimeError(f"Database migration aborted: unable to create safety backup: {e}")


def run_sqlite_migrations(db_path: str) -> None:
    """Executes pending SQLite migrations with automated snapshot protection."""
    migrations_dir = os.path.join(Config.BASE_DIR, "storage", "migrations")
    if not os.path.exists(migrations_dir):
        return

    # Scan for migration files (.sql) targeting SQLite
    migration_files = sorted([
        f for f in os.listdir(migrations_dir)
        if f.endswith(".sqlite.sql") or (f.endswith(".sql") and ".pgsql." not in f)
    ])
    if not migration_files:
        return

    # Snapshot current database before executing migration batch
    snapshot_database_before_migration(db_path, Config.VERSION)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at DATETIME)")
        cursor.execute("SELECT version FROM schema_migrations")
        applied = {row[0] for row in cursor.fetchall()}

        for m_file in migration_files:
            if m_file not in applied:
                logger.info(f"Applying database migration: {m_file}")
                with open(os.path.join(migrations_dir, m_file), "r", encoding="utf-8") as f:
                    cursor.executescript(f.read())
                cursor.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))", (m_file,))
                conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Migration failed on {db_path}: {e}")
        raise
    finally:
        conn.close()


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

    if not is_pg:
        db_path = getattr(Config, 'DB_PATH', None)
        if db_path and os.path.exists(db_path):
            try:
                snapshot_database_before_migration(db_path, Config.VERSION)
            except Exception as se:
                logger.warning(f"Pre-migration snapshot skipped or failed: {se}")

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
