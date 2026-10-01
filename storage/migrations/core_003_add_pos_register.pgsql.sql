-- =============================================================================
-- Open-POS Core Migration: core_003_add_pos_register (PostgreSQL)
-- =============================================================================
-- POS Register transactions, double-entry accounting ledger, and held orders.
-- This migration is idempotent (all DDL uses IF NOT EXISTS).
-- =============================================================================

CREATE TABLE IF NOT EXISTS pos_transactions (
    id                    SERIAL PRIMARY KEY,
    order_id              TEXT UNIQUE NOT NULL,
    customer_id           INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    customer_name         TEXT,
    subtotal              DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    discount_total        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    tax_rate              DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    tax_total             DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    grand_total           DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    credit_applied        DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    cash_tendered         DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    card_tendered         DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    change_due            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    status                TEXT NOT NULL DEFAULT 'completed',
    items_json            TEXT NOT NULL DEFAULT '[]',
    metadata_json         TEXT NOT NULL DEFAULT '{}',
    created_at            TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pos_txn_order_id    ON pos_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_pos_txn_customer_id ON pos_transactions(customer_id);
CREATE INDEX IF NOT EXISTS idx_pos_txn_created_at  ON pos_transactions(created_at DESC);

-- ----------------------------------------------------------------------------
-- Double-entry accounting ledger for POS transactions.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pos_ledger_entries (
    id                SERIAL PRIMARY KEY,
    transaction_id    TEXT NOT NULL,
    account           TEXT NOT NULL,
    entry_type        TEXT NOT NULL CHECK (entry_type IN ('DEBIT', 'CREDIT')),
    amount            DOUBLE PRECISION NOT NULL CHECK (amount >= 0.0),
    notes             TEXT,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pos_ledger_txn_id   ON pos_ledger_entries(transaction_id);
CREATE INDEX IF NOT EXISTS idx_pos_ledger_account  ON pos_ledger_entries(account);
CREATE INDEX IF NOT EXISTS idx_pos_ledger_created  ON pos_ledger_entries(created_at DESC);

-- ----------------------------------------------------------------------------
-- Held orders table for parked carts.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pos_held_orders (
    id                SERIAL PRIMARY KEY,
    hold_id           TEXT UNIQUE NOT NULL,
    customer_name     TEXT,
    cart_data         TEXT NOT NULL,
    notes             TEXT,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pos_held_hold_id    ON pos_held_orders(hold_id);
