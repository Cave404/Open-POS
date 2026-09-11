"""
=============================================================================
Open-POS Standalone First-Run Setup Launcher
=============================================================================
Launches the dedicated onboarding wizard window:
  - Validates if setup is already complete (exits cleanly or informs user).
  - Starts the local backend server on a background daemon thread.
  - Opens the 840x700 Setup Wizard desktop container on the main thread.
=============================================================================
"""

import os
import sys
import threading
import webview

from core.config import Config
from core.setup import is_setup_complete
from app import create_app

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

    # 2. Launch setup window
    window = webview.create_window(
        title="OpenPOS - Initial Setup & Security Initialization",
        url=f"http://127.0.0.1:{Config.PORT}/setup",
        width=840,
        height=700,
        min_size=(780, 600),
        resizable=True
    )

    webview.start()

if __name__ == '__main__':
    main()
