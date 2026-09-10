"""
=============================================================================
Open-POS Unified Desktop Runner & System Supervisor
=============================================================================
This module is the singular entry point for the Open-POS desktop application.
It orchestrates the concurrent execution of:
  1. The Flask WSGI backend server (running on a background daemon thread).
  2. The Windows System Tray icon & context menu (running detached via pystray).
  3. The Startup Splash Screen & Boot Progress Sequencer (borderless WebView2).
  4. The PyWebView Edge Chromium WebView2 window (running on the MAIN thread).

Threading Architecture & Collision Prevention:
----------------------------------------------
Native GUI event loops on Microsoft Windows require access to the primary
operating system thread to process window messages (HWND message pump).
Running `webview.start()` inside a secondary or worker thread causes thread
starvation, deadlocks, and `WebViewException: Thread collision` crashes.

To ensure 100% stable execution:
  - Main Thread: Exclusively dedicated to `webview.start(boot_worker)`.
  - Daemon Thread 1: Hosts Flask/Waitress serving REST APIs on localhost:PORT.
  - Daemon Thread 2: Hosts Pystray message pump via `tray.run_detached()`.
  - Worker Thread: Executes modular boot verification sequence in core.boot.
=============================================================================
"""

import os
import sys
import threading
import webbrowser
import webview
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

from core.config import Config
from core.boot import run_boot_sequence
from app import create_app

# -----------------------------------------------------------------------------
# Global Runtime State & Shared Handle Registry
# -----------------------------------------------------------------------------
splash_window = None          # Handle to the initial frameless splash window
active_window = None          # Handle to the primary System Manager window
tray_instance = None          # Handle to the Pystray icon runner
is_terminating = False        # Flag indicating whether a full system shutdown is underway


# -----------------------------------------------------------------------------
# 1. Background Web Server Worker
# -----------------------------------------------------------------------------
def run_backend_server():
    """
    Spins up the Flask backend application on a background daemon thread.
    The WSGI server binds quietly to 127.0.0.1 on the configured port.
    """
    app = create_app()
    # use_reloader is set to False to prevent spawning child watcher processes
    app.run(
        host="127.0.0.1",
        port=Config.PORT,
        debug=False,
        use_reloader=False
    )


# -----------------------------------------------------------------------------
# 2. In-Memory System Tray Icon Generator
# -----------------------------------------------------------------------------
def generate_tray_icon() -> Image.Image:
    """
    Generates a crisp 64x64 RGBA blue badge icon with white accent bars
    directly in-memory using Pillow, eliminating reliance on external image assets.
    """
    img = Image.new('RGBA', (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer pill frame in vibrant POS blue
    draw.rounded_rectangle([(4, 4), (60, 60)], radius=14, fill=(59, 130, 246))

    # Inner badge styling: simulated receipt / barcode register lines
    draw.rectangle([(16, 18), (48, 24)], fill=(255, 255, 255))
    draw.rectangle([(16, 30), (36, 36)], fill=(255, 255, 255))
    draw.rectangle([(16, 42), (44, 48)], fill=(255, 255, 255))

    return img


# -----------------------------------------------------------------------------
# 3. Window Event Interception & Safe Navigation
# -----------------------------------------------------------------------------
def on_window_closing():
    """
    Event listener triggered when the user clicks the 'X' (close) window control.
    Instead of terminating the Flask server and destroying the desktop container,
    we hide the window to the system tray and return False to cancel destruction.
    """
    global is_terminating, active_window
    if is_terminating:
        # Full application shutdown initiated; allow destruction to proceed
        return True

    if active_window is not None:
        active_window.hide()

    # Returning False instructs pywebview to cancel window destruction
    return False


def show_system_manager(icon=None, menu_item=None):
    """
    Restores and focuses the hidden System Manager container window
    when triggered via system tray double-click or context menu item.
    """
    global active_window
    if active_window is not None:
        active_window.show()
        active_window.restore()


def open_register_browser(icon=None, menu_item=None):
    """
    Opens the default system web browser directed at the POS register endpoint.
    """
    register_url = f"http://127.0.0.1:{Config.PORT}/register"
    webbrowser.open(register_url)


def exit_open_pos(icon=None, menu_item=None):
    """
    Executes a clean, graceful shutdown of the Open-POS desktop application:
      1. Marks the termination flag to stop closing interception.
      2. Stops the system tray icon loop.
      3. Destroys all open WebView container windows.
      4. Terminates the Python process.
    """
    global is_terminating, tray_instance, active_window, splash_window
    is_terminating = True

    if tray_instance is not None:
        try:
            tray_instance.stop()
        except Exception:
            pass

    if active_window is not None:
        try:
            active_window.destroy()
        except Exception:
            pass

    if splash_window is not None:
        try:
            splash_window.destroy()
        except Exception:
            pass

    os._exit(0)


# -----------------------------------------------------------------------------
# 4. System Tray Construction
# -----------------------------------------------------------------------------
def initialize_system_tray() -> pystray.Icon:
    """
    Constructs the Pystray system tray icon with primary actions and exit hook.
    """
    menu_items = (
        item('Open System Manager', show_system_manager, default=True),
        item('Open Register (Browser)', open_register_browser),
        pystray.Menu.SEPARATOR,
        item('Exit Open-POS', exit_open_pos)
    )

    tray = pystray.Icon(
        name="OpenPOS",
        icon=generate_tray_icon(),
        title=f"{Config.STORE_NAME} Core",
        menu=menu_items
    )
    return tray


# -----------------------------------------------------------------------------
# 5. Boot Sequencer Worker & Window Transition
# -----------------------------------------------------------------------------
def boot_orchestration_worker():
    """
    Executes inside a background thread once pywebview's GUI message loop is active.
    Coordinates the 5-phase boot sequence, streaming progress events into the
    splash screen, and smoothly transitions into the primary System Manager window.
    """
    global splash_window, active_window

    def update_splash_ui(percent: int, message: str):
        """Dispatches progress updates into the splash DOM via evaluate_js."""
        if splash_window is not None:
            safe_msg = message.replace("\\", "\\\\").replace("'", "\\'")
            js_code = f"if (window.updateProgress) window.updateProgress({percent}, '{safe_msg}');"
            try:
                splash_window.evaluate_js(js_code)
            except Exception as js_err:
                pass

    # Execute modular boot sequence (Phases 1 through 5)
    run_boot_sequence(progress_callback=update_splash_ui, buffer_seconds=1.5)

    # Instantiate the primary System Manager window
    active_window = webview.create_window(
        title=f"{Config.STORE_NAME} - System Manager",
        url=f"http://127.0.0.1:{Config.PORT}/manager",
        width=1040,
        height=720,
        min_size=(820, 560),
        resizable=True,
        confirm_close=False
    )

    # Register close button minimization hook
    active_window.events.closing += on_window_closing

    # Destroy the temporary splash window
    if splash_window is not None:
        try:
            splash_window.destroy()
            splash_window = None
        except Exception:
            pass


# -----------------------------------------------------------------------------
# 6. Main Execution Entry Point
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    # Step A: Launch Flask backend on background daemon thread
    server_thread = threading.Thread(
        target=run_backend_server,
        name="OpenPOS-BackendWorker",
        daemon=True
    )
    server_thread.start()

    # Step B: Launch Pystray in detached (non-blocking) thread mode
    tray_instance = initialize_system_tray()
    tray_instance.run_detached()

    # Step C: Instantiate the borderless splash window matching image aspect ratio (656x404)
    splash_window = webview.create_window(
        title="Open-POS Starting",
        url=f"http://127.0.0.1:{Config.PORT}/manager/splash",
        width=656,
        height=404,
        frameless=True,
        easy_drag=True,
        resizable=False,
        shadow=True,
        on_top=True
    )

    # Step D: Start WebView event loop on MAIN thread with boot worker callback
    webview.start(boot_orchestration_worker)

    # Step E: Clean exit cleanup once main loop terminates
    exit_open_pos()
