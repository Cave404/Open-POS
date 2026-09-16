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
import socket
import threading
import webbrowser
import webview
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item

from core.config import Config, REQUIRED_DATA_DIRS
from core.boot import run_boot_sequence
from core.setup import is_setup_complete
from app import create_app


# -----------------------------------------------------------------------------
# Global Runtime State & Shared Handle Registry
# -----------------------------------------------------------------------------
splash_window = None          # Handle to the initial frameless splash window
active_window = None          # Handle to the primary System Manager window
tray_instance = None          # Handle to the Pystray icon runner
is_terminating = False        # Flag indicating whether a full system shutdown is underway


# -----------------------------------------------------------------------------
# JS Bridge: Python capabilities exposed to the WebView2 JS context
# -----------------------------------------------------------------------------
class JSBridge:
    """
    Exposes safe Python-native capabilities to the embedded WebView2 browser
    context via window.pywebview.api.<method>(). pywebview injects _window
    automatically so we can reference the calling window for dialog dispatch.

    Threading note: pywebview runs bridge methods on a background worker thread
    but internally dispatches Win32 dialog calls to the main OS thread, so
    create_file_dialog() is safe to call here without additional synchronization.
    """

    def save_recovery_file(self, content: str, filename: str = 'OpenPOS_Emergency_Recovery.txt') -> dict:
        """
        Opens a native Windows Save-As dialog pre-filled with the given filename,
        then writes the provided text content to the chosen path.

        Returns:
            { 'status': 'success', 'path': '/chosen/path' }
            { 'status': 'cancelled' }  -- if the user dismissed the dialog
        """
        try:
            win = getattr(self, '_window', None) or (webview.windows[0] if webview.windows else None)
            if not win:
                return {'status': 'error', 'message': 'No active pywebview window available.'}
            result = win.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=('Text Files (*.txt)', 'All Files (*.*)')
            )
            if result and len(result) > 0:
                target_path = result[0]
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return {'status': 'success', 'path': target_path}
            return {'status': 'cancelled'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def save_recovery_file_dialog(self, store_name, token, fernet_key):
        """
        Opens a native Windows Save-As dialog pre-filled with the store recovery key filename,
        then writes the recovery token and Fernet key to plain text.
        """
        try:
            from datetime import datetime
            win = getattr(self, '_window', None) or (webview.windows[0] if webview.windows else None)
            if not win:
                return {'status': 'error', 'message': 'No active pywebview window available.'}

            safe_name = str(store_name or 'OpenPOS_Store').replace(' ', '_')
            file_path = win.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=os.path.expanduser("~/Desktop"),
                save_filename=f"{safe_name}_Recovery_Key.txt"
            )
            if file_path:
                target = file_path[0] if isinstance(file_path, (list, tuple)) else file_path
                with open(target, 'w', encoding='utf-8') as f:
                    f.write("=== OPENPOS EMERGENCY SYSTEM RECOVERY KEY ===\n")
                    f.write(f"Store: {store_name}\n")
                    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(f"RECOVERY TOKEN: {token}\n")
                    f.write(f"FERNET KEY:     {fernet_key}\n\n")
                    f.write("Keep this file in a secure offline location (e.g. encrypted USB drive).\n")
                return {"status": "success", "path": target}
            return {"status": "cancelled"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def cancel_reauth(self) -> dict:
        """
        Cancels setup re-configuration, re-generates data/config/.setup_complete,
        closes wizard window, spawns Start_POS.bat detached, and exits.
        """
        try:
            import subprocess
            from core.setup import mark_setup_complete
            mark_setup_complete({"store_name": "Store", "restored": True})
            win = getattr(self, '_window', None) or (webview.windows[0] if webview.windows else None)
            if win:
                try:
                    win.destroy()
                except Exception:
                    pass

            bat_path = os.path.join(Config.BASE_DIR, "Start_POS.bat")
            if os.path.isfile(bat_path):
                subprocess.Popen(
                    ["cmd.exe", "/c", "Start_POS.bat"],
                    cwd=Config.BASE_DIR,
                    creationflags=subprocess.DETACHED_PROCESS
                )

            def _exit_later():
                import time
                time.sleep(0.5)
                os._exit(0)

            threading.Thread(target=_exit_later, daemon=True).start()
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def finish_and_launch(self, store_name: str = None) -> dict:
        """
        Writes data/config/.setup_complete, closes setup window, spawns Start_POS.bat detached, and exits.
        """
        try:
            import subprocess
            from core.setup import mark_setup_complete
            mark_setup_complete({"store_name": store_name or "Store", "completed_by": "setup_wizard"})
            win = getattr(self, '_window', None) or (webview.windows[0] if webview.windows else None)
            if win:
                try:
                    win.destroy()
                except Exception:
                    pass

            bat_path = os.path.join(Config.BASE_DIR, "Start_POS.bat")
            if os.path.isfile(bat_path):
                subprocess.Popen(
                    ["cmd.exe", "/c", "Start_POS.bat"],
                    cwd=Config.BASE_DIR,
                    creationflags=subprocess.DETACHED_PROCESS
                )

            def _exit_later():
                import time
                time.sleep(0.5)
                os._exit(0)

            threading.Thread(target=_exit_later, daemon=True).start()
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_version(self) -> str:
        """Returns the current Open-POS version string (used by JS diagnostics)."""
        return Config.VERSION


# -----------------------------------------------------------------------------
# 1. Background Web Server Worker & Dynamic Port Fallback
# -----------------------------------------------------------------------------
def find_available_port(start_port: int = 5000, max_attempts: int = 10) -> int:
    """
    Attempts to bind to 127.0.0.1:port.
    If OSError (e.g. WinError 10048), increments port (e.g. 5001, 5002...) and logs:
    [WARN] Port 5000 is occupied by another service. Shifting OpenPOS to port {port}.
    """
    for attempt in range(max_attempts):
        port = start_port + attempt
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(('127.0.0.1', port))
            sock.close()
            if attempt > 0:
                print(f"[WARN] Port {start_port} is occupied by another service. Shifting OpenPOS to port {port}.")
            return port
        except OSError:
            sock.close()
            continue
    raise RuntimeError(f"Could not find an available port in range {start_port}-{start_port + max_attempts - 1}")


def run_backend_server(port: int = None):
    """
    Spins up the backend WSGI server on a background daemon thread.
    Uses Waitress production WSGI server, falling back to Flask dev server if needed.
    """
    target_port = port or Config.PORT
    app = create_app()
    try:
        from waitress import serve
        serve(app, host="127.0.0.1", port=target_port, threads=6)
    except Exception as e:
        print(f"[WARN] Waitress serve failed ({e}), falling back to Werkzeug development server.")
        app.run(
            host="127.0.0.1",
            port=target_port,
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
        confirm_close=False,
        js_api=JSBridge()   # Expose native save/dialog bridge to manager JS context
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
    # Step 0: Ensure required data directories exist
    for folder in REQUIRED_DATA_DIRS:
        os.makedirs(os.path.join(Config.BASE_DIR, folder), exist_ok=True)

    # Step 1: Detect available port to prevent collisions
    resolved_port = find_available_port(start_port=Config.PORT, max_attempts=10)
    Config.PORT = resolved_port

    # Step A: Launch Flask backend on background daemon thread
    server_thread = threading.Thread(
        target=run_backend_server,
        args=(resolved_port,),
        name="OpenPOS-BackendWorker",
        daemon=True
    )
    server_thread.start()

    # Step B: Check if first-run onboarding setup is required
    if not is_setup_complete():
        # Bypass normal dashboard and splash screen; launch Setup Wizard
        active_window = webview.create_window(
            title="OpenPOS - Initial Setup & Security Initialization",
            url=f"http://127.0.0.1:{resolved_port}/setup",
            width=1080,
            height=800,
            min_size=(960, 650),
            resizable=True,
            easy_drag=False,
            confirm_close=False,
            js_api=JSBridge()   # Expose native save dialog to wizard JS context
        )
        active_window.events.closing += on_window_closing
        webview.start()
        exit_open_pos()

    # Step C: Launch Pystray in detached (non-blocking) thread mode
    tray_instance = initialize_system_tray()
    tray_instance.run_detached()

    # Step D: Measure exact splash image dimensions and instantiate borderless window with docked tray
    splash_path = os.path.join(Config.BASE_DIR, 'manager', 'open_pos_splash.png')
    img_w, img_h = 656, 404
    if os.path.isfile(splash_path):
        try:
            with Image.open(splash_path) as img:
                img_w, img_h = img.size
        except Exception:
            pass

    TRAY_HEIGHT = 54
    splash_window = webview.create_window(
        title="Open-POS Starting",
        url=f"http://127.0.0.1:{resolved_port}/manager/splash",
        width=img_w,
        height=img_h + TRAY_HEIGHT,
        frameless=True,
        easy_drag=True,
        resizable=False,
        shadow=True,
        on_top=True
    )

    # Step E: Start WebView event loop on MAIN thread with boot worker callback
    webview.start(boot_orchestration_worker)

    # Step F: Clean exit cleanup once main loop terminates
    exit_open_pos()

