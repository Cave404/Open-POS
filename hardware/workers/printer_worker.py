"""
=============================================================================
Open-POS Thermal Printer Worker (hardware/workers/printer_worker.py)
=============================================================================
Non-blocking worker routine for rendering and transmitting ESC/POS formatted
receipts to physical or simulated thermal receipt printers.
=============================================================================
"""

import logging
from typing import Dict, Any
from hardware.drivers.escpos_driver import escpos_driver
from core.settings import get_setting

logger = logging.getLogger("openpos.hardware.printer")


def format_receipt_text(order_data: Dict[str, Any]) -> bytes:
    """
    Formats structured order data into a clean 40-column thermal receipt.
    """
    store_name = get_setting("store_name", "Open-POS Store")
    currency = get_setting("currency_symbol", "$")

    order_id = order_data.get("order_id", "N/A")
    date_str = order_data.get("date", "")
    customer = order_data.get("customer_name") or "Guest"
    items = order_data.get("items", [])
    subtotal = float(order_data.get("subtotal", 0.0))
    discount_total = float(order_data.get("discount_total", 0.0))
    tax_total = float(order_data.get("tax_total", 0.0))
    grand_total = float(order_data.get("grand_total", 0.0))
    tenders = order_data.get("tenders", {})
    change_due = float(order_data.get("change_due", 0.0))

    lines = [
        f"{store_name.center(40)}",
        "=" * 40,
        f"Order: {order_id}",
        f"Date:  {date_str}",
        f"Cust:  {customer}",
        "-" * 40,
        f"{'Item':<22}{'Qty':>4}{'Price':>7}{'Total':>7}",
        "-" * 40,
    ]

    for item in items:
        name = str(item.get("name", "Item"))[:20]
        qty = int(item.get("quantity", 1))
        price = float(item.get("price", 0.0))
        total = round(qty * price, 2)
        lines.append(f"{name:<22}{qty:>4}{currency}{price:>6.2f}{currency}{total:>6.2f}")

    lines.append("-" * 40)
    lines.append(f"{'Subtotal:':<28}{currency}{subtotal:>10.2f}")
    if discount_total > 0:
        lines.append(f"{'Discounts:':<28}-{currency}{discount_total:>9.2f}")
    lines.append(f"{'Tax:':<28}{currency}{tax_total:>10.2f}")
    lines.append("=" * 40)
    lines.append(f"{'GRAND TOTAL:':<28}{currency}{grand_total:>10.2f}")
    lines.append("=" * 40)

    for tender_type, amt in tenders.items():
        if float(amt or 0) > 0:
            lines.append(f"{tender_type.title() + ' Tender:':<28}{currency}{float(amt):>10.2f}")

    if change_due > 0:
        lines.append(f"{'Change Due:':<28}{currency}{change_due:>10.2f}")

    lines.append("\nThank you for your business!\n\n\n")

    return "\n".join(lines).encode("latin-1", errors="replace")


def print_receipt_slip(order_data: Dict[str, Any]) -> bool:
    """
    Asynchronously formats and prints a receipt slip.
    """
    printing_enabled = get_setting("printer_enabled", True)
    if not printing_enabled:
        logger.info("Printer Worker: Receipt printing disabled in settings.")
        return True

    order_id = order_data.get("order_id", "UNKNOWN")
    logger.info(f"Printer Worker: Preparing thermal receipt for ticket '{order_id}'...")

    try:
        receipt_bytes = format_receipt_text(order_data)
        success = escpos_driver.print_raw(receipt_bytes)
        if success:
            logger.info(f"Printer Worker: Receipt for '{order_id}' transmitted successfully.")
        else:
            logger.warning(f"Printer Worker: Receipt for '{order_id}' queued in simulator or printer offline.")
        return success
    except Exception as e:
        logger.error(f"Printer Worker: Printing failed for '{order_id}': {e}", exc_info=True)
        return False
