"""
=============================================================================
Open-POS Centralized Storage Database Layer (storage/database.py)
=============================================================================
Provides centralized, thread-safe connection management for SQLite and PostgreSQL.
Implements the get_db_connection() context manager with automatic rollback
on unhandled exceptions and explicit commit upon success.
=============================================================================
"""

import os
import sqlite3
import threading
import logging
from contextlib import contextmanager
from typing import Optional, Any
from core.config import Config

logger = logging.getLogger("openpos.storage.database")

_db_lock = threading.RLock()


def get_db_path() -> str:
    """Resolves filesystem path to active SQLite database file."""
    db_name = getattr(Config, 'DB_NAME', 'pos_store.db')
    if db_name == ':memory:' or os.path.isabs(db_name):
        return db_name
    db_path = getattr(Config, 'DB_PATH', None)
    if db_path and os.path.isabs(db_path):
        return db_path
    return os.path.join(Config.DB_DIR, db_name)


@contextmanager
def get_db_connection():
    """
    Centralized, thread-safe connection context manager for SQLite and PostgreSQL.
    Ensures safe transaction boundaries: commits on clean exit, rolls back on exceptions.
    """
    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    conn = None
    try:
        if engine in ('postgres', 'postgresql'):
            import psycopg
            from psycopg.rows import dict_row
            conn = psycopg.connect(
                host=Config.DB_HOST,
                port=Config.DB_PORT,
                dbname=Config.DB_NAME,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                row_factory=dict_row
            )
        else:
            db_path = get_db_path()
            # Ensure parent directory exists
            if db_path != ':memory:':
                os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10.0)
            conn.row_factory = sqlite3.Row

        yield conn
        conn.commit()
    except Exception as exc:
        if conn:
            try:
                conn.rollback()
            except Exception as rbe:
                logger.error(f"Failed to rollback connection: {rbe}")
        raise exc
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def execute_sql(conn, sql: str, params: tuple = ()) -> Any:
    """
    Executes a SQL query adapting placeholders for SQLite (?) or PostgreSQL (%s).
    """
    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    if engine in ('postgres', 'postgresql'):
        sql = sql.replace('?', '%s')
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def init_db() -> None:
    """
    Initializes primary system settings and metadata tables.
    """
    with get_db_connection() as conn:
        execute_sql(conn, '''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        ''')
