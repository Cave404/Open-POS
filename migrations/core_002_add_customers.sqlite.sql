-- =============================================================================
-- Open-POS Core Migration: core_002_add_customers (SQLite 3)
-- =============================================================================
-- Customers identity table and append-only credit ledger.
-- This migration is idempotent (all DDL uses IF NOT EXISTS).
-- =============================================================================

CREATE TABLE IF NOT EXISTS customers (
    id                    INTEGER  PRIMARY KEY AUTOINCREMENT,
    name                  TEXT     NOT NULL,
    phone                 TEXT,
    email                 TEXT,
    nfc_uid               TEXT     UNIQUE,
    store_credit_balance  REAL     NOT NULL DEFAULT 0.0
                                   CHECK (store_credit_balance >= 0.0),
    notes                 TEXT,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_customers_name   ON customers(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_customers_phone  ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_customers_email  ON customers(email COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_customers_nfc    ON customers(nfc_uid);

-- ----------------------------------------------------------------------------
-- Append-only store credit ledger.
-- Records MUST NEVER be updated or deleted. Every balance modification is
-- written as a new row with the resulting balance in balance_after.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customer_credit_ledger (
    id                INTEGER   PRIMARY KEY AUTOINCREMENT,
    customer_id       INTEGER   NOT NULL
                                REFERENCES customers(id) ON DELETE CASCADE,
    amount            REAL      NOT NULL,
    balance_after     REAL      NOT NULL
                                CHECK (balance_after >= 0.0),
    transaction_type  TEXT      NOT NULL,
    source_addon      TEXT      NOT NULL DEFAULT 'core',
    reference_id      TEXT,
    notes             TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ledger_customer_id ON customer_credit_ledger(customer_id);
CREATE INDEX IF NOT EXISTS idx_ledger_created_at  ON customer_credit_ledger(created_at DESC);
