"""
core/tray.py
============
Native Windows System Tray Icon controller for Open-POS.
Provides desktop background persistence, quick navigation to Register and
Manager views, active port monitoring, and graceful process shutdown.
"""

import os
import threading
import logging
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

logger = logging.getLogger("openpos.tray")


class SystemTrayManager:
    """
    Manages the Windows notification area system tray icon and context menu.
    """

    def __init__(self, app_window, port: int, on_exit_callback=None):
        self.window = app_window
        self.port = port
        self.on_exit_callback = on_exit_callback
        self.icon = None

    def _create_fallback_icon(self):
        """Generates a high-contrast icon if favicon.ico is not bundled."""
        img = Image.new("RGBA", (64, 64), color=(13, 17, 23, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([12, 12, 52, 52], outline="#58a6ff", width=4)
        draw.text((22, 18), "P", fill="#58a6ff")
        return img

    def _load_icon(self):
        from core.config import Config
        icon_path = os.path.join(Config.BUNDLE_DIR, "ui", "static", "img", "favicon.ico")
        if os.path.exists(icon_path):
            try:
                return Image.open(icon_path)
            except Exception:
                pass
        return self._create_fallback_icon()

    def show_window(self, target_path="/pos"):
        if self.window:
            try:
                self.window.load_url(f"http://127.0.0.1:{self.port}{target_path}")
                self.window.show()
                self.window.restore()
            except Exception as err:
                logger.error(f"Failed to focus window: {err}")

    def exit_app(self):
        logger.info("Exit requested from System Tray.")
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self.on_exit_callback:
            try:
                self.on_exit_callback()
            except Exception:
                pass
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
        os._exit(0)

    def start(self):
        from core.config import Config
        try:
            menu = pystray.Menu(
                item("Open Register", lambda: self.show_window("/pos"), default=True),
                item("System Manager", lambda: self.show_window("/manager")),
                item("Addon Manager", lambda: self.show_window("/manager/addons")),
                pystray.Menu.SEPARATOR,
                item(f"Port: {self.port}", lambda: None, enabled=False),
                pystray.Menu.SEPARATOR,
                item("Exit OpenPOS", lambda: self.exit_app())
            )

            self.icon = pystray.Icon("OpenPOS", self._load_icon(), f"OpenPOS [v{Config.VERSION}]", menu)
            tray_thread = threading.Thread(target=self.icon.run, daemon=True, name="SystemTrayThread")
            tray_thread.start()
            logger.info("System Tray service started.")
        except Exception as e:
            logger.warning(f"Could not start system tray service: {e}")
