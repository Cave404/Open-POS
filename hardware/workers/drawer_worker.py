"""
=============================================================================
Open-POS Cash Drawer Worker (hardware/workers/drawer_worker.py)
=============================================================================
Non-blocking worker routine for issuing cash drawer kick triggers via ESC/POS.
Guaranteed never to block the main POS register or UI threads.
=============================================================================
"""

import logging
from hardware.drivers.escpos_driver import escpos_driver
from core.settings import get_setting

logger = logging.getLogger("openpos.hardware.drawer")


def kick_cash_drawer(pin: int = 2) -> bool:
    """
    Asynchronously executed routine to pulse the cash drawer RJ11 solenoid.
    Configured via settings: drawer_enabled, drawer_pin.
    """
    drawer_enabled = get_setting("drawer_enabled", True)
    if not drawer_enabled:
        logger.info("Drawer Worker: Cash drawer trigger disabled in settings.")
        return True

    configured_pin = int(get_setting("drawer_pin", pin))
    logger.info(f"Drawer Worker: Actuating cash drawer on pin {configured_pin}...")
    try:
        success = escpos_driver.kick_drawer(configured_pin)
        if success:
            logger.info("Drawer Worker: Drawer kick completed successfully.")
        else:
            logger.warning("Drawer Worker: Drawer kick command issued with warning/offline status.")
        return success
    except Exception as e:
        logger.error(f"Drawer Worker: Failed to kick cash drawer: {e}", exc_info=True)
        return False
