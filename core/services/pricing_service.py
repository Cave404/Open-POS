"""
=============================================================================
Open-POS Core Pricing Service (core/services/pricing_service.py)
=============================================================================
Pure business logic for pricing, discounts, line totals, and order subtotals.
Decoupled from presentation routes and database queries.
=============================================================================
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger("openpos.core.pricing")


class PricingService:
    @staticmethod
    def calculate_line_item(price: float, quantity: int, discount: float = 0.0) -> Dict[str, float]:
        """
        Calculates line subtotal, discount, and net total for an item.
        Ensures amounts are never negative.
        """
        unit_price = round(max(0.0, float(price)), 2)
        qty = max(0, int(quantity))
        raw_total = round(unit_price * qty, 2)
        line_discount = round(min(raw_total, max(0.0, float(discount))), 2)
        net_total = round(max(0.0, raw_total - line_discount), 2)

        return {
            "unit_price": unit_price,
            "quantity": qty,
            "gross_total": raw_total,
            "discount": line_discount,
            "net_total": net_total
        }

    @staticmethod
    def calculate_order_totals(items: List[Dict[str, Any]], order_discount: float = 0.0) -> Dict[str, float]:
        """
        Aggregates items and computes subtotal, item discounts, order discount, and net taxable totals.
        """
        subtotal = 0.0
        item_discounts = 0.0
        taxable_net = 0.0
        non_taxable_net = 0.0

        for item in items:
            p = float(item.get("price", 0.0))
            q = int(item.get("quantity", 1))
            d = float(item.get("discount", 0.0))
            is_taxable = bool(item.get("taxable", True))

            calc = PricingService.calculate_line_item(p, q, d)
            subtotal += calc["gross_total"]
            item_discounts += calc["discount"]

            if is_taxable:
                taxable_net += calc["net_total"]
            else:
                non_taxable_net += calc["net_total"]

        total_net = taxable_net + non_taxable_net
        applied_order_discount = round(min(total_net, max(0.0, float(order_discount))), 2)
        discount_total = round(item_discounts + applied_order_discount, 2)

        return {
            "subtotal": round(subtotal, 2),
            "item_discounts": round(item_discounts, 2),
            "order_discount": applied_order_discount,
            "discount_total": discount_total,
            "taxable_net": round(taxable_net, 2),
            "non_taxable_net": round(non_taxable_net, 2),
            "net_total": round(max(0.0, subtotal - discount_total), 2)
        }


pricing_service = PricingService()
