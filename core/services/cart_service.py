"""
=============================================================================
Open-POS Core Cart Service (core/services/cart_service.py)
=============================================================================
Thread-safe cart state management serving standard retail, custom addon views,
and split tender checkout.

Cart State Model:
-----------------
{
    "cart_id": "uuid4",
    "customer_id": None,
    "customer_name": None,
    "customer_credit": 0.00,
    "credit_applied": 0.00,
    "items": [
        {
            "item_id": "str",
            "sku": "str",
            "name": "str",
            "price": 0.00,
            "quantity": 1,
            "discount": 0.00,
            "taxable": True,
            "metadata": {}  # For addon data (Scryfall ID, condition, foil, trade-in flag)
        }
    ],
    "discount_total": 0.00,
    "order_discount": 0.00,
    "subtotal": 0.00,
    "tax_rate": 0.0825,
    "tax_total": 0.00,
    "grand_total": 0.00
}
=============================================================================
"""

import json
import uuid
import threading
import logging
from typing import Dict, Any, List, Optional
from core.settings import get_setting
from core.db import get_db_connection, execute_sql

logger = logging.getLogger(__name__)


class CartService:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._carts: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def get_instance(cls) -> "CartService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = CartService()
            return cls._instance

    def _get_default_tax_rate(self) -> float:
        """Retrieves tax rate from settings and converts percentage to decimal (e.g. 8.25 -> 0.0825)."""
        rate_pct = get_setting("tax_rate", 8.25)
        try:
            return round(float(rate_pct) / 100.0, 4)
        except (ValueError, TypeError):
            return 0.0825

    def _create_empty_cart(self, cart_id: Optional[str] = None) -> Dict[str, Any]:
        tax_rate = self._get_default_tax_rate()
        return {
            "cart_id": cart_id or str(uuid.uuid4()),
            "customer_id": None,
            "customer_name": None,
            "customer_credit": 0.00,
            "credit_applied": 0.00,
            "items": [],
            "discount_total": 0.00,
            "order_discount": 0.00,
            "subtotal": 0.00,
            "tax_rate": tax_rate,
            "tax_total": 0.00,
            "grand_total": 0.00
        }

    def _recalculate(self, cart: Dict[str, Any]) -> None:
        """
        Recalculates subtotal, line discounts, taxes, and grand total.
        Guarantees non-negative monetary amounts and caps credit applied.
        """
        items = cart.get("items", [])
        tax_rate = cart.get("tax_rate", self._get_default_tax_rate())

        subtotal = 0.0
        line_discount_sum = 0.0
        taxable_net_total = 0.0
        non_taxable_net_total = 0.0

        for item in items:
            qty = max(1, int(item.get("quantity", 1)))
            unit_price = max(0.0, float(item.get("price", 0.0)))
            unit_disc = max(0.0, float(item.get("discount", 0.0)))
            line_gross = round(unit_price * qty, 2)
            line_disc = round(min(unit_price, unit_disc) * qty, 2)
            line_net = max(0.0, round(line_gross - line_disc, 2))

            subtotal += line_gross
            line_discount_sum += line_disc

            if item.get("taxable", True):
                taxable_net_total += line_net
            else:
                non_taxable_net_total += line_net

        order_discount = max(0.0, float(cart.get("order_discount", 0.0)))
        total_discount = round(line_discount_sum + order_discount, 2)

        # Distribute order discount proportionally if present, or apply directly
        net_after_order_disc = max(0.0, (taxable_net_total + non_taxable_net_total) - order_discount)
        if taxable_net_total + non_taxable_net_total > 0:
            taxable_share = taxable_net_total / (taxable_net_total + non_taxable_net_total)
            taxable_base = max(0.0, net_after_order_disc * taxable_share)
        else:
            taxable_base = 0.0

        tax_total = round(taxable_base * tax_rate, 2)
        grand_total = max(0.0, round(net_after_order_disc + tax_total, 2))

        # Adjust credit applied so it does not exceed customer credit or grand total
        customer_credit = max(0.0, float(cart.get("customer_credit", 0.0)))
        current_credit = max(0.0, float(cart.get("credit_applied", 0.0)))
        credit_applied = round(min(current_credit, customer_credit, grand_total), 2)

        cart["subtotal"] = round(subtotal, 2)
        cart["discount_total"] = total_discount
        cart["tax_rate"] = tax_rate
        cart["tax_total"] = tax_total
        cart["grand_total"] = grand_total
        cart["credit_applied"] = credit_applied

    def get_or_create_cart(self, cart_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if not cart_id or cart_id not in self._carts:
                cid = cart_id or str(uuid.uuid4())
                self._carts[cid] = self._create_empty_cart(cid)
                return dict(self._carts[cid])
            return dict(self._carts[cart_id])

    def add_item(
        self,
        cart_id: str,
        name: str,
        price: float,
        quantity: int = 1,
        sku: str = "",
        taxable: bool = True,
        discount: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        with self._lock:
            if cart_id not in self._carts:
                self._carts[cart_id] = self._create_empty_cart(cart_id)

            cart = self._carts[cart_id]
            clean_name = str(name).strip()
            unit_price = round(max(0.0, float(price)), 2)
            qty = max(1, int(quantity))
            sku_val = str(sku or "").strip()
            meta = metadata if isinstance(metadata, dict) else {}

            # Check if an identical item already exists (matching SKU, name, price, taxable, and metadata)
            found = False
            for existing in cart["items"]:
                if (
                    existing["sku"] == sku_val
                    and existing["name"] == clean_name
                    and abs(existing["price"] - unit_price) < 0.001
                    and existing["taxable"] == bool(taxable)
                    and existing.get("metadata", {}) == meta
                ):
                    existing["quantity"] += qty
                    found = True
                    break

            if not found:
                item_id = str(uuid.uuid4())[:8]
                new_item = {
                    "item_id": item_id,
                    "sku": sku_val,
                    "name": clean_name,
                    "price": unit_price,
                    "quantity": qty,
                    "discount": round(max(0.0, float(discount)), 2),
                    "taxable": bool(taxable),
                    "metadata": meta
                }
                cart["items"].append(new_item)

            self._recalculate(cart)
            return dict(cart)

    def update_quantity(self, cart_id: str, item_id: str, quantity: int) -> Dict[str, Any]:
        with self._lock:
            if cart_id not in self._carts:
                self._carts[cart_id] = self._create_empty_cart(cart_id)

            cart = self._carts[cart_id]
            qty = int(quantity)
            if qty <= 0:
                cart["items"] = [item for item in cart["items"] if item["item_id"] != item_id]
            else:
                for item in cart["items"]:
                    if item["item_id"] == item_id:
                        item["quantity"] = qty
                        break

            self._recalculate(cart)
            return dict(cart)

    def update_item(
        self,
        cart_id: str,
        item_id: str,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        discount: Optional[float] = None,
        taxable: Optional[bool] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        with self._lock:
            if cart_id not in self._carts:
                self._carts[cart_id] = self._create_empty_cart(cart_id)

            cart = self._carts[cart_id]
            for item in list(cart["items"]):
                if item["item_id"] == item_id:
                    if quantity is not None:
                        q = int(quantity)
                        if q <= 0:
                            cart["items"].remove(item)
                            break
                        item["quantity"] = q
                    if price is not None:
                        item["price"] = round(max(0.0, float(price)), 2)
                    if discount is not None:
                        item["discount"] = round(max(0.0, float(discount)), 2)
                    if taxable is not None:
                        item["taxable"] = bool(taxable)
                    if metadata is not None and isinstance(metadata, dict):
                        item.setdefault("metadata", {}).update(metadata)
                    break

            self._recalculate(cart)
            return dict(cart)

    def remove_item(self, cart_id: str, item_id: str) -> Dict[str, Any]:
        with self._lock:
            if cart_id in self._carts:
                cart = self._carts[cart_id]
                cart["items"] = [item for item in cart["items"] if item["item_id"] != item_id]
                self._recalculate(cart)
                return dict(cart)
            return self._create_empty_cart(cart_id)

    def attach_customer(
        self,
        cart_id: str,
        customer_id: int,
        customer_name: str,
        customer_credit: float = 0.0,
        nfc_uid: Optional[str] = None
    ) -> Dict[str, Any]:
        with self._lock:
            if cart_id not in self._carts:
                self._carts[cart_id] = self._create_empty_cart(cart_id)

            cart = self._carts[cart_id]
            cart["customer_id"] = int(customer_id)
            cart["customer_name"] = str(customer_name or "").strip()
            cart["customer_credit"] = round(max(0.0, float(customer_credit)), 2)
            cart["nfc_uid"] = str(nfc_uid or "").strip() if nfc_uid else None
            self._recalculate(cart)
            return dict(cart)

    def detach_customer(self, cart_id: str) -> Dict[str, Any]:
        with self._lock:
            if cart_id in self._carts:
                cart = self._carts[cart_id]
                cart["customer_id"] = None
                cart["customer_name"] = None
                cart["customer_credit"] = 0.00
                cart["credit_applied"] = 0.00
                cart["nfc_uid"] = None
                self._recalculate(cart)
                return dict(cart)
            return self._create_empty_cart(cart_id)

    def apply_store_credit(self, cart_id: str, amount: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            if cart_id not in self._carts:
                self._carts[cart_id] = self._create_empty_cart(cart_id)

            cart = self._carts[cart_id]
            customer_credit = max(0.0, float(cart.get("customer_credit", 0.0)))
            grand_total = max(0.0, float(cart.get("grand_total", 0.0)))

            if amount is None:
                # Max credit possible
                cart["credit_applied"] = round(min(customer_credit, grand_total), 2)
            else:
                req_amount = max(0.0, float(amount))
                cart["credit_applied"] = round(min(req_amount, customer_credit, grand_total), 2)

            self._recalculate(cart)
            return dict(cart)

    def apply_discount(self, cart_id: str, amount: float) -> Dict[str, Any]:
        with self._lock:
            if cart_id not in self._carts:
                self._carts[cart_id] = self._create_empty_cart(cart_id)

            cart = self._carts[cart_id]
            cart["order_discount"] = round(max(0.0, float(amount)), 2)
            self._recalculate(cart)
            return dict(cart)

    def clear(self, cart_id: str) -> Dict[str, Any]:
        with self._lock:
            self._carts[cart_id] = self._create_empty_cart(cart_id)
            return dict(self._carts[cart_id])

    # -------------------------------------------------------------------------
    # Hold & Recall Orders
    # -------------------------------------------------------------------------
    def hold_order(self, cart_id: str, notes: str = "") -> Dict[str, Any]:
        with self._lock:
            if cart_id not in self._carts or not self._carts[cart_id].get("items"):
                raise ValueError("Cannot hold an empty cart.")

            cart = self._carts[cart_id]
            hold_id = f"HOLD-{uuid.uuid4().hex[:6].upper()}"
            customer_name = cart.get("customer_name") or "Guest Customer"
            cart_json = json.dumps(cart)

            with get_db_connection() as conn:
                execute_sql(
                    conn,
                    """
                    INSERT INTO pos_held_orders (hold_id, customer_name, cart_data, notes)
                    VALUES (?, ?, ?, ?)
                    """,
                    (hold_id, customer_name, cart_json, str(notes or "").strip())
                )

            # Reset the active cart
            self._carts[cart_id] = self._create_empty_cart(cart_id)
            return {"hold_id": hold_id, "customer_name": customer_name, "notes": notes}

    def list_held_orders(self) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cur = execute_sql(
                conn,
                "SELECT id, hold_id, customer_name, cart_data, notes, created_at FROM pos_held_orders ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
            results = []
            for r in rows:
                row_dict = dict(r) if hasattr(r, 'keys') else {
                    "id": r[0], "hold_id": r[1], "customer_name": r[2],
                    "cart_data": r[3], "notes": r[4], "created_at": r[5]
                }
                try:
                    parsed_cart = json.loads(row_dict["cart_data"])
                    item_count = sum(i.get("quantity", 1) for i in parsed_cart.get("items", []))
                    total = parsed_cart.get("grand_total", 0.0)
                except Exception:
                    item_count = 0
                    total = 0.0

                results.append({
                    "id": row_dict["id"],
                    "hold_id": row_dict["hold_id"],
                    "customer_name": row_dict["customer_name"],
                    "notes": row_dict["notes"],
                    "item_count": item_count,
                    "grand_total": total,
                    "created_at": str(row_dict["created_at"])
                })
            return results

    def resume_held_order(self, hold_id: str, cart_id: str) -> Dict[str, Any]:
        with self._lock:
            with get_db_connection() as conn:
                cur = execute_sql(
                    conn,
                    "SELECT cart_data FROM pos_held_orders WHERE hold_id = ?",
                    (hold_id,)
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Held order '{hold_id}' not found.")

                raw_json = row['cart_data'] if hasattr(row, '__getitem__') and not isinstance(row, tuple) else row[0]
                restored_cart = json.loads(raw_json)

                # Delete from held orders
                execute_sql(conn, "DELETE FROM pos_held_orders WHERE hold_id = ?", (hold_id,))

            restored_cart["cart_id"] = cart_id
            self._recalculate(restored_cart)
            self._carts[cart_id] = restored_cart
            return dict(restored_cart)


# Global singleton instance
cart_service = CartService.get_instance()
