from flask import Flask, redirect, url_for, render_template, send_from_directory
from core.config import Config
from core.db import init_db
from core.settings import seed_default_settings
from manager.routes import manager_bp, api_bp
from core.routes.customer_routes import core_customers_bp
from core.routes.pos_routes import pos_bp, run_pos_migrations
from core.addons.ui_hooks import render_addon_hook, has_addon_canvas

def create_app():
    app = Flask(__name__, template_folder='templates')
    app.config.from_object(Config)

    # Initialize database schema and default settings
    init_db()
    seed_default_settings()

    # Run Database Migrations (idempotent)
    from core.services.customer_service import run_customer_migrations
    run_customer_migrations()
    run_pos_migrations()

    # Register blueprints
    app.register_blueprint(manager_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(core_customers_bp)
    app.register_blueprint(pos_bp)

    # Expose Addon UI Hooks to Jinja2 templates
    app.jinja_env.globals['render_addon_hook'] = render_addon_hook
    app.jinja_env.globals['has_addon_canvas'] = has_addon_canvas

    # Initialize dynamic Addon & Plugin Engine
    from core.addons import addon_manager
    addon_manager.init_app(app)

    # Start background update checker (30-second boot delay, then hourly)
    try:
        from core.updater.checker import start_background_checker
        start_background_checker(app)
    except Exception:
        pass  # Never block startup on updater failure

    @app.route('/')
    def index():
        return redirect('/pos')

    @app.route('/setup')
    def setup_root():
        from manager.routes import manager_setup
        return manager_setup()

    @app.route('/customers')
    def customers_directory():
        return render_template('customers/index.html')

    @app.route('/data/uploads/<path:filename>')
    def serve_data_uploads(filename):
        return send_from_directory(Config.UPLOAD_DIR, filename)

    # Configure persistent session cookies
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Global Error Handlers - Centralized Logging & Resilient Feedback
    from flask import request, jsonify
    from core.logger import logger, install_global_excepthooks

    install_global_excepthooks()

    @app.errorhandler(404)
    def handle_404(err):
        if request.path.startswith('/api/') or request.path.startswith('/manager/api/') or request.is_json:
            return jsonify({
                "error": "Not Found",
                "detail": "The requested API endpoint does not exist.",
                "path": getattr(request, 'path', '')
            }), 404
        return render_template('error.html',
            error_code=404,
            error_title="Page or Endpoint Not Found",
            error_message="The requested system route is not registered or has been moved.",
            request_path=getattr(request, 'path', '')
        ), 404

    @app.errorhandler(500)
    def handle_500(err):
        logger.error(f"Internal Server Error on {getattr(request, 'path', '')}: {err}", exc_info=True)
        if request.path.startswith('/api/') or request.path.startswith('/manager/api/') or request.is_json:
            return jsonify({
                "error": "Internal Server Error",
                "detail": str(err),
                "path": getattr(request, 'path', '')
            }), 500
        return render_template('error.html',
            error_code=500,
            error_title="Internal Server Failure",
            error_message="An unexpected error occurred while processing your request.",
            request_path=getattr(request, 'path', '')
        ), 500

    @app.errorhandler(Exception)
    def handle_unhandled_exception(e):
        logger.error(f"Unhandled HTTP Exception on {getattr(request, 'path', '')}: {e}", exc_info=True)
        if request.path.startswith('/api/') or request.path.startswith('/manager/api/') or request.is_json:
            return jsonify({
                "error": "Internal Server Error",
                "detail": str(e),
                "path": getattr(request, 'path', '')
            }), 500
        return render_template('error.html',
            error_code=500,
            error_title="Internal Server Failure",
            error_message="An unexpected error occurred while processing your request.",
            request_path=getattr(request, 'path', '')
        ), 500

    return app

if __name__ == '__main__':
    application = create_app()
    print(f"Starting Open-POS on http://127.0.0.1:{Config.PORT}")
    application.run(host=Config.HOST, port=Config.PORT, debug=True)