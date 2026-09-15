"""
core/routes/customer_routes.py
================================
REST API blueprint for the Customer Management subsystem.

All routes are mounted under /api/core/customers via core_customers_bp.

Financial Invariant Enforcement
--------------------------------
- No UPDATE or DELETE route is exposed for ledger entries.
- Credit operations always route through customer_service deposit/redeem
  which enforce atomic transactions and ledger appends.
"""
import logging
from flask import Blueprint, jsonify, request

from core.services.customer_service import (
    resolve_customer,
    search_customers,
    get_customer,
    get_customer_ledger,
    create_customer,
    update_customer,
    assign_nfc_badge,
    deposit_store_credit,
    redeem_store_credit,
)

logger = logging.getLogger(__name__)

core_customers_bp = Blueprint(
    'core_customers',
    __name__,
    url_prefix='/api/core/customers'
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(message: str, code: int = 400):
    return jsonify({'status': 'error', 'message': message}), code


def _ok(data: dict, code: int = 200):
    return jsonify({'status': 'success', **data}), code


# ---------------------------------------------------------------------------
# GET /api/core/customers/resolve?q=<identifier>
# ---------------------------------------------------------------------------

@core_customers_bp.route('/resolve', methods=['GET'])
def api_resolve_customer():
    """Find a customer by NFC UID, phone, name, or email.

    Query param: q — the raw identifier string.
    Returns: full customer dict or 404.
    """
    q = (request.args.get('q') or '').strip()
    if not q:
        return _err("Query parameter 'q' is required.")
    try:
        customer = resolve_customer(q)
    except Exception as exc:
        logger.error(f"resolve_customer error: {exc}", exc_info=True)
        return _err(str(exc), 500)

    if customer is None:
        return _err(f"No customer found for identifier '{q}'.", 404)
    return _ok({'customer': customer.to_dict()})


# ---------------------------------------------------------------------------
# GET /api/core/customers/search?q=<query>&limit=20
# ---------------------------------------------------------------------------

@core_customers_bp.route('/search', methods=['GET'])
def api_search_customers():
    """Autocomplete lookup for cashier register.

    Returns a list of compact summary dicts.
    """
    q = (request.args.get('q') or '').strip()
    try:
        limit = int(request.args.get('limit', 20))
        limit = max(1, min(limit, 100))
    except (TypeError, ValueError):
        limit = 20

    try:
        results = search_customers(q, limit=limit)
    except Exception as exc:
        logger.error(f"search_customers error: {exc}", exc_info=True)
        return _err(str(exc), 500)

    return jsonify(results), 200


# ---------------------------------------------------------------------------
# GET /api/core/customers/<customer_id>
# ---------------------------------------------------------------------------

@core_customers_bp.route('/<int:customer_id>', methods=['GET'])
def api_get_customer(customer_id: int):
    """Return full customer profile including lifetime stats."""
    try:
        customer = get_customer(customer_id)
    except Exception as exc:
        return _err(str(exc), 500)

    if customer is None:
        return _err(f"Customer {customer_id} not found.", 404)
    return _ok({'customer': customer.to_dict()})


# ---------------------------------------------------------------------------
# GET /api/core/customers/<customer_id>/ledger
# ---------------------------------------------------------------------------

@core_customers_bp.route('/<int:customer_id>/ledger', methods=['GET'])
def api_get_customer_ledger(customer_id: int):
    """Return paginated, immutable ledger entries (newest first).

    Query params: page (default 1), per_page (default 50, max 200).
    """
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        per_page = max(1, min(per_page, 200))
    except (TypeError, ValueError):
        page, per_page = 1, 50

    try:
        data = get_customer_ledger(customer_id, page=page, per_page=per_page)
    except Exception as exc:
        return _err(str(exc), 500)

    return jsonify(data), 200


# ---------------------------------------------------------------------------
# POST /api/core/customers
# ---------------------------------------------------------------------------

@core_customers_bp.route('', methods=['POST'])
def api_create_customer():
    """Create a new customer record.

    JSON body (all optional except name):
        name (str, required), phone, email, nfc_uid, notes,
        initial_credit (float, default 0.0), source_addon (str, default 'core')
    """
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return _err("'name' is required.")

    try:
        customer = create_customer(
            name=name,
            phone=body.get('phone'),
            email=body.get('email'),
            nfc_uid=body.get('nfc_uid'),
            notes=body.get('notes'),
            initial_credit=float(body.get('initial_credit', 0.0)),
            source_addon=body.get('source_addon', 'core'),
        )
    except ValueError as ve:
        return _err(str(ve))
    except Exception as exc:
        logger.error(f"create_customer error: {exc}", exc_info=True)
        return _err(str(exc), 500)

    return jsonify({'status': 'success', 'customer': customer.to_dict()}), 201


# ---------------------------------------------------------------------------
# PATCH /api/core/customers/<customer_id>
# ---------------------------------------------------------------------------

@core_customers_bp.route('/<int:customer_id>', methods=['PATCH'])
def api_update_customer(customer_id: int):
    """Update mutable profile fields: name, phone, email, notes."""
    body = request.get_json(silent=True) or {}
    kwargs = {}
    for field in ('name', 'phone', 'email', 'notes'):
        if field in body:
            kwargs[field] = body[field]

    if not kwargs:
        return _err("No updatable fields provided (name, phone, email, notes).")

    try:
        customer = update_customer(customer_id, **kwargs)
    except ValueError as ve:
        return _err(str(ve))
    except Exception as exc:
        logger.error(f"update_customer error: {exc}", exc_info=True)
        return _err(str(exc), 500)

    return _ok({'customer': customer.to_dict()})


# ---------------------------------------------------------------------------
# POST /api/core/customers/<customer_id>/badge
# ---------------------------------------------------------------------------

@core_customers_bp.route('/<int:customer_id>/badge', methods=['POST'])
def api_assign_badge(customer_id: int):
    """Assign a 14-char hex NFC badge UID to the customer.

    JSON body: { "nfc_uid": "04A1B2C3D4E5F6" }
    Dispatches customer:badge_assigned event (Ghost Tag Safeguard).
    """
    body = request.get_json(silent=True) or {}
    nfc_uid = (body.get('nfc_uid') or '').strip()
    if not nfc_uid:
        return _err("'nfc_uid' is required.")

    try:
        customer = assign_nfc_badge(customer_id, nfc_uid)
    except ValueError as ve:
        return _err(str(ve))
    except Exception as exc:
        logger.error(f"assign_nfc_badge error: {exc}", exc_info=True)
        return _err(str(exc), 500)

    return _ok({
        'customer': customer.to_dict(),
        'message': f"Badge {customer.nfc_uid} assigned successfully."
    })


# ---------------------------------------------------------------------------
# POST /api/core/customers/<customer_id>/credit/deposit
# ---------------------------------------------------------------------------

@core_customers_bp.route('/<int:customer_id>/credit/deposit', methods=['POST'])
def api_deposit_credit(customer_id: int):
    """Deposit store credit.

    JSON body: { "amount": 25.00, "source_addon": "tcg_pos",
                 "reference_id": "TRADE-001", "notes": "Trade-in credit" }
    """
    body = request.get_json(silent=True) or {}
    try:
        amount = float(body.get('amount', 0))
    except (TypeError, ValueError):
        return _err("'amount' must be a numeric value.")

    if amount <= 0:
        return _err("'amount' must be greater than zero.")

    try:
        customer = deposit_store_credit(
            customer_id=customer_id,
            amount=amount,
            source_addon=body.get('source_addon', 'core'),
            reference_id=body.get('reference_id'),
            notes=body.get('notes'),
        )
    except ValueError as ve:
        return _err(str(ve))
    except Exception as exc:
        logger.error(f"deposit_store_credit error: {exc}", exc_info=True)
        return _err(str(exc), 500)

    return _ok({
        'customer': customer.to_dict(),
        'new_balance': customer.store_credit_balance,
        'message': f"${amount:.2f} deposited successfully."
    })


# ---------------------------------------------------------------------------
# POST /api/core/customers/<customer_id>/credit/redeem
# ---------------------------------------------------------------------------

@core_customers_bp.route('/<int:customer_id>/credit/redeem', methods=['POST'])
def api_redeem_credit(customer_id: int):
    """Redeem store credit.

    Returns HTTP 400 if the customer has insufficient balance.

    JSON body: { "amount": 10.00, "source_addon": "core",
                 "reference_id": "TXN-042", "notes": "Applied to sale" }
    """
    body = request.get_json(silent=True) or {}
    try:
        amount = float(body.get('amount', 0))
    except (TypeError, ValueError):
        return _err("'amount' must be a numeric value.")

    if amount <= 0:
        return _err("'amount' must be greater than zero.")

    try:
        customer = redeem_store_credit(
            customer_id=customer_id,
            amount=amount,
            source_addon=body.get('source_addon', 'core'),
            reference_id=body.get('reference_id'),
            notes=body.get('notes'),
        )
    except ValueError as ve:
        return _err(str(ve))  # 400 for insufficient balance
    except Exception as exc:
        logger.error(f"redeem_store_credit error: {exc}", exc_info=True)
        return _err(str(exc), 500)

    return _ok({
        'customer': customer.to_dict(),
        'new_balance': customer.store_credit_balance,
        'message': f"${amount:.2f} redeemed successfully."
    })
