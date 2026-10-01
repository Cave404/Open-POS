"""
=============================================================================
Open-POS Storage Subsystem Layer (storage/)
=============================================================================
Centralized database connection management, migrations, and repository abstractions:
  - storage.database: Thread-safe SQLite / PostgreSQL connection context manager.
  - storage.migrations: Schema migrations executor.
  - storage.repositories: Customer, Ledger, and Product repositories.
=============================================================================
"""

from storage.database import get_db_connection, execute_sql, get_db_path, init_db
from storage.migrations import run_customer_migrations, run_pos_migrations, run_all_migrations
from storage.repositories.customer_repository import CustomerRepository
from storage.repositories.ledger_repository import LedgerRepository
from storage.repositories.product_repository import ProductRepository

__all__ = [
    "get_db_connection",
    "execute_sql",
    "get_db_path",
    "init_db",
    "run_customer_migrations",
    "run_pos_migrations",
    "run_all_migrations",
    "CustomerRepository",
    "LedgerRepository",
    "ProductRepository",
]
