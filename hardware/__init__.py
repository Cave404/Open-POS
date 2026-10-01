"""
=============================================================================
Open-POS Hardware Subsystem Layer (hardware/)
=============================================================================
Non-blocking peripheral worker threads and device drivers:
  - hardware.dispatcher: Asynchronous FIFO queue worker pool.
  - hardware.workers: Printer, Drawer, and NFC workers.
  - hardware.drivers: ESC/POS and Serial drivers.
=============================================================================
"""

import logging
from hardware.dispatcher import HardwareDispatcher, hardware_dispatcher
from hardware.workers.drawer_worker import kick_cash_drawer
from hardware.workers.printer_worker import print_receipt_slip
from hardware.workers.nfc_worker import start_nfc_worker, stop_nfc_worker
from core.events import event_bus

logger = logging.getLogger("openpos.hardware")

_events_wired = False


def wire_hardware_events():
    """
    Wires core business events (e.g. checkout completed) to asynchronous
    hardware worker routines, preventing peripheral latency from blocking UI threads.
    """
    global _events_wired
    if _events_wired:
        return
    _events_wired = True

    def _on_transaction_completed(**payload):
        order_data = payload.get("order") or payload.get("receipt") or payload
        # Dispatch non-blocking hardware actions to background worker thread
        hardware_dispatcher.dispatch("kick_drawer", kick_cash_drawer)
        hardware_dispatcher.dispatch("print_receipt", print_receipt_slip, order_data)

    event_bus.subscribe("pos:transaction_completed", _on_transaction_completed)
    logger.info("Hardware subsystem: Core events wired to hardware dispatcher.")


# Automatically wire hardware events when layer is imported
wire_hardware_events()

__all__ = [
    "HardwareDispatcher",
    "hardware_dispatcher",
    "kick_cash_drawer",
    "print_receipt_slip",
    "start_nfc_worker",
    "stop_nfc_worker",
    "wire_hardware_events",
]
