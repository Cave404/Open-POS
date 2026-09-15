"""
core/services/customer_service.py
==================================
Atomic business logic for the Customer Management subsystem.

All database interactions go through core.db.get_db_connection() /
core.db.execute_sql() — never raw ORM calls. Financial operations
(deposit / redeem) use BEGIN IMMEDIATE on SQLite (or FOR UPDATE on
PostgreSQL) to prevent double-spending races.

Financial Invariant
-------------------
The ``customer_credit_ledger`` table is strictly append-only.
No function in this module issues UPDATE or DELETE against ledger rows.
"""
from __future__ import annotations

import os
import re
import logging
from typing import Optional

from core.config import Config
from core.db import get_db_connection, execute_sql
from core.events import event_bus
from core.models.customer import Customer, CustomerCreditLedger

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NFC UID helpers
# ---------------------------------------------------------------------------
_NFC_UID_PATTERN = re.compile(r'^[A-F0-9]{14}$')


def sanitize_nfc_uid(raw_uid: str) -> str:
    """Strip all non-hex characters, uppercase, and validate 14-char length.

    Raises ValueError if the result is not exactly 14 uppercase hex characters.
    """
    if not raw_uid:
        raise ValueError("NFC UID cannot be empty.")
    cleaned = re.sub(r'[^A-F0-9]', '', raw_uid.upper())
    if not _NFC_UID_PATTERN.match(cleaned):
        raise ValueError(
            f"Invalid NFC UID '{raw_uid}'. Must be exactly 14 hexadecimal characters "
            f"after stripping separators. Got '{cleaned}' ({len(cleaned)} chars)."
        )
    return cleaned


# ---------------------------------------------------------------------------
# Database migration
# ---------------------------------------------------------------------------

def run_customer_migrations() -> None:
    """Execute the customers schema migration for the active database engine.

    This is idempotent — all DDL uses IF NOT EXISTS.
    """
    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    if engine in ('postgres', 'postgresql'):
        sql_file = os.path.join(
            Config.BASE_DIR, 'migrations', 'core_002_add_customers.pgsql.sql'
        )
    else:
        sql_file = os.path.join(
            Config.BASE_DIR, 'migrations', 'core_002_add_customers.sqlite.sql'
        )

    if not os.path.isfile(sql_file):
        logger.error(f"Customer migration file not found: {sql_file}")
        return

    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_script = f.read()

    try:
        with get_db_connection() as conn:
            if engine in ('postgres', 'postgresql'):
                cur = conn.cursor()
                cur.execute(sql_script)
            else:
                conn.executescript(sql_script)
        logger.info("Customer migration completed successfully.")
    except Exception as exc:
        logger.error(f"Customer migration failed: {exc}", exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Customer lookup helpers
# ---------------------------------------------------------------------------

def _row_to_customer(row) -> Optional[Customer]:
    if row is None:
        return None
    return Customer.from_row(row)


def resolve_customer(identifier: str) -> Optional[Customer]:
    """Find a customer by NFC UID, phone number, or name/email.

    Resolution order:
    1. If *identifier* matches ``^[A-Fa-f0-9]{14}$`` exactly → search ``nfc_uid``.
    2. If *identifier* contains ≥7 digits after stripping non-numeric chars → search ``phone``.
    3. Otherwise → case-insensitive match on ``name`` or ``email``.
    """
    identifier = identifier.strip()
    if not identifier:
        return None

    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    is_pg = engine in ('postgres', 'postgresql')

    # 1. NFC UID
    if re.fullmatch(r'[A-Fa-f0-9]{14}', identifier):
        uid = identifier.upper()
        with get_db_connection() as conn:
            cur = execute_sql(conn, "SELECT * FROM customers WHERE nfc_uid = ?", (uid,))
            row = cur.fetchone()
        return _row_to_customer(row)

    # 2. Phone number — extract digits only
    digits_only = re.sub(r'\D', '', identifier)
    if len(digits_only) >= 7:
        like_phone = f"%{digits_only}%"
        with get_db_connection() as conn:
            cur = execute_sql(
                conn,
                "SELECT * FROM customers WHERE REPLACE(REPLACE(REPLACE(phone, '-', ''), '(', ''), ')', '') LIKE ?",
                (like_phone,)
            )
            row = cur.fetchone()
        if row:
            return _row_to_customer(row)

    # 3. Name / email
    pattern = f"%{identifier}%"
    with get_db_connection() as conn:
        if is_pg:
            cur = execute_sql(
                conn,
                "SELECT * FROM customers WHERE name ILIKE ? OR email ILIKE ? LIMIT 1",
                (pattern, pattern)
            )
        else:
            cur = execute_sql(
                conn,
                "SELECT * FROM customers WHERE name LIKE ? COLLATE NOCASE OR email LIKE ? COLLATE NOCASE LIMIT 1",
                (pattern, pattern)
            )
        row = cur.fetchone()
    return _row_to_customer(row)


def search_customers(query: str, limit: int = 20) -> list:
    """Return compact summary dicts for autocomplete / cashier lookup."""
    query = query.strip()
    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    is_pg = engine in ('postgres', 'postgresql')

    if not query:
        with get_db_connection() as conn:
            cur = execute_sql(
                conn,
                "SELECT * FROM customers ORDER BY name LIMIT ?",
                (limit,)
            )
            rows = cur.fetchall()
        return [Customer.from_row(r).to_summary_dict() for r in rows]

    pattern = f"%{query}%"
    digits = re.sub(r'\D', '', query)
    with get_db_connection() as conn:
        if is_pg:
            cur = execute_sql(
                conn,
                """SELECT * FROM customers
                   WHERE name ILIKE ? OR email ILIKE ? OR phone LIKE ? OR nfc_uid ILIKE ?
                   ORDER BY name LIMIT ?""",
                (pattern, pattern, f"%{digits}%" if digits else pattern, pattern, limit)
            )
        else:
            cur = execute_sql(
                conn,
                """SELECT * FROM customers
                   WHERE name LIKE ? COLLATE NOCASE
                      OR email LIKE ? COLLATE NOCASE
                      OR phone LIKE ?
                      OR nfc_uid LIKE ? COLLATE NOCASE
                   ORDER BY name LIMIT ?""",
                (pattern, pattern, f"%{digits}%" if digits else pattern, pattern, limit)
            )
        rows = cur.fetchall()
    return [Customer.from_row(r).to_summary_dict() for r in rows]


def get_customer(customer_id: int) -> Optional[Customer]:
    """Return a full customer profile with lifetime stats."""
    with get_db_connection() as conn:
        cur = execute_sql(conn, "SELECT * FROM customers WHERE id = ?", (customer_id,))
        row = cur.fetchone()
        if row is None:
            return None
        customer = Customer.from_row(row)

        # Hydrate lifetime stats from the ledger
        cur2 = execute_sql(
            conn,
            """SELECT
                   COUNT(*)                                                AS total_transactions,
                   COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS total_deposited,
                   COALESCE(SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END), 0) AS total_redeemed
               FROM customer_credit_ledger
               WHERE customer_id = ?""",
            (customer_id,)
        )
        stats = cur2.fetchone()
        if stats:
            # sqlite3.Row supports both index and key access; index is universally safe
            customer.total_transactions = int(stats[0])
            customer.total_deposited = float(stats[1])
            customer.total_redeemed = float(stats[2])

    return customer


def get_customer_ledger(customer_id: int, page: int = 1, per_page: int = 50) -> dict:
    """Return paginated ledger entries for *customer_id*, newest first."""
    offset = (max(page, 1) - 1) * per_page
    with get_db_connection() as conn:
        cur_count = execute_sql(
            conn,
            "SELECT COUNT(*) FROM customer_credit_ledger WHERE customer_id = ?",
            (customer_id,)
        )
        total_raw = cur_count.fetchone()
        # sqlite3.Row supports index access; psycopg returns a tuple-like
        total = int(total_raw[0])

        cur = execute_sql(
            conn,
            """SELECT * FROM customer_credit_ledger
               WHERE customer_id = ?
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (customer_id, per_page, offset)
        )
        rows = cur.fetchall()

    entries = [CustomerCreditLedger.from_row(r).to_dict() for r in rows]
    return {
        'customer_id': customer_id,
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': max(1, -(-total // per_page)),  # ceiling division
        'entries': entries,
    }


# ---------------------------------------------------------------------------
# Mutating operations
# ---------------------------------------------------------------------------

def create_customer(
    name: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    nfc_uid: Optional[str] = None,
    notes: Optional[str] = None,
    initial_credit: float = 0.0,
    source_addon: str = 'core',
) -> Customer:
    """Create a new customer record.

    If *initial_credit* > 0, seeds the balance and writes the first ledger entry
    (``transaction_type='initial_migration'``).
    If *nfc_uid* is supplied, sanitizes and assigns it; dispatches
    ``customer:badge_assigned`` on the event bus.
    """
    name = name.strip()
    if not name:
        raise ValueError("Customer name is required.")

    cleaned_uid: Optional[str] = None
    if nfc_uid:
        cleaned_uid = sanitize_nfc_uid(nfc_uid)

    if initial_credit < 0:
        raise ValueError("Initial credit cannot be negative.")

    with get_db_connection() as conn:
        # Uniqueness guard for NFC UID
        if cleaned_uid:
            cur_dup = execute_sql(
                conn,
                "SELECT id FROM customers WHERE nfc_uid = ?",
                (cleaned_uid,)
            )
            if cur_dup.fetchone():
                raise ValueError(f"NFC UID '{cleaned_uid}' is already assigned to another customer.")

        initial_balance = round(initial_credit, 2)
        cur = execute_sql(
            conn,
            """INSERT INTO customers (name, phone, email, nfc_uid, store_credit_balance, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, phone or None, email or None, cleaned_uid, initial_balance, notes or None)
        )
        customer_id = cur.lastrowid

        # Seed initial ledger entry if balance > 0
        if initial_balance > 0.0:
            execute_sql(
                conn,
                """INSERT INTO customer_credit_ledger
                       (customer_id, amount, balance_after, transaction_type, source_addon, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    customer_id,
                    initial_balance,
                    initial_balance,
                    'initial_migration',
                    source_addon,
                    'Initial store credit balance'
                )
            )

    customer = get_customer(customer_id)

    # Ghost Tag Safeguard event
    if cleaned_uid:
        event_bus.dispatch('customer:badge_assigned', customer_id=customer_id, nfc_uid=cleaned_uid)

    logger.info(f"Customer created: id={customer_id} name='{name}' nfc_uid={cleaned_uid}")
    return customer


def update_customer(
    customer_id: int,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    notes: Optional[str] = None,
) -> Customer:
    """Update mutable profile fields. Returns the refreshed Customer."""
    updates = []
    params = []
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Customer name cannot be empty.")
        updates.append("name = ?")
        params.append(name)
    if phone is not None:
        updates.append("phone = ?")
        params.append(phone or None)
    if email is not None:
        updates.append("email = ?")
        params.append(email or None)
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes or None)

    if not updates:
        raise ValueError("No updatable fields provided.")

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(customer_id)

    with get_db_connection() as conn:
        execute_sql(
            conn,
            f"UPDATE customers SET {', '.join(updates)} WHERE id = ?",
            tuple(params)
        )

    customer = get_customer(customer_id)
    if customer is None:
        raise ValueError(f"Customer {customer_id} not found.")
    return customer


def assign_nfc_badge(customer_id: int, nfc_uid: str) -> Customer:
    """Assign a sanitized 14-char NFC UID to a customer.

    Validates uniqueness before writing. Dispatches ``customer:badge_assigned``
    on success so the tcg_pos / inventory addons can immediately wipe any
    ghost tag records tied to this physical card.
    """
    cleaned_uid = sanitize_nfc_uid(nfc_uid)

    with get_db_connection() as conn:
        # Verify customer exists
        cur_check = execute_sql(conn, "SELECT id FROM customers WHERE id = ?", (customer_id,))
        if cur_check.fetchone() is None:
            raise ValueError(f"Customer {customer_id} not found.")

        # Uniqueness check (exclude current customer)
        cur_dup = execute_sql(
            conn,
            "SELECT id FROM customers WHERE nfc_uid = ? AND id != ?",
            (cleaned_uid, customer_id)
        )
        if cur_dup.fetchone():
            raise ValueError(
                f"NFC UID '{cleaned_uid}' is already assigned to another customer."
            )

        execute_sql(
            conn,
            "UPDATE customers SET nfc_uid = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (cleaned_uid, customer_id)
        )

    # Ghost Tag Safeguard: notify all addons immediately
    event_bus.dispatch('customer:badge_assigned', customer_id=customer_id, nfc_uid=cleaned_uid)
    logger.info(f"Badge assigned: customer_id={customer_id} nfc_uid={cleaned_uid}")

    customer = get_customer(customer_id)
    return customer


def deposit_store_credit(
    customer_id: int,
    amount: float,
    source_addon: str = 'core',
    reference_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Customer:
    """Atomically deposit *amount* store credit for *customer_id*.

    Uses BEGIN IMMEDIATE on SQLite (equivalent of row-level write lock).
    Returns the refreshed Customer with updated balance.
    """
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("Deposit amount must be greater than zero.")

    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    is_pg = engine in ('postgres', 'postgresql')

    with get_db_connection() as conn:
        if not is_pg:
            # SQLite: escalate to exclusive write transaction immediately
            conn.execute("BEGIN IMMEDIATE")

        # Fetch current balance (with FOR UPDATE on PG for row-lock)
        lock_sql = (
            "SELECT store_credit_balance FROM customers WHERE id = ? FOR UPDATE"
            if is_pg
            else "SELECT store_credit_balance FROM customers WHERE id = ?"
        )
        cur = execute_sql(conn, lock_sql, (customer_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Customer {customer_id} not found.")

        current = float(row[0] if isinstance(row, tuple) else row['store_credit_balance'])
        new_balance = round(current + amount, 2)

        # Append ledger entry (never UPDATE existing rows)
        execute_sql(
            conn,
            """INSERT INTO customer_credit_ledger
                   (customer_id, amount, balance_after, transaction_type, source_addon, reference_id, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (customer_id, amount, new_balance, 'deposit', source_addon, reference_id, notes)
        )

        # Update customer balance
        execute_sql(
            conn,
            "UPDATE customers SET store_credit_balance = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_balance, customer_id)
        )

    logger.info(f"Deposit: customer_id={customer_id} amount={amount} new_balance={new_balance}")
    return get_customer(customer_id)


def redeem_store_credit(
    customer_id: int,
    amount: float,
    source_addon: str = 'core',
    reference_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Customer:
    """Atomically redeem *amount* store credit for *customer_id*.

    Raises ``ValueError`` if the customer has insufficient balance.
    Uses BEGIN IMMEDIATE on SQLite for write-lock semantics.
    Returns the refreshed Customer with updated balance.
    """
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("Redemption amount must be greater than zero.")

    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    is_pg = engine in ('postgres', 'postgresql')

    with get_db_connection() as conn:
        if not is_pg:
            conn.execute("BEGIN IMMEDIATE")

        lock_sql = (
            "SELECT store_credit_balance FROM customers WHERE id = ? FOR UPDATE"
            if is_pg
            else "SELECT store_credit_balance FROM customers WHERE id = ?"
        )
        cur = execute_sql(conn, lock_sql, (customer_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Customer {customer_id} not found.")

        current = float(row[0] if isinstance(row, tuple) else row['store_credit_balance'])

        if current < amount:
            raise ValueError(
                f"Insufficient store credit balance. "
                f"Available: ${current:.2f}, Requested: ${amount:.2f}"
            )

        new_balance = round(current - amount, 2)

        # Append negative ledger entry
        execute_sql(
            conn,
            """INSERT INTO customer_credit_ledger
                   (customer_id, amount, balance_after, transaction_type, source_addon, reference_id, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (customer_id, -amount, new_balance, 'redemption', source_addon, reference_id, notes)
        )

        execute_sql(
            conn,
            "UPDATE customers SET store_credit_balance = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_balance, customer_id)
        )

    logger.info(f"Redeem: customer_id={customer_id} amount={amount} new_balance={new_balance}")
    return get_customer(customer_id)
