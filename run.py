"""
=============================================================================
Open-POS Unified Desktop Runtime Entrypoint (run.py)
=============================================================================
Orchestrates application initialization across layered subsystems:
  1. Bootstraps centralized logging and configuration.
  2. Starts the non-blocking hardware worker queue dispatcher.
  3. Initializes the Flask presentation engine and background WSGI server.
  4. Launches the PyWebView Edge Chromium desktop client window with native JS bridge.
  5. Guarantees safe teardown of peripheral dispatchers upon shutdown.
=============================================================================
"""

import sys
import os
import threading

# Ensure project root is present in search path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.logger import setup_system_logger
from core.config import Config
from core.setup import is_setup_complete
from hardware.dispatcher import hardware_dispatcher
from ui.app import create_app
import webview


class JSBridge:
    """
    Exposes safe Python-native capabilities to the embedded WebView2 browser
    context via window.pywebview.api.<method>().
    """

    def save_recovery_file(self, content: str, filename: str = 'OpenPOS_Emergency_Recovery.txt') -> dict:
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
        return Config.VERSION

    def reload_window(self) -> dict:
        try:
            win = getattr(self, '_window', None) or (webview.windows[0] if webview.windows else None)
            if win:
                current_url = win.get_current_url() or f"http://127.0.0.1:{Config.PORT}/manager/addons"
                win.load_url(current_url)
                return {"status": "success"}
            return {"status": "error", "message": "No active pywebview window available."}
        except Exception as e:
            return {"status": "error", "message": str(e)}


def main():
    logger, _ = setup_system_logger()
    logger.info("Initializing OpenPOS subsystems...")

    # Start non-blocking hardware queue
    hardware_dispatcher.start()

    # Initialize Flask presentation engine
    app = create_app()

    # Determine host URL
    server_port = Config.PORT or 5000
    entry_url = f"http://127.0.0.1:{server_port}/pos"

    # Start background WSGI server daemon thread
    def _run_server():
        try:
            from waitress import serve
            serve(app, host="127.0.0.1", port=server_port, threads=6)
        except Exception as e:
            logger.warning(f"Waitress serve failed ({e}), falling back to Werkzeug development server.")
            app.run(host="127.0.0.1", port=server_port, debug=False, use_reloader=False)

    server_thread = threading.Thread(target=_run_server, daemon=True, name="OpenPOS-BackendWorker")
    server_thread.start()

    try:
        # Check if first-run onboarding setup is required
        if not is_setup_complete():
            webview.create_window(
                title="OpenPOS - Initial Setup & Security Initialization",
                url=f"http://127.0.0.1:{server_port}/setup",
                width=1120,
                height=800,
                min_size=(960, 650),
                resizable=True,
                easy_drag=False,
                confirm_close=False,
                js_api=JSBridge()
            )
        else:
            # Start PyWebView desktop client
            webview.create_window(
                title=f"OpenPOS - Register [{Config.VERSION}]",
                url=entry_url,
                width=1280,
                height=800,
                min_size=(1024, 680),
                background_color="#0d1117",
                js_api=JSBridge()
            )
        webview.start(private_mode=False)
    finally:
        logger.info("Shutting down peripheral dispatchers...")
        hardware_dispatcher.stop()


if __name__ == "__main__":
    main()
