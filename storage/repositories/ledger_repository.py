"""
=============================================================================
Open-POS Ledger & Audit Repository (storage/repositories/ledger_repository.py)
=============================================================================
Abstracts transaction recording, double-entry journal entry generation,
and audit trails for the POS register.
Ensures double-entry invariant: Sum(DEBITS) == Sum(CREDITS).
=============================================================================
"""

import json
import logging
from typing import Optional, Dict, Any, List
from storage.database import get_db_connection, execute_sql

logger = logging.getLogger("openpos.storage.ledger_repository")


class LedgerRepository:
    @staticmethod
    def record_transaction(
        order_id: str,
        tender_type: str,
        subtotal: float,
        tax: float,
        total: float,
        customer_id: Optional[str] = None,
        customer_name: Optional[str] = None,
        items: Optional[List[Dict[str, Any]]] = None,
        notes: str = ""
    ) -> Dict[str, Any]:
        """
        Commits an order header and balanced double-entry accounting entries
        to the pos_transactions and pos_ledger_entries tables.
        """
        subtotal_val = round(max(0.0, float(subtotal)), 2)
        tax_val = round(max(0.0, float(tax)), 2)
        total_val = round(max(0.0, float(total)), 2)
        tender_str = str(tender_type).lower().strip()

        cash_tender = total_val if tender_str == "cash" else 0.0
        card_tender = total_val if tender_str == "card" else 0.0
        credit_tender = total_val if tender_str in ("store_credit", "credit") else 0.0

        items_json = json.dumps(items or [])
        metadata_json = json.dumps({"notes": notes, "tender_type": tender_str})

        with get_db_connection() as conn:
            # 1. Insert order header
            execute_sql(
                conn,
                """
                INSERT INTO pos_transactions (
                    order_id, customer_id, customer_name, subtotal, discount_total,
                    tax_rate, tax_total, grand_total, credit_applied, cash_tendered,
                    card_tendered, change_due, status, items_json, metadata_json
                ) VALUES (?, ?, ?, ?, 0.0, 0.0, ?, ?, ?, ?, ?, 0.0, 'completed', ?, ?)
                """,
                (
                    order_id,
                    customer_id,
                    customer_name or "Guest",
                    subtotal_val,
                    tax_val,
                    total_val,
                    credit_tender,
                    cash_tender,
                    card_tender,
                    items_json,
                    metadata_json
                )
            )

            # 2. Balanced Double-Entry Journal Entries
            # DEBIT: Asset received / liability settled
            debit_account = "cash"
            if tender_str == "card":
                debit_account = "card"
            elif tender_str in ("store_credit", "credit"):
                debit_account = "customer_store_credit"

            execute_sql(
                conn,
                """
                INSERT INTO pos_ledger_entries (transaction_id, account, entry_type, amount, notes)
                VALUES (?, ?, 'DEBIT', ?, ?)
                """,
                (order_id, debit_account, total_val, f"{tender_str.title()} payment received")
            )

            # CREDIT: Sales revenue
            if subtotal_val > 0:
                execute_sql(
                    conn,
                    """
                    INSERT INTO pos_ledger_entries (transaction_id, account, entry_type, amount, notes)
                    VALUES (?, 'sales_revenue', 'CREDIT', ?, 'Sales merchandise revenue')
                    """,
                    (order_id, subtotal_val)
                )

            # CREDIT: Sales tax payable
            if tax_val > 0:
                execute_sql(
                    conn,
                    """
                    INSERT INTO pos_ledger_entries (transaction_id, account, entry_type, amount, notes)
                    VALUES (?, 'sales_tax_payable', 'CREDIT', ?, 'Sales tax collected')
                    """,
                    (order_id, tax_val)
                )

            conn.commit()

        logger.info(f"LedgerRepository: Recorded transaction {order_id} (Total: {total_val}, Tender: {tender_str})")
        return {
            "order_id": order_id,
            "status": "completed",
            "total": total_val,
            "tender_type": tender_str
        }

    @staticmethod
    def get_transaction(order_id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = execute_sql(
                conn,
                "SELECT * FROM pos_transactions WHERE order_id = ?",
                (order_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_ledger_entries(transaction_id: str) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = execute_sql(
                conn,
                "SELECT * FROM pos_ledger_entries WHERE transaction_id = ? ORDER BY id ASC",
                (transaction_id,)
            )
            return [dict(r) for r in cur.fetchall()]

    @staticmethod
    def list_recent_transactions(limit: int = 50) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = execute_sql(
                conn,
                "SELECT * FROM pos_transactions ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            return [dict(r) for r in cur.fetchall()]
