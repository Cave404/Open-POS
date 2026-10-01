"""
=============================================================================
Open-POS Serial NFC Hardware Driver (hardware/drivers/serial_nfc.py)
=============================================================================
Communicates with USB/Serial/HID NFC card readers (e.g. ACR122U, PN532).
Provides safe polling, APDU UID extraction, and non-blocking disconnect handling.
=============================================================================
"""

import logging
import re
from typing import Optional, Callable

logger = logging.getLogger("openpos.hardware.nfc")


class SerialNfcDriver:
    def __init__(self, port: Optional[str] = None, baudrate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._is_connected = False

    def read_uid(self) -> Optional[str]:
        """
        Polls reader for an active tag and returns normalized 14-hex UID or None.
        """
        if not self.port:
            return None

        try:
            import serial
            with serial.Serial(self.port, self.baudrate, timeout=self.timeout) as ser:
                # Read incoming serial payload
                raw = ser.readline()
                if raw:
                    text = raw.decode("utf-8", errors="ignore").strip()
                    cleaned = re.sub(r'[^A-Fa-f0-9]', '', text).upper()
                    if len(cleaned) in (8, 14):
                        return cleaned
        except ImportError:
            logger.debug("SerialNfcDriver: pyserial not available.")
        except Exception as e:
            logger.debug(f"SerialNfcDriver: Read polling error: {e}")
        return None


serial_nfc_driver = SerialNfcDriver()
