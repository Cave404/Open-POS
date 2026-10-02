"""
=============================================================================
Open-POS UI Presentation Engine & Application Factory (ui/app.py)
=============================================================================
Initializes Flask presentation layer, registers core & management blueprints,
configures Jinja template/static paths, sets up exception handlers,
and boots background services.
=============================================================================
"""

import os
from flask import Flask, redirect, url_for, render_template, send_from_directory, request, jsonify
from jinja2 import ChoiceLoader, FileSystemLoader

from core.config import Config
from storage.database import init_db
from core.settings import seed_default_settings
from storage.migrations import run_all_migrations

from ui.routes.manager_routes import manager_bp, api_bp
from core.routes.customer_routes import core_customers_bp
from ui.routes.pos_routes import pos_bp
from ui.routes.system_routes import system_bp
from core.addons.ui_hooks import render_addon_hook, has_addon_canvas
from core.logger import setup_system_logger, logger, install_global_excepthooks


def create_app():
    Config.init_directories()
    logger, _ = setup_system_logger()

    templates_path = os.path.join(Config.BUNDLE_DIR, "ui", "templates")
    static_path = os.path.join(Config.BUNDLE_DIR, "ui", "static")

    logger.info(f"Initializing Flask with templates: {templates_path}")
    logger.info(f"Initializing Flask with static assets: {static_path}")

    app = Flask(
        __name__,
        template_folder=templates_path,
        static_folder=static_path,
        static_url_path="/static"
    )
    app.config.from_object(Config)

    # Multi-path template loader to support ui/templates, templates, and manager/templates
    app.jinja_loader = ChoiceLoader([
        FileSystemLoader(templates_path),
        FileSystemLoader(os.path.join(Config.BUNDLE_DIR, 'ui', 'templates', 'manager')),
        FileSystemLoader(os.path.join(Config.BUNDLE_DIR, 'templates')),
    ])

    # Initialize database schema and default settings
    init_db()
    seed_default_settings()

    # Run Database Migrations (idempotent)
    run_all_migrations()

    # Register blueprints
    app.register_blueprint(manager_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(core_customers_bp)
    app.register_blueprint(pos_bp)
    app.register_blueprint(system_bp)

    # Expose Addon UI Hooks to Jinja2 templates
    app.jinja_env.globals['render_addon_hook'] = render_addon_hook
    app.jinja_env.globals['has_addon_canvas'] = has_addon_canvas

    # Initialize dynamic Addon & Plugin Engine
    from core.addons import addon_manager
    addon_manager.init_app(app)

    # Start background update checker and maintenance scheduler
    try:
        from core.updater.checker import start_background_checker
        from core.updater.scheduler import start_update_scheduler_daemon
        start_background_checker(app)
        start_update_scheduler_daemon(app)
    except Exception:
        pass  # Never block startup on updater failure

    @app.route('/')
    def index():
        sentinel_path = os.path.join(Config.DATA_DIR, "config", ".setup_complete")
        if not os.path.exists(sentinel_path) and not app.config.get("TESTING"):
            return redirect('/setup')
        return redirect('/pos')

    @app.route('/setup')
    def setup_root():
        from core.setup import is_setup_complete
        if is_setup_complete():
            from ui.routes.manager_routes import manager_setup
            return manager_setup()
        from ui.routes.pos_routes import setup_activation
        return setup_activation()

    @app.route('/setup/wizard')
    def setup_wizard_root():
        from ui.routes.manager_routes import manager_setup_wizard
        return manager_setup_wizard()

    @app.route('/auth/verify-pin', methods=['POST'])
    def auth_verify_pin_root():
        from ui.routes.manager_routes import verify_pin
        return verify_pin()

    @app.route('/customers')
    def customers_directory():
        return render_template('customers/index.html')

    @app.route('/data/uploads/<path:filename>')
    @app.route('/uploads/<path:filename>')
    def serve_data_uploads(filename):
        return send_from_directory(Config.UPLOAD_DIR, filename)

    # Configure persistent session cookies
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Global Error Handlers - Centralized Logging & Resilient Feedback
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
