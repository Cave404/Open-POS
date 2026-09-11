"""
=============================================================================
Open-POS Standalone First-Run Setup Launcher
=============================================================================
Launches the dedicated onboarding wizard window:
  - Validates if setup is already complete (exits cleanly or informs user).
  - Starts the local backend server on a background daemon thread.
  - Exposes native Save Dialog and restart capabilities via SetupWizardBridge.
  - Opens the 840x700 Setup Wizard desktop container on the main thread.
=============================================================================
"""

import os
import sys
import threading
import subprocess
from datetime import datetime
import webview

from core.config import Config
from core.setup import is_setup_complete, mark_setup_complete
from app import create_app


class SetupWizardBridge:
    """
    Exposes Python-native capabilities to the Setup Wizard WebView2 JS context
    via window.pywebview.api.<method>().
    """
    def __init__(self, window=None):
        self.window = window

    def save_recovery_file_dialog(self, store_name, token, fernet_key):
        """
        Opens a native Windows Save-As dialog targeting the user's Desktop,
        then writes the emergency recovery token sheet to plain text.
        """
        win = self.window or getattr(self, '_window', None) or (webview.windows[0] if webview.windows else None)
        if not win:
            return {"status": "error", "message": "No active pywebview window available."}

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

    # Keep compatibility with string-based content save
    def save_recovery_file(self, content: str, filename: str = 'OpenPOS_Emergency_Recovery.txt') -> dict:
        win = self.window or getattr(self, '_window', None) or (webview.windows[0] if webview.windows else None)
        if not win:
            return {'status': 'error', 'message': 'No active pywebview window available.'}
        file_path = win.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=os.path.expanduser("~/Desktop"),
            save_filename=filename,
            file_types=('Text Files (*.txt)', 'All Files (*.*)')
        )
        if file_path:
            target = file_path[0] if isinstance(file_path, (list, tuple)) else file_path
            with open(target, 'w', encoding='utf-8') as f:
                f.write(content)
            return {'status': 'success', 'path': target}
        return {'status': 'cancelled'}

    def finish_and_launch(self, store_name: str = None) -> dict:
        """
        Writes data/config/.setup_complete, closes the wizard window,
        spawns Start_POS.bat in a detached process, and terminates setup.
        """
        try:
            mark_setup_complete({"store_name": store_name or "Store", "completed_by": "setup_wizard"})
            win = self.window or getattr(self, '_window', None) or (webview.windows[0] if webview.windows else None)
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


def run_backend():
    """Starts local WSGI server for setup wizard API endpoints."""
    app = create_app()
    app.run(
        host="127.0.0.1",
        port=Config.PORT,
        debug=False,
        use_reloader=False
    )


def main():
    print(f"[*] OpenPOS First-Run Setup Wizard ({Config.VERSION})")
    if is_setup_complete():
        print("[!] Setup has already been completed and locked.")
        print("[!] To re-run setup, delete data/config/.setup_complete.")
        sys.exit(0)

    # 1. Start backend server
    server_thread = threading.Thread(
        target=run_backend,
        name="OpenPOS-SetupBackend",
        daemon=True
    )
    server_thread.start()

    # 2. Instantiate JS bridge & launch setup window
    bridge = SetupWizardBridge()
    window = webview.create_window(
        title="OpenPOS - Initial Setup & Security Initialization",
        url=f"http://127.0.0.1:{Config.PORT}/setup",
        width=840,
        height=700,
        min_size=(780, 600),
        resizable=True,
        js_api=bridge
    )
    bridge.window = window

    webview.start()


if __name__ == '__main__':
    main()
