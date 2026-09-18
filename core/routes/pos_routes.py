"""
=============================================================================
Open-POS Core POS Register & Checkout REST Controller
=============================================================================
Governs:
  1. Main Register UI (/pos) with dynamic canvas resolution & store branding.
  2. Cart State Management REST endpoints (/api/pos/cart/*).
  3. Barcode & Omni-Search lookup (/api/pos/scan, /api/pos/products).
  4. Customer loyalty & NFC attachment with store credit hydration.
  5. Split Tender Checkout (Cash, Card, Store Credit) with double-entry
     accounting ledger commits and event_bus dispatch.
=============================================================================
"""

import os
import json
import uuid
import logging
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, session, current_app

from core.config import Config
from core.settings import get_setting, get_all_settings
from core.db import get_db_connection, execute_sql
from core.events import event_bus
from core.services.cart_service import cart_service
from core.services.customer_service import resolve_customer, get_customer, redeem_store_credit
from core.addons.ui_hooks import has_addon_canvas, get_addon_canvases

logger = logging.getLogger(__name__)

pos_bp = Blueprint(
    'pos',
    __name__,
    template_folder='../../templates',
    static_folder='../../static'
)


# -----------------------------------------------------------------------------
# Database Migration Runner
# -----------------------------------------------------------------------------
def run_pos_migrations() -> None:
    """Executes the POS register schema migrations idempotently."""
    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    if engine in ('postgres', 'postgresql'):
        sql_file = os.path.join(Config.BASE_DIR, 'migrations', 'core_003_add_pos_register.pgsql.sql')
    else:
        sql_file = os.path.join(Config.BASE_DIR, 'migrations', 'core_003_add_pos_register.sqlite.sql')

    if not os.path.isfile(sql_file):
        logger.error(f"POS migration file not found: {sql_file}")
        return

    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_script = f.read()

    try:
        with get_db_connection() as conn:
            if engine in ('postgres', 'postgresql'):
                execute_sql(conn, sql_script)
            else:
                conn.executescript(sql_script)
        logger.info("POS register database migrations executed successfully.")
    except Exception as e:
        logger.error(f"Error running POS migrations: {e}", exc_info=True)


# -----------------------------------------------------------------------------
# Quick-Key Preset Products Catalog
# -----------------------------------------------------------------------------
DEFAULT_PRESET_PRODUCTS = [
    {"sku": "ACC-SLV-001", "name": "Matte Card Sleeves (100ct)", "price": 11.99, "category": "Accessories", "icon": "🛡️", "taxable": True},
    {"sku": "ACC-DKB-002", "name": "Deck Box (80+ Cards)", "price": 4.99, "category": "Accessories", "icon": "📦", "taxable": True},
    {"sku": "ACC-MAT-003", "name": "Custom Stitched Playmat", "price": 24.99, "category": "Accessories", "icon": "🎨", "taxable": True},
    {"sku": "ACC-DCE-004", "name": "Spindown / Dice Set", "price": 7.49, "category": "Accessories", "icon": "🎲", "taxable": True},
    {"sku": "TCG-BST-001", "name": "Booster Pack (Standard)", "price": 4.99, "category": "TCG Sealed", "icon": "🃏", "taxable": True},
    {"sku": "TCG-BDL-002", "name": "Collector Booster Pack", "price": 24.99, "category": "TCG Sealed", "icon": "✨", "taxable": True},
    {"sku": "TCG-EVT-001", "name": "Weekly Tournament Entry", "price": 10.00, "category": "Events", "icon": "🎟️", "taxable": False},
    {"sku": "FNB-SDA-001", "name": "Cold Beverage / Soda", "price": 2.25, "category": "Snacks", "icon": "🥤", "taxable": True},
    {"sku": "FNB-SNK-002", "name": "Gourmet Candy / Snack", "price": 2.50, "category": "Snacks", "icon": "🍫", "taxable": True},
]


def _get_active_cart_id() -> str:
    """Resolves or establishes a stable cart ID from headers or session."""
    cid = request.headers.get("X-Cart-ID")
    if not cid:
        cid = session.get("pos_cart_id")
    if not cid:
        cid = "default_register_cart"
        session["pos_cart_id"] = cid
    return cid


# -----------------------------------------------------------------------------
# HTML UI Register Views
# -----------------------------------------------------------------------------
@pos_bp.route('/pos', methods=['GET'])
def pos_register_view():
    """Renders the Core POS Register UI with the active default canvas."""
    default_pos_view = get_setting('default_pos_view', 'default-retail')
    store_name = get_setting('store_name', 'Open-POS System')
    store_logo_url = get_setting('store_logo_url', '')
    currency_symbol = get_setting('currency_symbol', '$')
    tax_rate = get_setting('tax_rate', 8.25)

    # Determine default active canvas
    active_canvas = "default-retail"
    if default_pos_view and default_pos_view != "default-retail":
        active_canvas = f"addon-{default_pos_view}"

    canvases = get_addon_canvases()
    has_canvas_switcher = len(canvases) > 0

    return render_template(
        'pos/register.html',
        store_name=store_name,
        store_logo_url=store_logo_url,
        currency_symbol=currency_symbol,
        tax_rate=tax_rate,
        default_canvas=active_canvas,
        default_pos_view=default_pos_view,
        has_canvas_switcher=has_canvas_switcher,
        canvases=canvases
    )


@pos_bp.route('/register', methods=['GET'])
def legacy_register_redirect():
    """Redirects legacy /register route to standard /pos."""
    return redirect('/pos')


# -----------------------------------------------------------------------------
# Core Cart REST Endpoints
# -----------------------------------------------------------------------------
@pos_bp.route('/api/pos/cart', methods=['GET'])
def api_get_cart():
    """Delivers the current active unified cart state."""
    cid = _get_active_cart_id()
    cart = cart_service.get_or_create_cart(cid)
    return jsonify({"status": "success", "cart": cart})


@pos_bp.route('/api/pos/cart/item', methods=['POST'])
def api_add_item():
    """Adds a line item with optional custom addon metadata to the cart."""
    cid = _get_active_cart_id()
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    if not name or not str(name).strip():
        return jsonify({"status": "error", "message": "Item name is required."}), 400

    try:
        price = float(data.get("price", 0.0))
        if price < 0.0:
            raise ValueError("Negative price")
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid item price."}), 400

    qty = max(1, int(data.get("quantity", 1)))
    sku = str(data.get("sku", "")).strip()
    taxable = bool(data.get("taxable", True))
    discount = float(data.get("discount", 0.0))
    metadata = data.get("metadata", {})

    cart = cart_service.add_item(
        cart_id=cid,
        name=name,
        price=price,
        quantity=qty,
        sku=sku,
        taxable=taxable,
        discount=discount,
        metadata=metadata
    )
    return jsonify({"status": "success", "cart": cart})


@pos_bp.route('/api/pos/cart/item/<item_id>', methods=['PATCH'])
def api_update_item(item_id: str):
    """Updates item quantity, price, discount, or custom metadata."""
    cid = _get_active_cart_id()
    data = request.get_json(silent=True) or {}

    quantity = data.get("quantity")
    price = data.get("price")
    discount = data.get("discount")
    taxable = data.get("taxable")
    metadata = data.get("metadata")

    cart = cart_service.update_item(
        cart_id=cid,
        item_id=item_id,
        quantity=quantity,
        price=price,
        discount=discount,
        taxable=taxable,
        metadata=metadata
    )
    return jsonify({"status": "success", "cart": cart})


@pos_bp.route('/api/pos/cart/item/<item_id>', methods=['DELETE'])
def api_remove_item(item_id: str):
    """Removes a specific line item from the active cart."""
    cid = _get_active_cart_id()
    cart = cart_service.remove_item(cid, item_id)
    return jsonify({"status": "success", "cart": cart})


@pos_bp.route('/api/pos/cart/customer', methods=['POST'])
def api_attach_customer():
    """
    Attaches a customer to the active cart using phone, name, or NFC UID.
    Hydrates customer store credit balance automatically.
    """
    cid = _get_active_cart_id()
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier") or data.get("customer_id") or data.get("nfc_uid") or data.get("phone")

    if not identifier:
        return jsonify({"status": "error", "message": "Customer identifier (phone, name, or NFC UID) required."}), 400

    cust = None
    if "customer_id" in data and data["customer_id"] is not None:
        try:
            cust = get_customer(int(data["customer_id"]))
        except (ValueError, TypeError):
            pass

    if not cust and identifier:
        if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.strip().isdigit()):
            try:
                cust = get_customer(int(identifier))
            except (ValueError, TypeError):
                pass
        if not cust:
            cust = resolve_customer(str(identifier))

    if not cust:
        return jsonify({"status": "error", "message": f"Customer '{identifier}' not found."}), 404

    cust_dict = cust.to_dict() if hasattr(cust, 'to_dict') else cust
    cart = cart_service.attach_customer(
        cart_id=cid,
        customer_id=cust_dict["id"],
        customer_name=cust_dict["name"],
        customer_credit=cust_dict["store_credit_balance"],
        nfc_uid=cust_dict.get("nfc_uid")
    )
    return jsonify({
        "status": "success",
        "customer": cust_dict,
        "cart": cart
    })


@pos_bp.route('/api/pos/cart/customer', methods=['DELETE'])
def api_detach_customer():
    """Detaches the active customer from the cart."""
    cid = _get_active_cart_id()
    cart = cart_service.detach_customer(cid)
    return jsonify({"status": "success", "cart": cart})


@pos_bp.route('/api/pos/cart/credit', methods=['POST'])
def api_apply_store_credit():
    """Applies customer store credit up to balance or total due."""
    cid = _get_active_cart_id()
    data = request.get_json(silent=True) or {}
    amount = data.get("amount")
    if amount is not None:
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return jsonify({"status": "error", "message": "Invalid credit amount."}), 400

    cart = cart_service.apply_store_credit(cid, amount=amount)
    return jsonify({"status": "success", "cart": cart})


@pos_bp.route('/api/pos/cart/discount', methods=['POST'])
def api_apply_discount():
    """Applies order-level discount amount to the ticket."""
    cid = _get_active_cart_id()
    data = request.get_json(silent=True) or {}
    amount = float(data.get("amount", 0.0))
    cart = cart_service.apply_discount(cid, amount)
    return jsonify({"status": "success", "cart": cart})


@pos_bp.route('/api/pos/cart/clear', methods=['POST'])
def api_clear_cart():
    """Resets the active cart to empty."""
    cid = _get_active_cart_id()
    cart = cart_service.clear(cid)
    return jsonify({"status": "success", "cart": cart})


@pos_bp.route('/api/pos/cart/hold', methods=['POST'])
def api_hold_cart():
    """Parks the current cart into pos_held_orders and clears active ticket."""
    cid = _get_active_cart_id()
    data = request.get_json(silent=True) or {}
    notes = data.get("notes", "")

    try:
        result = cart_service.hold_order(cid, notes)
        empty_cart = cart_service.get_or_create_cart(cid)
        return jsonify({
            "status": "success",
            "hold": result,
            "cart": empty_cart
        })
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400


@pos_bp.route('/api/pos/cart/holds', methods=['GET'])
def api_list_holds():
    """Returns all currently held orders."""
    holds = cart_service.list_held_orders()
    return jsonify({"status": "success", "held_orders": holds})


@pos_bp.route('/api/pos/cart/resume/<hold_id>', methods=['POST'])
def api_resume_hold(hold_id: str):
    """Restores a held order onto the active ticket."""
    cid = _get_active_cart_id()
    try:
        cart = cart_service.resume_held_order(hold_id, cid)
        return jsonify({"status": "success", "cart": cart})
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 404


# -----------------------------------------------------------------------------
# Barcode Scan & Omni-Search Endpoints
# -----------------------------------------------------------------------------
@pos_bp.route('/api/pos/products', methods=['GET'])
def api_get_products():
    """Returns preset retail products for the quick-key grid."""
    return jsonify({"status": "success", "products": DEFAULT_PRESET_PRODUCTS})


@pos_bp.route('/api/pos/scan', methods=['GET'])
def api_scan_barcode():
    """
    Scans a barcode or SKU. If matched, automatically adds the item to the cart.
    Query param: ?barcode=...
    """
    cid = _get_active_cart_id()
    barcode = str(request.args.get("barcode", "")).strip()
    if not barcode:
        return jsonify({"status": "error", "message": "Barcode parameter is required."}), 400

    # 1. Search in preset retail products
    matched_product = None
    for p in DEFAULT_PRESET_PRODUCTS:
        if p["sku"].lower() == barcode.lower():
            matched_product = p
            break

    # 2. Search in custom singles/inventory table if available
    if not matched_product:
        try:
            with get_db_connection() as conn:
                cur = execute_sql(
                    conn,
                    "SELECT * FROM singles_inventory WHERE scryfall_id = ? OR card_name = ? LIMIT 1",
                    (barcode, barcode)
                )
                row = cur.fetchone()
                if row:
                    row_dict = dict(row) if hasattr(row, 'keys') else {}
                    matched_product = {
                        "sku": row_dict.get("scryfall_id", barcode),
                        "name": row_dict.get("card_name", barcode),
                        "price": float(row_dict.get("sell_price", 0.0) or 0.0),
                        "taxable": True,
                        "metadata": {
                            "condition": row_dict.get("condition", "NM"),
                            "is_foil": bool(row_dict.get("is_foil", 0))
                        }
                    }
        except Exception:
            pass

    # 3. Fallback: Check if barcode is an NFC UID for customer loyalty tap
    if not matched_product and len(barcode) >= 14:
        cust = resolve_customer(barcode)
        if cust:
            cust_dict = cust.to_dict() if hasattr(cust, 'to_dict') else cust
            cart = cart_service.attach_customer(
                cart_id=cid,
                customer_id=cust_dict["id"],
                customer_name=cust_dict["name"],
                customer_credit=cust_dict["store_credit_balance"],
                nfc_uid=cust_dict.get("nfc_uid")
            )
            return jsonify({
                "status": "success",
                "type": "customer_attached",
                "customer": cust_dict,
                "cart": cart
            })

    if not matched_product:
        return jsonify({
            "status": "error",
            "message": f"No merchandise or customer matched barcode: '{barcode}'."
        }), 404

    # Add matched merchandise to active cart
    cart = cart_service.add_item(
        cart_id=cid,
        name=matched_product["name"],
        price=matched_product["price"],
        quantity=1,
        sku=matched_product.get("sku", ""),
        taxable=matched_product.get("taxable", True),
        metadata=matched_product.get("metadata", {})
    )
    return jsonify({
        "status": "success",
        "type": "item_added",
        "product": matched_product,
        "cart": cart
    })


# -----------------------------------------------------------------------------
# Split Tender Checkout & Double-Entry Accounting
# -----------------------------------------------------------------------------
@pos_bp.route('/api/pos/cart/checkout', methods=['POST'])
def api_checkout():
    """
    Validates payment amounts, commits transaction to double-entry ledger,
    deducts customer store credit if used, dispatches 'pos:transaction_completed' event,
    and returns complete receipt data.

    Payload:
    {
        "tenders": {
            "cash": 20.00,
            "card": 0.00,
            "store_credit": 5.00
        },
        "notes": "Optional receipt note"
    }
    """
    cid = _get_active_cart_id()
    cart = cart_service.get_or_create_cart(cid)

    if not cart.get("items"):
        return jsonify({"status": "error", "message": "Cannot checkout an empty ticket."}), 400

    data = request.get_json(silent=True) or {}
    tenders = data.get("tenders", {})
    notes = str(data.get("notes", "")).strip()

    # Normalize split tender inputs
    cash_tendered = round(max(0.0, float(tenders.get("cash", 0.0))), 2)
    card_tendered = round(max(0.0, float(tenders.get("card", 0.0))), 2)
    credit_tendered = round(max(0.0, float(tenders.get("store_credit", 0.0))), 2)

    grand_total = cart["grand_total"]
    total_tendered = round(cash_tendered + card_tendered + credit_tendered, 2)

    if total_tendered < grand_total:
        underpaid = round(grand_total - total_tendered, 2)
        return jsonify({
            "status": "error",
            "message": f"Insufficient payment tendered. Remaining due: ${underpaid:.2f}"
        }), 400

    # Calculate change due (only from cash tender)
    non_cash = card_tendered + credit_tendered
    cash_required = max(0.0, grand_total - non_cash)
    change_due = round(max(0.0, cash_tendered - cash_required), 2)
    cash_net = round(cash_tendered - change_due, 2)

    # 1. Store Credit Validation & Deduction
    customer_id = cart.get("customer_id")
    if credit_tendered > 0:
        if not customer_id:
            return jsonify({
                "status": "error",
                "message": "A customer must be attached to tender store credit."
            }), 400

        customer_credit = cart.get("customer_credit", 0.0)
        if credit_tendered > customer_credit:
            return jsonify({
                "status": "error",
                "message": f"Tendered store credit (${credit_tendered:.2f}) exceeds customer balance (${customer_credit:.2f})."
            }), 400

    order_id = f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    # Redeem customer store credit in ledger if tendered
    if credit_tendered > 0 and customer_id:
        try:
            redeem_store_credit(
                customer_id=customer_id,
                amount=credit_tendered,
                source_addon="core_pos",
                reference_id=order_id,
                notes=f"Store credit redemption for ticket {order_id}"
            )
        except Exception as ce:
            logger.error(f"Store credit redemption failed: {ce}", exc_info=True)
            return jsonify({
                "status": "error",
                "message": f"Customer credit ledger redemption failed: {str(ce)}"
            }), 400

    # 2. Commit Order & Double-Entry Accounting Ledger
    items_json = json.dumps(cart["items"])
    metadata_json = json.dumps({"notes": notes, "cart_id": cid})

    try:
        with get_db_connection() as conn:
            # 2a. Insert transaction header record
            execute_sql(
                conn,
                """
                INSERT INTO pos_transactions (
                    order_id, customer_id, customer_name, subtotal, discount_total,
                    tax_rate, tax_total, grand_total, credit_applied, cash_tendered,
                    card_tendered, change_due, status, items_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
                """,
                (
                    order_id,
                    customer_id,
                    cart.get("customer_name"),
                    cart["subtotal"],
                    cart["discount_total"],
                    cart["tax_rate"],
                    cart["tax_total"],
                    cart["grand_total"],
                    credit_tendered,
                    cash_tendered,
                    card_tendered,
                    change_due,
                    items_json,
                    metadata_json
                )
            )

            # 2b. Double-Entry Accounting Entries
            # Balanced Rule: Sum of Debits == Sum of Credits
            # DEBITS (Assets received / Customer liability settled):
            if cash_net > 0:
                execute_sql(conn, """
                    INSERT INTO pos_ledger_entries (transaction_id, account, entry_type, amount, notes)
                    VALUES (?, 'cash', 'DEBIT', ?, 'Cash tendered for sale')
                """, (order_id, cash_net))

            if card_tendered > 0:
                execute_sql(conn, """
                    INSERT INTO pos_ledger_entries (transaction_id, account, entry_type, amount, notes)
                    VALUES (?, 'card', 'DEBIT', ?, 'Card processing settlement')
                """, (order_id, card_tendered))

            if credit_tendered > 0:
                execute_sql(conn, """
                    INSERT INTO pos_ledger_entries (transaction_id, account, entry_type, amount, notes)
                    VALUES (?, 'customer_store_credit', 'DEBIT', ?, 'Store credit liability redemption')
                """, (order_id, credit_tendered))

            # CREDITS (Revenue recognized & Tax collected):
            # Net sales revenue = subtotal - line_discounts - order_discounts
            net_revenue = max(0.0, round(cart["subtotal"] - cart["discount_total"], 2))
            if net_revenue > 0:
                execute_sql(conn, """
                    INSERT INTO pos_ledger_entries (transaction_id, account, entry_type, amount, notes)
                    VALUES (?, 'sales_revenue', 'CREDIT', ?, 'Sales merchandise revenue')
                """, (order_id, net_revenue))

            if cart["tax_total"] > 0:
                execute_sql(conn, """
                    INSERT INTO pos_ledger_entries (transaction_id, account, entry_type, amount, notes)
                    VALUES (?, 'sales_tax_payable', 'CREDIT', ?, 'Sales tax collected')
                """, (order_id, cart["tax_total"]))

    except Exception as dbe:
        logger.error(f"Failed to commit transaction to database: {dbe}", exc_info=True)
        return jsonify({"status": "error", "message": f"Database commit failure: {str(dbe)}"}), 500

    # 3. Assemble Receipt Data
    receipt_data = {
        "order_id": order_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "customer_name": cart.get("customer_name") or "Guest",
        "items": list(cart["items"]),
        "subtotal": cart["subtotal"],
        "discount_total": cart["discount_total"],
        "tax_total": cart["tax_total"],
        "grand_total": cart["grand_total"],
        "tenders": {
            "cash": cash_tendered,
            "card": card_tendered,
            "store_credit": credit_tendered
        },
        "change_due": change_due,
        "notes": notes
    }

    # 4. Dispatch Event Bus Notification
    event_bus.dispatch("pos:transaction_completed", order=receipt_data)

    # 5. Clear active cart state
    cart_service.clear(cid)

    return jsonify({
        "status": "success",
        "order_id": order_id,
        "receipt": receipt_data,
        "change_due": change_due
    })
