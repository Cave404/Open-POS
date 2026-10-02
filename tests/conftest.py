"""
Global Pytest Configuration & Test Environment Isolation
Ensures automated tests never touch, overwrite, or mutate production/local store databases,
logo uploads, custom addons, or credentials.
"""

import os
import sys
import types
import pytest
from core.config import Config
from storage.database import init_db

# Legacy module shims for decoupled 5-layer architecture
import ui.app
import ui.routes.manager_routes
import run

sys.modules['app'] = ui.app
if 'manager' not in sys.modules:
    sys.modules['manager'] = types.ModuleType('manager')
sys.modules['manager.routes'] = ui.routes.manager_routes
sys.modules['manager'].routes = ui.routes.manager_routes

if 'setup_wizard' not in sys.modules:
    _sw = types.ModuleType('setup_wizard')
    _sw.SetupWizardBridge = getattr(run, 'JSBridge', None)
    sys.modules['setup_wizard'] = _sw


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch, tmp_path):
    """
    Globally isolates database and private storage directories for every test.
    Protects data/db/pos_store.db and user configurations from test mutation.
    """
    test_db_file = str(tmp_path / "test_isolated.db")
    test_upload_dir = str(tmp_path / "uploads")
    test_custom_addons = str(tmp_path / "custom_addons")
    test_logs_dir = str(tmp_path / "logs")

    os.makedirs(test_upload_dir, exist_ok=True)
    os.makedirs(test_custom_addons, exist_ok=True)
    os.makedirs(test_logs_dir, exist_ok=True)

    import shutil
    real_addons_dir = os.path.join(Config.BASE_DIR, 'data', 'custom_addons')
    if os.path.isdir(real_addons_dir):
        for item in os.listdir(real_addons_dir):
            if item != "test_addon":
                s = os.path.join(real_addons_dir, item)
                d = os.path.join(test_custom_addons, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)

    # Monkeypatch Config paths to point exclusively to the isolated tmp_path
    monkeypatch.setattr(Config, "DB_ENGINE", "sqlite")
    monkeypatch.setattr(Config, "DB_NAME", test_db_file)
    monkeypatch.setattr(Config, "DB_PATH", test_db_file)
    monkeypatch.setattr(Config, "UPLOAD_DIR", test_upload_dir)
    monkeypatch.setattr(Config, "CUSTOM_ADDONS_DIR", test_custom_addons)
    monkeypatch.setattr(Config, "LOGS_DIR", test_logs_dir)

    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("DB_NAME", test_db_file)

    try:
        import manager.routes
        monkeypatch.setattr(manager.routes, "UPLOAD_FOLDER", test_upload_dir)
    except Exception:
        pass

    # Ensure tests by default do not inherit a persistent locked state from a provisioned dev environment
    import json
    test_auth_file = str(tmp_path / "default_unlocked_auth.json")
    with open(test_auth_file, "w", encoding="utf-8") as f:
        json.dump({
            "require_password": False,
            "password_hash": "",
            "salt": "",
            "protected_sections": ["branding", "database", "admin"],
            "bypass_manager_on_boot": False
        }, f)
    try:
        monkeypatch.setattr("manager.routes.AUTH_CONFIG_PATH", test_auth_file)
    except Exception:
        pass
    try:
        monkeypatch.setattr("core.setup.wizard.AUTH_CONFIG_PATH", test_auth_file)
    except Exception:
        pass
    try:
        monkeypatch.setattr("core.services.security_service.AUTH_CONFIG_PATH", test_auth_file)
    except Exception:
        pass

    # Initialize clean isolated schema in the test database
    init_db()

    # Discover and run migrations for addons against the fresh test DB
    try:
        from core.addons import addon_manager
        addon_manager.discover_and_load_all()
    except Exception:
        pass

    yield
