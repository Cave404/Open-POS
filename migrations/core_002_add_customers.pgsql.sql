-- =============================================================================
-- Open-POS Core Migration: core_002_add_customers (PostgreSQL 14+)
-- =============================================================================
-- Customers identity table and append-only credit ledger.
-- This migration is idempotent (all DDL uses IF NOT EXISTS).
-- Requires: PostgreSQL 14+, psycopg driver.
-- =============================================================================

-- citext provides case-insensitive text comparisons without LOWER() everywhere
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS customers (
    id                    BIGINT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                  CITEXT         NOT NULL,
    phone                 VARCHAR(32),
    email                 CITEXT,
    nfc_uid               VARCHAR(64)    UNIQUE,
    store_credit_balance  NUMERIC(10, 2) NOT NULL DEFAULT 0.00
                                         CHECK (store_credit_balance >= 0.00),
    notes                 TEXT,
    created_at            TIMESTAMPTZ    DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMPTZ    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_customers_name   ON customers(name);
CREATE INDEX IF NOT EXISTS idx_customers_phone  ON customers(phone);
CREATE INDEX IF NOT EXISTS idx_customers_email  ON customers(email);
CREATE INDEX IF NOT EXISTS idx_customers_nfc    ON customers(nfc_uid);

-- ----------------------------------------------------------------------------
-- Append-only store credit ledger.
-- Records MUST NEVER be updated or deleted. Every balance modification is
-- written as a new row with the resulting balance in balance_after.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customer_credit_ledger (
    id                BIGINT         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id       BIGINT         NOT NULL
                                     REFERENCES customers(id) ON DELETE CASCADE,
    amount            NUMERIC(10, 2) NOT NULL,
    balance_after     NUMERIC(10, 2) NOT NULL
                                     CHECK (balance_after >= 0.00),
    transaction_type  VARCHAR(32)    NOT NULL,
    source_addon      VARCHAR(64)    NOT NULL DEFAULT 'core',
    reference_id      VARCHAR(128),
    notes             TEXT,
    created_at        TIMESTAMPTZ    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ledger_customer_id ON customer_credit_ledger(customer_id);
CREATE INDEX IF NOT EXISTS idx_ledger_created_at  ON customer_credit_ledger(created_at DESC);
