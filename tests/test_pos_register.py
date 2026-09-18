"""
=============================================================================
tests/test_pos_register.py
=============================================================================
Comprehensive unit & integration tests for:
  1. POS Register schema migrations (pos_transactions, pos_ledger_entries, pos_held_orders).
  2. CartService business logic: calculations, discounts, metadata, steppers.
  3. REST endpoints (/api/pos/cart/*, /api/pos/scan, /api/pos/products).
  4. Customer attachment & store credit hydration.
  5. Split tender checkout, double-entry accounting ledger balancing,
     customer credit ledger deductions, and event bus dispatch.
  6. Dynamic canvas swapping & UI hooks (pos:workspace_toggles, pos:canvas_mount).
  7. Configurable default POS view setting.
=============================================================================
"""

import json
import sqlite3
import pytest
from unittest.mock import patch

from app import create_app
from core.config import Config
from core.events import event_bus
from core.settings import set_setting, get_setting
from core.services.cart_service import cart_service
from core.services.customer_service import create_customer, get_customer
from core.addons.ui_hooks import has_addon_canvas, render_addon_hook, get_addon_canvases


@pytest.fixture
def test_app(monkeypatch, tmp_path):
    """Flask test client backed by a temporary isolated SQLite database."""
    db_path = str(tmp_path / "test_pos.db")
    monkeypatch.setattr(Config, 'DB_ENGINE', 'sqlite')
    monkeypatch.setattr(Config, 'DB_NAME', db_path)
    monkeypatch.setattr(Config, 'DB_PATH', db_path)

    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def reset_event_bus_and_cart():
    """Ensures a clean event bus and cart state between tests."""
    event_bus.clear()
    cart_service.clear("test_cart")
    cart_service.clear("default_register_cart")
    yield
    event_bus.clear()


# =============================================================================
# 1. Database Schema & Migrations
# =============================================================================
def test_pos_migrations_create_tables(test_app):
    """Asserts that pos_transactions, pos_ledger_entries, and pos_held_orders tables exist."""
    with sqlite3.connect(Config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r['name'] for r in cur.fetchall()]

    assert 'pos_transactions' in tables, "pos_transactions table missing"
    assert 'pos_ledger_entries' in tables, "pos_ledger_entries table missing"
    assert 'pos_held_orders' in tables, "pos_held_orders table missing"


# =============================================================================
# 2. CartService Business Logic & Financial Math
# =============================================================================
def test_cart_service_pricing_and_discounts():
    """Asserts subtotals, line item discounts, tax calculation, and grand total."""
    cid = "test_cart_calc"
    cart_service.clear(cid)

    # Add 2x $10 item (taxable)
    c1 = cart_service.add_item(cid, "Card Sleeves", 10.00, quantity=2, taxable=True)
    assert c1["subtotal"] == 20.00
    assert c1["discount_total"] == 0.00
    # Default tax 8.25% of 20.00 = 1.65
    assert c1["tax_total"] == 1.65
    assert c1["grand_total"] == 21.65

    # Update item with line discount ($2 off per item)
    item_id = c1["items"][0]["item_id"]
    c2 = cart_service.update_item(cid, item_id, discount=2.00)
    # Net subtotal = (10 - 2) * 2 = 16.00; discount_total = 4.00
    assert c2["discount_total"] == 4.00
    # Tax on 16.00 = 1.32
    assert c2["tax_total"] == 1.32
    assert c2["grand_total"] == 17.32

    # Apply order-level discount $5.00
    c3 = cart_service.apply_discount(cid, 5.00)
    # Net base = 16.00 - 5.00 = 11.00; tax on 11.00 = 0.91
    assert c3["tax_total"] == 0.91
    assert c3["grand_total"] == 11.91


def test_cart_service_item_metadata_preservation():
    """Asserts custom addon metadata (Scryfall ID, condition, foil, trade-in) is preserved."""
    cid = "test_meta_cart"
    cart_service.clear(cid)

    metadata = {
        "addon": "tcg_pos",
        "scryfall_id": "0004e020-2199-4e12-b571-c7f73c6265aa",
        "condition": "LP",
        "is_foil": True,
        "trade_in": False
    }

    c = cart_service.add_item(
        cid,
        name="Mox Pearl (LP Foil)",
        price=1500.00,
        quantity=1,
        sku="TCG-MOX-PEARL",
        metadata=metadata
    )

    assert len(c["items"]) == 1
    stored_item = c["items"][0]
    assert stored_item["metadata"]["condition"] == "LP"
    assert stored_item["metadata"]["is_foil"] is True
    assert stored_item["metadata"]["scryfall_id"] == "0004e020-2199-4e12-b571-c7f73c6265aa"


# =============================================================================
# 3. Customer Attachment & Store Credit Application
# =============================================================================
def test_cart_customer_attachment_and_store_credit(test_app):
    """Asserts customer attachment and capping store credit application."""
    # Create customer with $40.00 balance
    cust = create_customer(
        name="Jace Beleren",
        phone="(555) 777-8888",
        initial_credit=40.00,
        nfc_uid="04A1B2C3D4E5F6"
    )

    cid = "test_cust_cart"
    cart_service.clear(cid)
    cart_service.add_item(cid, "Booster Box", 100.00, quantity=1, taxable=False)

    # Attach customer
    c_attached = cart_service.attach_customer(
        cid,
        customer_id=cust.id,
        customer_name=cust.name,
        customer_credit=cust.store_credit_balance,
        nfc_uid=cust.nfc_uid
    )

    assert c_attached["customer_id"] == cust.id
    assert c_attached["customer_credit"] == 40.00

    # Apply full credit
    c_credit = cart_service.apply_store_credit(cid, amount=None)
    assert c_credit["credit_applied"] == 40.00

    # Attempt to apply more credit than customer possesses ($100) -> capped at balance ($40)
    c_capped = cart_service.apply_store_credit(cid, amount=100.00)
    assert c_capped["credit_applied"] == 40.00

    # Detach customer -> resets credit_applied to 0
    c_detached = cart_service.detach_customer(cid)
    assert c_detached["customer_id"] is None
    assert c_detached["credit_applied"] == 0.00


# =============================================================================
# 4. REST Endpoints: Cart CRUD
# =============================================================================
def test_api_cart_crud(test_app):
    """Asserts GET, POST, PATCH, DELETE, and CLEAR endpoints for /api/pos/cart."""
    headers = {"X-Cart-ID": "test_api_cart"}

    # 1. GET empty cart
    res1 = test_app.get('/api/pos/cart', headers=headers)
    assert res1.status_code == 200
    assert res1.get_json()["cart"]["items"] == []

    # 2. POST add item
    res2 = test_app.post('/api/pos/cart/item', headers=headers, json={
        "name": "Playmat",
        "price": 25.00,
        "quantity": 1,
        "sku": "ACC-MAT-001"
    })
    assert res2.status_code == 200
    cart2 = res2.get_json()["cart"]
    assert len(cart2["items"]) == 1
    item_id = cart2["items"][0]["item_id"]

    # 3. PATCH update quantity
    res3 = test_app.patch(f'/api/pos/cart/item/{item_id}', headers=headers, json={"quantity": 3})
    assert res3.status_code == 200
    assert res3.get_json()["cart"]["items"][0]["quantity"] == 3

    # 4. DELETE remove item
    res4 = test_app.delete(f'/api/pos/cart/item/{item_id}', headers=headers)
    assert res4.status_code == 200
    assert len(res4.get_json()["cart"]["items"]) == 0


# =============================================================================
# 5. REST Endpoints: Hold & Resume Orders
# =============================================================================
def test_api_hold_and_resume_order(test_app):
    """Asserts parking a ticket with /api/pos/cart/hold and resuming via /resume."""
    headers = {"X-Cart-ID": "test_hold_cart"}

    # Add item
    test_app.post('/api/pos/cart/item', headers=headers, json={
        "name": "Held Item",
        "price": 15.00,
        "quantity": 2
    })

    # Hold order
    res_hold = test_app.post('/api/pos/cart/hold', headers=headers, json={"notes": "Customer stepped out"})
    assert res_hold.status_code == 200
    hold_id = res_hold.get_json()["hold"]["hold_id"]
    assert hold_id.startswith("HOLD-")

    # List holds
    res_list = test_app.get('/api/pos/cart/holds')
    assert res_list.status_code == 200
    holds = res_list.get_json()["held_orders"]
    assert any(h["hold_id"] == hold_id for h in holds)

    # Resume order
    res_resume = test_app.post(f'/api/pos/cart/resume/{hold_id}', headers=headers)
    assert res_resume.status_code == 200
    restored_cart = res_resume.get_json()["cart"]
    assert len(restored_cart["items"]) == 1
    assert restored_cart["items"][0]["name"] == "Held Item"


# =============================================================================
# 6. Barcode & Hardware Scan Endpoint
# =============================================================================
def test_api_barcode_scan(test_app):
    """Asserts /api/pos/scan matches preset merchandise and customer NFC tags."""
    headers = {"X-Cart-ID": "test_scan_cart"}

    # 1. Scan valid preset merchandise SKU
    res1 = test_app.get('/api/pos/scan?barcode=ACC-SLV-001', headers=headers)
    assert res1.status_code == 200
    data1 = res1.get_json()
    assert data1["type"] == "item_added"
    assert data1["product"]["name"] == "Matte Card Sleeves (100ct)"

    # 2. Create customer with NFC UID
    cust = create_customer(
        name="Chandra Nalaar",
        phone="(555) 444-3333",
        initial_credit=15.00,
        nfc_uid="04112233445566"
    )

    # Scan NFC UID -> attaches customer
    res2 = test_app.get('/api/pos/scan?barcode=04112233445566', headers=headers)
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["type"] == "customer_attached"
    assert data2["customer"]["id"] == cust.id

    # 3. Scan invalid barcode
    res3 = test_app.get('/api/pos/scan?barcode=NON_EXISTENT_CODE', headers=headers)
    assert res3.status_code == 404


# =============================================================================
# 7. Split Tender Checkout & Double-Entry Accounting
# =============================================================================
def test_checkout_split_tender_and_ledger_commit(test_app):
    """
    Asserts complete checkout with split tender (Cash + Card + Store Credit):
      1. Commits order to pos_transactions.
      2. Generates balanced double-entry records in pos_ledger_entries (DEBITS == CREDITS).
      3. Deducts store credit in customer_credit_ledger and decrements balance.
      4. Dispatches 'pos:transaction_completed' event on event_bus.
    """
    headers = {"X-Cart-ID": "test_checkout_cart"}

    # 1. Setup Customer with $25.00 Store Credit
    cust = create_customer(
        name="Liliana Vess",
        phone="(555) 666-9999",
        initial_credit=25.00
    )
    cid = cust.id

    # 2. Attach Customer and add items
    test_app.post('/api/pos/cart/customer', headers=headers, json={"identifier": str(cid)})

    # Item 1: $30.00 (taxable, e.g. tax 8.25% = $2.48, Total = $32.48)
    test_app.post('/api/pos/cart/item', headers=headers, json={
        "name": "Collector Pack",
        "price": 30.00,
        "quantity": 1,
        "taxable": True
    })

    cart_res = test_app.get('/api/pos/cart', headers=headers).get_json()["cart"]
    grand_total = cart_res["grand_total"]  # 32.48

    # Record event bus invocations
    received_events = []
    def on_transaction_completed(**kwargs):
        received_events.append(kwargs)

    event_bus.subscribe("pos:transaction_completed", on_transaction_completed)

    # 3. Submit Split Tender Checkout:
    # Grand Total = $32.48
    # Store Credit: $10.00
    # Card: $12.48
    # Cash: $15.00 (Total tendered = $37.48, Change due = $5.00)
    checkout_res = test_app.post('/api/pos/cart/checkout', headers=headers, json={
        "tenders": {
            "store_credit": 10.00,
            "card": 12.48,
            "cash": 15.00
        },
        "notes": "Split tender test"
    })

    assert checkout_res.status_code == 200
    checkout_data = checkout_res.get_json()
    assert checkout_data["status"] == "success"
    order_id = checkout_data["order_id"]
    assert checkout_data["change_due"] == 5.00

    # 4. Verify Double-Entry Accounting in pos_ledger_entries
    with sqlite3.connect(Config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # Fetch ledger entries for this order
        cur = conn.execute(
            "SELECT account, entry_type, amount FROM pos_ledger_entries WHERE transaction_id = ?",
            (order_id,)
        )
        entries = cur.fetchall()

    assert len(entries) > 0, "No double-entry ledger rows created"

    debits = sum(r["amount"] for r in entries if r["entry_type"] == "DEBIT")
    credits = sum(r["amount"] for r in entries if r["entry_type"] == "CREDIT")

    # Double-entry invariant: Sum of Debits == Sum of Credits
    assert abs(debits - credits) < 0.01, f"Ledger out of balance: Debits={debits}, Credits={credits}"
    assert abs(debits - grand_total) < 0.01, f"Debits ({debits}) do not match grand total ({grand_total})"

    # 5. Verify customer store credit balance decremented to $15.00
    updated_cust = get_customer(cid)
    assert updated_cust.store_credit_balance == 15.00

    # Verify customer_credit_ledger contains redemption
    with sqlite3.connect(Config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT amount, transaction_type, reference_id FROM customer_credit_ledger WHERE customer_id = ? AND transaction_type = 'redemption'",
            (cid,)
        )
        redemption_row = cur.fetchone()

    assert redemption_row is not None
    assert redemption_row["amount"] == -10.00
    assert redemption_row["reference_id"] == order_id

    # 6. Verify event bus notification fired
    assert len(received_events) == 1
    assert received_events[0]["order"]["order_id"] == order_id


def test_checkout_validation_failures(test_app):
    """Asserts underpayment and unauthorized store credit return 400 errors."""
    headers = {"X-Cart-ID": "test_fail_cart"}
    test_app.post('/api/pos/cart/item', headers=headers, json={"name": "Item", "price": 50.00})

    # Underpayment: Total $54.12, Tendered $20.00
    res1 = test_app.post('/api/pos/cart/checkout', headers=headers, json={
        "tenders": {"cash": 20.00}
    })
    assert res1.status_code == 400
    assert "Insufficient payment" in res1.get_json()["message"]

    # Store credit without customer
    res2 = test_app.post('/api/pos/cart/checkout', headers=headers, json={
        "tenders": {"store_credit": 50.00, "cash": 5.00}
    })
    assert res2.status_code == 400
    assert "customer must be attached" in res2.get_json()["message"]


# =============================================================================
# 8. UI Views & Dynamic Canvas Resolution
# =============================================================================
def test_pos_view_and_default_canvas(test_app):
    """Asserts /pos renders successfully and /register redirects."""
    # 1. Default retail view
    set_setting("default_pos_view", "default-retail")
    res1 = test_app.get('/pos')
    assert res1.status_code == 200
    assert b"POS Register" in res1.data
    assert b"Current Ticket" in res1.data

    # 2. Redirect legacy /register
    res2 = test_app.get('/register')
    assert res2.status_code == 302
    assert "/pos" in res2.headers["Location"]

    # 3. Default view set to addon
    set_setting("default_pos_view", "tcg_pos")
    res3 = test_app.get('/pos')
    assert res3.status_code == 200
    assert b'data-default-canvas="addon-tcg_pos"' in res3.data


def test_ui_hooks_system():
    """Asserts UI hook rendering and canvas detection functions."""
    # has_addon_canvas should detect tcg_pos
    has_canvas = has_addon_canvas()
    assert isinstance(has_canvas, bool)

    # Render workspace toggle buttons
    toggles_html = render_addon_hook("pos:workspace_toggles")
    assert isinstance(toggles_html, str)

    # Render canvas mount
    canvas_html = render_addon_hook("pos:canvas_mount")
    assert isinstance(canvas_html, str)


def _ensure_tcg_addon():
    import os
    import shutil
    from core.config import Config
    from core.addons import addon_manager
    src = os.path.join(Config.BASE_DIR, 'data', 'custom_addons', 'tcg_pos')
    dst = os.path.join(Config.CUSTOM_ADDONS_DIR, 'tcg_pos')
    if os.path.isdir(src) and not os.path.isdir(dst):
        shutil.copytree(src, dst)
    if os.path.isdir(dst):
        addon_manager.load_addon(dst, "custom")


def test_registered_workspaces_discovery():
    """Asserts get_registered_workspaces discovers active addons declaring canvas views."""
    _ensure_tcg_addon()
    from core.addons.ui_hooks import get_registered_workspaces
    workspaces = get_registered_workspaces()
    assert isinstance(workspaces, list)
    assert len(workspaces) >= 1
    ws = next((w for w in workspaces if w["id"] == "tcg_pos"), None)
    assert ws is not None
    assert "TCG" in ws["label"]
    assert "tcg_pos/canvas.html" in ws["template_path"]


def test_pos_workspace_tabs_and_panes(test_app):
    """Asserts that /pos renders workspace tabs and dynamic addon panes correctly."""
    _ensure_tcg_addon()
    # 1. Retail view as default
    set_setting("default_pos_view", "default-retail")
    res1 = test_app.get('/pos')
    assert res1.status_code == 200
    html1 = res1.data.decode('utf-8')
    assert "pos-workspace-nav" in html1
    assert "Standard Retail" in html1
    assert 'data-target="#canvas-default-retail"' in html1
    assert 'id="canvas-default-retail"' in html1

    # 2. Addon view as default
    set_setting("default_pos_view", "tcg_pos")
    res2 = test_app.get('/pos')
    assert res2.status_code == 200
    html2 = res2.data.decode('utf-8')
    assert 'id="canvas-addon-tcg_pos"' in html2
    assert 'tab-tcg_pos' in html2


def test_manager_open_register_navigation(test_app):
    """Asserts the Open Register button is present across all Manager sub-views."""
    endpoints = ['/manager', '/manager/branding', '/manager/settings', '/manager/addons']
    for ep in endpoints:
        res = test_app.get(ep, follow_redirects=True)
        assert res.status_code == 200, f"Failed accessing {ep}"
        html = res.data.decode('utf-8')
        assert 'href="/pos"' in html, f"Open Register link missing on {ep}"
        assert 'Open Register' in html, f"'Open Register' text missing on {ep}"


def test_settings_service_sync():
    """Asserts that settings_service reads and writes store_settings.json and syncs default_pos_view."""
    from core.services.settings_service import (
        get_store_settings,
        save_store_settings,
        get_default_pos_view,
        set_default_pos_view
    )
    # Set default pos view to tcg_pos
    set_default_pos_view("tcg_pos")
    assert get_default_pos_view() == "tcg_pos"
    assert get_setting("default_pos_view") == "tcg_pos"

    # Reset back to default-retail
    set_default_pos_view("default-retail")
    assert get_default_pos_view() == "default-retail"
    assert get_setting("default_pos_view") == "default-retail"

