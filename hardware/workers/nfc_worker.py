"""
=============================================================================
Open-POS NFC Polling Worker (hardware/workers/nfc_worker.py)
=============================================================================
Non-blocking worker thread that polls connected USB/Serial NFC readers and
dispatches badge tap events to core.events.event_bus.
=============================================================================
"""

import time
import threading
import logging
from typing import Optional
from hardware.drivers.serial_nfc import serial_nfc_driver
from core.events import event_bus

logger = logging.getLogger("openpos.hardware.nfc_worker")

_worker_thread: Optional[threading.Thread] = None
_running = False


def _poll_loop():
    global _running
    last_uid = None
    last_seen_time = 0.0

    while _running:
        try:
            uid = serial_nfc_driver.read_uid()
            now = time.time()
            if uid:
                # Debounce same UID within 2.0 seconds
                if uid != last_uid or (now - last_seen_time) > 2.0:
                    last_uid = uid
                    last_seen_time = now
                    logger.info(f"NFC Worker: Tag detected: {uid}")
                    event_bus.dispatch("nfc:tag_scanned", nfc_uid=uid)
            time.sleep(0.2)
        except Exception as e:
            logger.debug(f"NFC Worker: Polling exception: {e}")
            time.sleep(1.0)


def start_nfc_worker():
    global _worker_thread, _running
    if _running:
        return
    _running = True
    _worker_thread = threading.Thread(target=_poll_loop, daemon=True, name="NfcWorkerThread")
    _worker_thread.start()
    logger.info("NFC Worker started.")


def stop_nfc_worker():
    global _running, _worker_thread
    _running = False
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=1.0)
    logger.info("NFC Worker stopped.")
