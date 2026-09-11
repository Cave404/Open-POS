"""
Global Pytest Configuration & Test Environment Isolation
Ensures automated tests never touch, overwrite, or mutate production/local store databases,
logo uploads, custom addons, or credentials.
"""

import os
import pytest
from core.config import Config
from core.db import init_db

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

    # Initialize clean isolated schema in the test database
    init_db()

    # Discover and run migrations for addons against the fresh test DB
    try:
        from core.addons import addon_manager
        addon_manager.discover_and_load_all()
    except Exception:
        pass

    yield
