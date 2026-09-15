"""
core/models/customer.py
=======================
Data model classes for the Customer Management subsystem.

These are plain Python dataclasses — no ORM dependency.
They are constructed by customer_service.py from raw sqlite3.Row / psycopg Row
objects and expose serialization helpers consumed by REST API routes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


def _fmt_ts(ts) -> Optional[str]:
    """Return a consistent ISO-8601 string from any timestamp representation."""
    if ts is None:
        return None
    # sqlite3.Row timestamps come back as strings; psycopg returns datetime objects
    if hasattr(ts, 'isoformat'):
        return ts.isoformat()
    return str(ts)


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

@dataclass
class Customer:
    """Represents a single customer record from the ``customers`` table."""
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    nfc_uid: Optional[str] = None
    store_credit_balance: float = 0.0
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # Optional stats hydrated by get_customer()
    total_transactions: int = 0
    total_deposited: float = 0.0
    total_redeemed: float = 0.0

    # ------------------------------------------------------------------ #
    # Factories
    # ------------------------------------------------------------------ #

    @classmethod
    def from_row(cls, row) -> 'Customer':
        """Construct a Customer from a sqlite3.Row or psycopg dict-like row."""
        def _get(key, default=None):
            try:
                return row[key]
            except (KeyError, IndexError):
                return default

        return cls(
            id=_get('id'),
            name=_get('name', ''),
            phone=_get('phone'),
            email=_get('email'),
            nfc_uid=_get('nfc_uid'),
            store_credit_balance=float(_get('store_credit_balance') or 0.0),
            notes=_get('notes'),
            created_at=_fmt_ts(_get('created_at')),
            updated_at=_fmt_ts(_get('updated_at')),
        )

    # ------------------------------------------------------------------ #
    # Serializers
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """Full profile representation including audit timestamps and lifetime stats."""
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'nfc_uid': self.nfc_uid,
            'has_badge': bool(self.nfc_uid),
            'store_credit_balance': round(self.store_credit_balance, 2),
            'notes': self.notes,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'stats': {
                'total_transactions': self.total_transactions,
                'total_deposited': round(self.total_deposited, 2),
                'total_redeemed': round(self.total_redeemed, 2),
            },
        }

    def to_summary_dict(self) -> dict:
        """Compact representation for POS register autocomplete lookups."""
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'nfc_uid': self.nfc_uid,
            'has_badge': bool(self.nfc_uid),
            'store_credit_balance': round(self.store_credit_balance, 2),
        }


# ---------------------------------------------------------------------------
# CustomerCreditLedger
# ---------------------------------------------------------------------------

@dataclass
class CustomerCreditLedger:
    """Represents a single, immutable ledger entry from ``customer_credit_ledger``."""
    id: int
    customer_id: int
    amount: float
    balance_after: float
    transaction_type: str
    source_addon: str = 'core'
    reference_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None

    def __post_init__(self):
        if self.amount == 0.0:
            raise ValueError("Ledger entry amount must not be zero.")

    @classmethod
    def from_row(cls, row) -> 'CustomerCreditLedger':
        def _get(key, default=None):
            try:
                return row[key]
            except (KeyError, IndexError):
                return default

        return cls(
            id=_get('id'),
            customer_id=_get('customer_id'),
            amount=float(_get('amount') or 0.0),
            balance_after=float(_get('balance_after') or 0.0),
            transaction_type=_get('transaction_type', ''),
            source_addon=_get('source_addon', 'core'),
            reference_id=_get('reference_id'),
            notes=_get('notes'),
            created_at=_fmt_ts(_get('created_at')),
        )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'amount': round(self.amount, 2),
            'balance_after': round(self.balance_after, 2),
            'transaction_type': self.transaction_type,
            'source_addon': self.source_addon,
            'reference_id': self.reference_id,
            'notes': self.notes,
            'created_at': self.created_at,
        }
