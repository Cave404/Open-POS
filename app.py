"""
=============================================================================
Open-POS Application Entrypoint Shim (app.py)
=============================================================================
Provides backward-compatible facade re-exporting create_app from the
restructured presentation layer (ui.app).
=============================================================================
"""

from ui.app import create_app

if __name__ == '__main__':
    from core.config import Config
    application = create_app()
    print(f"Starting Open-POS on http://127.0.0.1:{Config.PORT}")
    application.run(host=Config.HOST, port=Config.PORT, debug=True)