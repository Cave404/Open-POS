import threading
import sys
import webview
from core.config import Config
from app import create_app

def start_server(app):
    # Multi-threaded WSGI server or Flask development server
    app.run(host="127.0.0.1", port=Config.PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    app = create_app()

    # Run backend server in a background thread
    server_thread = threading.Thread(target=start_server, args=(app,), daemon=True)
    server_thread.start()

    # Launch dedicated Edge WebView2 container window
    window = webview.create_window(
        title=f"{Config.STORE_NAME} - System Manager",
        url=f"http://127.0.0.1:{Config.PORT}/manager",
        width=760,
        height=600,
        resizable=True,
        confirm_close=False,
        easy_drag=True
    )

    webview.start()
    sys.exit()