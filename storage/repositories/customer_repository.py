"""
=============================================================================
Open-POS Customer Repository (storage/repositories/customer_repository.py)
=============================================================================
Abstracts database access for customer records, NFC badge associations,
and store credit ledgers. Eliminates raw SQL execution from presentation routes.
=============================================================================
"""

import logging
from typing import Optional, Dict, Any, List
from storage.database import get_db_connection

logger = logging.getLogger("openpos.storage.customer_repository")


def _ensure_schema(conn):
    """Ensures customer_credit_log table and synchronized store_credit columns exist."""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customer_credit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                delta REAL,
                balance_after REAL,
                reason TEXT,
                source_addon TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Verify table info for customers
        cur.execute("PRAGMA table_info(customers)")
        cols = {row[1] for row in cur.fetchall()}
        if cols:
            if "store_credit" not in cols and "store_credit_balance" in cols:
                conn.execute("ALTER TABLE customers ADD COLUMN store_credit REAL DEFAULT 0.0")
                conn.execute("UPDATE customers SET store_credit = COALESCE(store_credit_balance, 0.0)")
            elif "store_credit_balance" not in cols and "store_credit" in cols:
                conn.execute("ALTER TABLE customers ADD COLUMN store_credit_balance REAL DEFAULT 0.0")
                conn.execute("UPDATE customers SET store_credit_balance = COALESCE(store_credit, 0.0)")
    except Exception as e:
        logger.debug(f"CustomerRepository schema sync note: {e}")


class CustomerRepository:
    @staticmethod
    def get_by_id(customer_id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            _ensure_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, phone, nfc_uid, store_credit, created_at FROM customers WHERE id = ?",
                (customer_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            if "store_credit_balance" not in res and "store_credit" in res:
                res["store_credit_balance"] = res["store_credit"]
            return res

    @staticmethod
    def get_by_nfc(nfc_uid: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            _ensure_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, phone, nfc_uid, store_credit FROM customers WHERE nfc_uid = ?",
                (nfc_uid,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            if "store_credit_balance" not in res and "store_credit" in res:
                res["store_credit_balance"] = res["store_credit"]
            return res

    @staticmethod
    def adjust_store_credit(customer_id: str, delta: float, reason: str, source_addon: Optional[str] = None) -> float:
        with get_db_connection() as conn:
            _ensure_schema(conn)
            cursor = conn.cursor()
            cursor.execute("SELECT store_credit FROM customers WHERE id = ?", (customer_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Customer {customer_id} not found.")

            current_val = row["store_credit"]
            if current_val is None:
                current_val = 0.0
            new_balance = round(float(current_val) + delta, 2)
            if new_balance < 0:
                raise ValueError("Insufficient store credit balance.")

            # Update store_credit column
            cursor.execute("UPDATE customers SET store_credit = ? WHERE id = ?", (new_balance, customer_id))
            # Also keep store_credit_balance in sync if present
            try:
                cursor.execute("UPDATE customers SET store_credit_balance = ? WHERE id = ?", (new_balance, customer_id))
            except Exception:
                pass

            cursor.execute(
                "INSERT INTO customer_credit_log (customer_id, delta, balance_after, reason, source_addon, timestamp) VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (customer_id, delta, new_balance, reason, source_addon)
            )

            # Also write to append-only customer_credit_ledger if it exists
            try:
                txn_type = "ADJUSTMENT" if delta >= 0 else "REDEMPTION"
                cursor.execute(
                    """
                    INSERT INTO customer_credit_ledger
                        (customer_id, amount, balance_after, transaction_type, source_addon, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (customer_id, abs(delta), new_balance, txn_type, source_addon or "core", reason)
                )
            except Exception:
                pass

            conn.commit()
            return new_balance

    @staticmethod
    def list_all(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            _ensure_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, phone, email, nfc_uid, store_credit, created_at FROM customers ORDER BY name ASC LIMIT ? OFFSET ?",
                (limit, offset)
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def search(query_str: str, limit: int = 20) -> List[Dict[str, Any]]:
        pattern = f"%{query_str}%"
        with get_db_connection() as conn:
            _ensure_schema(conn)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, phone, email, nfc_uid, store_credit, created_at
                FROM customers
                WHERE name LIKE ? OR phone LIKE ? OR email LIKE ? OR nfc_uid = ?
                LIMIT ?
                """,
                (pattern, pattern, pattern, query_str.strip().upper(), limit)
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
