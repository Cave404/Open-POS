"""
=============================================================================
Open-POS ESC/POS Hardware Driver (hardware/drivers/escpos_driver.py)
=============================================================================
Provides standard ESC/POS protocol command sequences for thermal receipt
printers and RJ11 cash drawer kick pulses.
Handles connection failures, timeouts, and offline states gracefully.
=============================================================================
"""

import logging
from typing import Optional

logger = logging.getLogger("openpos.hardware.escpos")

# Standard ESC/POS Command Byte Sequences
ESC = b'\x1b'
GS = b'\x1d'
FS = b'\x1c'

CMD_INIT = ESC + b'@'
CMD_DRAWER_KICK_PIN2 = ESC + b'p\x00\x19\xfa'  # ESC p m t1 t2 (Pin 2, 50ms on, 500ms off)
CMD_DRAWER_KICK_PIN5 = ESC + b'p\x01\x19\xfa'  # ESC p m t1 t2 (Pin 5)
CMD_CUT_FULL = GS + b'V\x00'
CMD_CUT_PARTIAL = GS + b'V\x01'
CMD_LINE_FEED = b'\n'


class EscPosDriver:
    def __init__(self, port: Optional[str] = None, baudrate: int = 9600, timeout: float = 2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

    def kick_drawer(self, pin: int = 2) -> bool:
        """
        Sends standard ESC/POS pulse command to open RJ11-connected cash drawer.
        """
        cmd = CMD_DRAWER_KICK_PIN2 if pin == 2 else CMD_DRAWER_KICK_PIN5
        logger.info(f"ESC/POS: Sending drawer kick pulse on Pin {pin}...")
        return self._send_raw(cmd)

    def print_raw(self, data: bytes) -> bool:
        """
        Sends raw bytes to the configured thermal printer.
        """
        return self._send_raw(CMD_INIT + data + CMD_CUT_PARTIAL)

    def _send_raw(self, payload: bytes) -> bool:
        """
        Transmits raw command buffer to peripheral with timeout protection.
        """
        if not self.port:
            logger.debug(f"ESC/POS: Simulation mode (no port configured). Payload size: {len(payload)} bytes.")
            return True

        try:
            import serial
            with serial.Serial(self.port, self.baudrate, timeout=self.timeout) as ser:
                ser.write(payload)
                ser.flush()
            logger.info(f"ESC/POS: Successfully sent {len(payload)} bytes to {self.port}.")
            return True
        except ImportError:
            logger.warning("ESC/POS: pyserial not installed. Skipping physical transmission.")
            return False
        except Exception as e:
            logger.error(f"ESC/POS: Communication failure on {self.port}: {e}")
            return False


escpos_driver = EscPosDriver()
