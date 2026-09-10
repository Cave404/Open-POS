import os
import sys
import threading
import webview
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
from core.config import Config
from app import create_app

flask_app = create_app()
active_window = None

def run_flask():
    """Runs backend server quietly on localhost."""
    flask_app.run(host="127.0.0.1", port=Config.PORT, debug=False, use_reloader=False)

def create_tray_icon():
    """Generates a clean 64x64 blue POS badge icon in-memory."""
    img = Image.new('RGBA', (64, 64), color=(0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Blue rounded pill
    d.rounded_rectangle([(4, 4), (60, 60)], radius=14, fill=(59, 130, 246))
    # Inner accent
    d.rectangle([(16, 20), (48, 26)], fill=(255, 255, 255))
    d.rectangle([(16, 32), (32, 38)], fill=(255, 255, 255))
    d.rectangle([(16, 44), (40, 50)], fill=(255, 255, 255))
    return img

def open_manager():
    """Opens or focuses the dedicated System Manager window."""
    global active_window
    
    def _create_win():
        global active_window
        active_window = webview.create_window(
            title=f"{Config.STORE_NAME} - System Manager",
            url=f"http://127.0.0.1:{Config.PORT}/manager",
            width=1000,
            height=680,
            min_size=(800, 550),
            resizable=True
        )
        webview.start()
        active_window = None

    # Run WebView in an independent thread if not already open
    threading.Thread(target=_create_win, daemon=True).start()

def quit_system(icon, item):
    """Graceful system shutdown."""
    icon.stop()
    os._exit(0)

if __name__ == '__main__':
    # 1. Start core backend on background daemon thread
    server_thread = threading.Thread(target=run_flask, daemon=True)
    server_thread.start()

    # 2. Build system tray menu
    menu = (
        item('Open System Manager', lambda icon, item: open_manager(), default=True),
        item('Open Register (Browser)', lambda icon, item: os.system(f'start http://127.0.0.1:{Config.PORT}/register')),
        pystray.Menu.SEPARATOR,
        item('Exit POS System', quit_system)
    )

    tray = pystray.Icon(
        name="OpenPOS",
        icon=create_tray_icon(),
        title=f"{Config.STORE_NAME} Core",
        menu=menu
    )

    # Automatically pop the Manager UI on initial boot
    open_manager()

    # 3. Enter persistent tray event loop
    tray.run()
