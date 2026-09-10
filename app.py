from flask import Flask, redirect, url_for
from core.config import Config
from manager.routes import manager_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Register blueprints
    app.register_blueprint(manager_bp)

    @app.route('/')
    def index():
        return redirect(url_for('manager.manager_index'))

    return app

if __name__ == '__main__':
    application = create_app()
    print(f"Starting Open-POS on http://127.0.0.1:{Config.PORT}")
    application.run(host=Config.HOST, port=Config.PORT, debug=True)