"""
tests/test_core_customers.py
============================
Automated unit & integration tests for the Customer Management Subsystem (v1.0.9).

Coverage:
  1.  Customer migrations run cleanly on isolated in-memory SQLite DB.
  2.  resolve_customer by formatted phone '(555) 123-4567'.
  3.  resolve_customer by 14-char uppercase hex UID.
  4.  resolve_customer by partial case-insensitive name.
  5.  Deposit $50 → balance=$50, ledger balance_after=50.
  6.  Redeem $30 from $50 → balance=$20, ledger amount=-30, balance_after=20.
  7.  Redeem $25 from $20 → ValueError, balance unchanged, no ledger row added.
  8.  Ghost Tag Safeguard: assign badge fires customer:badge_assigned with sanitized UID.
  9.  GET /api/core/customers/search returns results.
  10. POST /api/core/customers + POST /credit/deposit round-trip.
"""

import sqlite3
import pytest
from unittest.mock import patch
from app import create_app
from core.config import Config
from core.events import event_bus


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def memory_db(monkeypatch, tmp_path):
    """Redirect all DB operations to a fresh in-memory SQLite database."""
    monkeypatch.setattr(Config, 'DB_ENGINE', 'sqlite')
    monkeypatch.setattr(Config, 'DB_NAME', ':memory:')
    monkeypatch.setattr(Config, 'DB_PATH', ':memory:')

    # Run the customer migration directly on the in-memory DB
    from core.services.customer_service import run_customer_migrations
    # init_db (settings table) runs first via app factory; call migration directly:
    run_customer_migrations()
    yield


@pytest.fixture
def isolated_app(monkeypatch, tmp_path):
    """Flask test client backed by a private temp SQLite DB."""
    db_path = str(tmp_path / "test_customers.db")
    monkeypatch.setattr(Config, 'DB_ENGINE', 'sqlite')
    monkeypatch.setattr(Config, 'DB_NAME', db_path)
    monkeypatch.setattr(Config, 'DB_PATH', db_path)

    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def reset_event_bus():
    """Clear event bus subscribers between tests to prevent cross-test pollution."""
    event_bus.clear()
    yield
    event_bus.clear()


# ============================================================================
# Helpers — operate directly against isolated DB
# ============================================================================

def _run_migrations_on(db_path):
    from core.services.customer_service import run_customer_migrations
    import os
    sql_file = os.path.join(Config.BASE_DIR, 'migrations', 'core_002_add_customers.sqlite.sql')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    with open(sql_file, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


# ============================================================================
# 1. Migration runs cleanly on isolated SQLite DB
# ============================================================================

def test_customer_migrations_create_tables(tmp_path):
    """Asserts that both customers and customer_credit_ledger tables are created."""
    db_path = str(tmp_path / "migration_test.db")
    conn = _run_migrations_on(db_path)

    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('customers', 'customer_credit_ledger')"
    )
    tables = {row['name'] for row in cursor.fetchall()}
    assert 'customers' in tables, "customers table missing"
    assert 'customer_credit_ledger' in tables, "customer_credit_ledger table missing"

    # Verify indexes
    idx_cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='customers'"
    )
    indexes = {row['name'] for row in idx_cursor.fetchall()}
    assert 'idx_customers_nfc' in indexes
    assert 'idx_customers_phone' in indexes
    conn.close()


# ============================================================================
# 2–4. resolve_customer routing strategies
# ============================================================================

def test_resolve_customer_by_formatted_phone(tmp_path, monkeypatch):
    """resolve_customer finds a customer using a formatted phone '(555) 123-4567'."""
    db_path = str(tmp_path / "resolve_test.db")
    conn = _run_migrations_on(db_path)
    conn.execute(
        "INSERT INTO customers (name, phone, email) VALUES ('Jane Smith', '5551234567', NULL)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(Config, 'DB_ENGINE', 'sqlite')
    monkeypatch.setattr(Config, 'DB_PATH', db_path)
    monkeypatch.setattr(Config, 'DB_NAME', db_path)

    from core.services import customer_service
    # Reload module to pick up monkeypatched Config
    import importlib
    importlib.reload(customer_service)
    from core.services.customer_service import resolve_customer

    result = resolve_customer("(555) 123-4567")
    assert result is not None, "Expected to find customer by formatted phone"
    assert result.name == "Jane Smith"


def test_resolve_customer_by_nfc_uid(tmp_path, monkeypatch):
    """resolve_customer finds a customer by 14-char uppercase hex UID."""
    db_path = str(tmp_path / "resolve_nfc.db")
    conn = _run_migrations_on(db_path)
    conn.execute(
        "INSERT INTO customers (name, nfc_uid) VALUES ('Alice NFC', '04394D4FBD2A81')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(Config, 'DB_ENGINE', 'sqlite')
    monkeypatch.setattr(Config, 'DB_PATH', db_path)
    monkeypatch.setattr(Config, 'DB_NAME', db_path)

    from core.services import customer_service
    import importlib
    importlib.reload(customer_service)
    from core.services.customer_service import resolve_customer

    result = resolve_customer("04394D4FBD2A81")
    assert result is not None, "Expected to find customer by NFC UID"
    assert result.name == "Alice NFC"


def test_resolve_customer_by_name_case_insensitive(tmp_path, monkeypatch):
    """resolve_customer finds a customer by partial case-insensitive name match."""
    db_path = str(tmp_path / "resolve_name.db")
    conn = _run_migrations_on(db_path)
    conn.execute(
        "INSERT INTO customers (name) VALUES ('Robert Townshend')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(Config, 'DB_ENGINE', 'sqlite')
    monkeypatch.setattr(Config, 'DB_PATH', db_path)
    monkeypatch.setattr(Config, 'DB_NAME', db_path)

    from core.services import customer_service
    import importlib
    importlib.reload(customer_service)
    from core.services.customer_service import resolve_customer

    result = resolve_customer("robert town")
    assert result is not None, "Expected to find customer by name fragment"
    assert result.name == "Robert Townshend"


# ============================================================================
# 5–7. Credit Deposit & Redemption (financial invariants)
# ============================================================================

def test_deposit_creates_ledger_row_and_updates_balance(tmp_path, monkeypatch):
    """Deposit $50 → balance=$50, ledger row has balance_after=50."""
    db_path = str(tmp_path / "credit_test.db")
    conn = _run_migrations_on(db_path)
    conn.execute("INSERT INTO customers (name) VALUES ('Credit Tester')")
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    monkeypatch.setattr(Config, 'DB_ENGINE', 'sqlite')
    monkeypatch.setattr(Config, 'DB_PATH', db_path)
    monkeypatch.setattr(Config, 'DB_NAME', db_path)

    from core.services import customer_service
    import importlib
    importlib.reload(customer_service)
    from core.services.customer_service import deposit_store_credit, get_customer

    updated = deposit_store_credit(cid, 50.00, source_addon='test', notes='Test deposit')
    assert updated.store_credit_balance == 50.00

    verify_conn = sqlite3.connect(db_path)
    verify_conn.row_factory = sqlite3.Row
    row = verify_conn.execute(
        "SELECT amount, balance_after, transaction_type FROM customer_credit_ledger WHERE customer_id=?",
        (cid,)
    ).fetchone()
    assert row is not None, "Ledger row must exist after deposit"
    assert float(row['amount']) == 50.00
    assert float(row['balance_after']) == 50.00
    assert row['transaction_type'] == 'deposit'
    verify_conn.close()


def test_redeem_reduces_balance_and_creates_negative_ledger_row(tmp_path, monkeypatch):
    """Redeem $30 from $50 balance → balance=$20, ledger amount=-30, balance_after=20."""
    db_path = str(tmp_path / "redeem_test.db")
    conn = _run_migrations_on(db_path)
    conn.execute("INSERT INTO customers (name, store_credit_balance) VALUES ('Redeem Tester', 50.0)")
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    monkeypatch.setattr(Config, 'DB_ENGINE', 'sqlite')
    monkeypatch.setattr(Config, 'DB_PATH', db_path)
    monkeypatch.setattr(Config, 'DB_NAME', db_path)

    from core.services import customer_service
    import importlib
    importlib.reload(customer_service)
    from core.services.customer_service import redeem_store_credit

    updated = redeem_store_credit(cid, 30.00, source_addon='test', notes='Redeem test')
    assert updated.store_credit_balance == 20.00

    verify_conn = sqlite3.connect(db_path)
    verify_conn.row_factory = sqlite3.Row
    row = verify_conn.execute(
        "SELECT amount, balance_after, transaction_type FROM customer_credit_ledger WHERE customer_id=?",
        (cid,)
    ).fetchone()
    assert row is not None, "Ledger row must exist after redemption"
    assert float(row['amount']) == -30.00
    assert float(row['balance_after']) == 20.00
    assert row['transaction_type'] == 'redemption'
    verify_conn.close()


def test_redeem_insufficient_balance_raises_and_leaves_no_ledger_row(tmp_path, monkeypatch):
    """Redeem $25 from $20 → ValueError, balance unchanged, no new ledger row."""
    db_path = str(tmp_path / "insufficient_test.db")
    conn = _run_migrations_on(db_path)
    conn.execute("INSERT INTO customers (name, store_credit_balance) VALUES ('Broke Tester', 20.0)")
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    monkeypatch.setattr(Config, 'DB_ENGINE', 'sqlite')
    monkeypatch.setattr(Config, 'DB_PATH', db_path)
    monkeypatch.setattr(Config, 'DB_NAME', db_path)

    from core.services import customer_service
    import importlib
    importlib.reload(customer_service)
    from core.services.customer_service import redeem_store_credit, get_customer

    with pytest.raises(ValueError, match="Insufficient store credit"):
        redeem_store_credit(cid, 25.00, source_addon='test', notes='Should fail')

    # Balance must be unchanged
    verify_conn = sqlite3.connect(db_path)
    verify_conn.row_factory = sqlite3.Row
    balance_row = verify_conn.execute(
        "SELECT store_credit_balance FROM customers WHERE id=?", (cid,)
    ).fetchone()
    assert float(balance_row['store_credit_balance']) == 20.00

    # No ledger row should have been created
    ledger_count = verify_conn.execute(
        "SELECT COUNT(*) FROM customer_credit_ledger WHERE customer_id=?", (cid,)
    ).fetchone()[0]
    assert ledger_count == 0, "Ledger must not have any rows when redemption fails"
    verify_conn.close()


# ============================================================================
# 8. Ghost Tag Safeguard — event dispatch on badge assignment
# ============================================================================

def test_assign_badge_fires_ghost_tag_event(tmp_path, monkeypatch):
    """Assigning a badge dispatches customer:badge_assigned with the sanitized UID."""
    db_path = str(tmp_path / "badge_test.db")
    conn = _run_migrations_on(db_path)
    conn.execute("INSERT INTO customers (name) VALUES ('Badge Tester')")
    cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    monkeypatch.setattr(Config, 'DB_ENGINE', 'sqlite')
    monkeypatch.setattr(Config, 'DB_PATH', db_path)
    monkeypatch.setattr(Config, 'DB_NAME', db_path)

    from core.services import customer_service
    import importlib
    importlib.reload(customer_service)
    from core.services.customer_service import assign_nfc_badge

    received_events = []

    def on_badge_assigned(customer_id, nfc_uid):
        received_events.append({'customer_id': customer_id, 'nfc_uid': nfc_uid})

    event_bus.subscribe('customer:badge_assigned', on_badge_assigned)

    # Intentionally pass with formatting separators — must be sanitized to 14 uppercase hex chars
    raw_uid = '04:A1:B2:C3:D4:E5:F6'  # 7 bytes = 14 hex chars after stripping colons
    assign_nfc_badge(cid, raw_uid)

    assert len(received_events) == 1, "Event should have been dispatched once"
    assert received_events[0]['customer_id'] == cid
    assert received_events[0]['nfc_uid'] == '04A1B2C3D4E5F6'


# ============================================================================
# 9. REST API: GET /api/core/customers/search
# ============================================================================

def test_api_search_customers_returns_results(isolated_app):
    """GET /api/core/customers/search returns a JSON list."""
    # Create a customer first
    isolated_app.post('/api/core/customers', json={
        'name': 'Search Test Customer',
        'phone': '5550001111',
    })

    res = isolated_app.get('/api/core/customers/search?q=Search Test')
    assert res.status_code == 200
    results = res.get_json()
    assert isinstance(results, list)
    assert len(results) >= 1
    assert any(r['name'] == 'Search Test Customer' for r in results)


# ============================================================================
# 10. REST API: Full create + deposit + ledger consistency round-trip
# ============================================================================

def test_api_create_deposit_ledger_consistency(isolated_app):
    """POST /api/core/customers → POST /credit/deposit → ledger round-trip."""
    # 1. Create customer with $25 initial credit
    res_create = isolated_app.post('/api/core/customers', json={
        'name': 'Round Trip Customer',
        'initial_credit': 25.00,
        'source_addon': 'test',
    })
    assert res_create.status_code == 201
    customer_id = res_create.get_json()['customer']['id']
    assert res_create.get_json()['customer']['store_credit_balance'] == 25.00

    # 2. Verify initial ledger entry
    res_ledger = isolated_app.get(f'/api/core/customers/{customer_id}/ledger')
    assert res_ledger.status_code == 200
    ledger = res_ledger.get_json()
    assert ledger['total'] >= 1
    first_entry = ledger['entries'][0]
    assert first_entry['transaction_type'] == 'initial_migration'
    assert first_entry['balance_after'] == 25.00

    # 3. Deposit $15
    res_deposit = isolated_app.post(f'/api/core/customers/{customer_id}/credit/deposit', json={
        'amount': 15.00,
        'source_addon': 'test',
        'notes': 'API deposit test',
    })
    assert res_deposit.status_code == 200
    assert res_deposit.get_json()['new_balance'] == 40.00

    # 4. Verify ledger now has 2 rows
    res_ledger2 = isolated_app.get(f'/api/core/customers/{customer_id}/ledger')
    assert res_ledger2.get_json()['total'] >= 2

    # 5. Redeem $5
    res_redeem = isolated_app.post(f'/api/core/customers/{customer_id}/credit/redeem', json={
        'amount': 5.00,
        'source_addon': 'test',
        'notes': 'API redeem test',
    })
    assert res_redeem.status_code == 200
    assert res_redeem.get_json()['new_balance'] == 35.00

    # 6. Insufficient balance returns 400
    res_bad = isolated_app.post(f'/api/core/customers/{customer_id}/credit/redeem', json={
        'amount': 9999.00,
        'source_addon': 'test',
        'notes': 'Should fail',
    })
    assert res_bad.status_code == 400
    assert 'Insufficient' in res_bad.get_json().get('message', '')

    # 7. Final profile balance matches
    res_profile = isolated_app.get(f'/api/core/customers/{customer_id}')
    assert res_profile.status_code == 200
    assert res_profile.get_json()['customer']['store_credit_balance'] == 35.00
