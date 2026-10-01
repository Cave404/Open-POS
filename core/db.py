"""
=============================================================================
Open-POS Core Database Shim (core/db.py)
=============================================================================
Provides backward-compatible facade re-exporting connection management
from the storage layer (storage/database.py).
=============================================================================
"""

from storage.database import (
    get_db_path,
    get_db_connection,
    execute_sql,
    init_db
)

__all__ = [
    "get_db_path",
    "get_db_connection",
    "execute_sql",
    "init_db"
]
