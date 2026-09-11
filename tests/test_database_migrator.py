"""
=============================================================================
Tests: Bidirectional Database Migration Engine & v1.0.4 Features
=============================================================================
Verifies:
  1. Database status reporting (active engine, tables count, disk size).
  2. Connection validation routines (SQLite & PostgreSQL).
  3. Type translation mappings (Citext, JSONB, BIGINT identity).
  4. Dry-run migration validation and parity reporting.
  5. Atomic update of data/config/.env engine settings.
  6. Database API endpoints (/api/database/status, /test_connection, /dry_run, /switch_engine).
  7. JSBridge desktop file-dialog integration for emergency recovery export.
  8. Lockout guard markup and Return to Home navigation.
=============================================================================
"""

import os
import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from core.config import Config
from core.db_migrator import (
    _map_sqlite_type_to_pg,
    get_database_status,
    test_sqlite_connection as fn_test_sqlite_connection,
    test_postgres_connection as fn_test_postgres_connection,
    dry_run_migration,
    update_env_engine,
)
from run import JSBridge
from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_type_translation_citext_and_jsonb():
    """Asserts that column names and affinity hints map correctly to PostgreSQL types."""
    assert _map_sqlite_type_to_pg("TEXT", "email") == "CITEXT"
    assert _map_sqlite_type_to_pg("TEXT", "username") == "CITEXT"
    assert _map_sqlite_type_to_pg("TEXT", "customer_email") == "CITEXT"
    assert _map_sqlite_type_to_pg("TEXT", "config_json") == "JSONB"
    assert _map_sqlite_type_to_pg("TEXT", "card_metadata") == "JSONB"
    assert _map_sqlite_type_to_pg("TEXT", "system_payload") == "JSONB"
    assert _map_sqlite_type_to_pg("INTEGER", "id") == "BIGINT"
    assert _map_sqlite_type_to_pg("REAL", "price") == "DOUBLE PRECISION"
    assert _map_sqlite_type_to_pg("BOOLEAN", "is_active") == "BOOLEAN"


def test_sqlite_connection_valid_and_invalid(tmp_path):
    """Asserts test_sqlite_connection correctly identifies valid and corrupt/missing DBs."""
    valid_db = str(tmp_path / "valid.db")
    conn = sqlite3.connect(valid_db)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    conn.close()

    res_valid = fn_test_sqlite_connection(valid_db)
    assert res_valid["ok"] is True
    assert "SQLite OK" in res_valid["message"]
    assert res_valid["latency_ms"] >= 0

    res_invalid = fn_test_sqlite_connection(str(tmp_path / "non_existent_folder" / "bad.db"))
    assert res_invalid["ok"] is False


def test_postgres_connection_mocked():
    """Asserts test_postgres_connection handles connection responses correctly."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {"version": "PostgreSQL 14.5"}
    mock_conn.execute.return_value = mock_cur

    with patch("core.db_migrator._pg_connection") as mock_pg:
        mock_pg.return_value.__enter__.return_value = mock_conn
        res = fn_test_postgres_connection(host="127.0.0.1", port=5432)
        assert res["ok"] is True
        assert "successful" in res["message"]
        assert "14.5" in res["server_version"]


def test_get_database_status_sqlite():
    """Asserts that get_database_status returns engine, tables count, and details."""
    status = get_database_status()
    assert "engine" in status
    assert "table_count" in status
    assert status["table_count"] >= 0
    if status["engine"] == "sqlite":
        assert "file_size_mb" in status


def test_dry_run_migration_sqlite_to_postgres(tmp_path):
    """Asserts dry_run_migration inspects source SQLite tables and row counts without writes."""
    test_db = str(tmp_path / "test_store.db")
    conn = sqlite3.connect(test_db)
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT);")
    conn.execute("INSERT INTO products (name) VALUES ('Booster Box'), ('Playmat');")
    conn.commit()
    conn.close()

    # Dry run with mock PostgreSQL connection success
    with patch("core.db_migrator.test_postgres_connection", return_value={"ok": True, "latency_ms": 12.5}):
        res = dry_run_migration(
            direction="sqlite_to_postgres",
            sqlite_path=test_db,
            pg_host="localhost",
            pg_port=5432,
            pg_dbname="openpos_test",
            pg_user="postgres",
            pg_password=""
        )
        assert res["ok"] is True
        assert res["tables_count"] == 1
        assert res["total_rows"] == 2
        assert "Dry Run Passed" in res["message"]


def test_update_env_engine(tmp_path, monkeypatch):
    """Asserts atomic rewriting of data/config/.env engine parameters."""
    env_file = tmp_path / ".env"
    env_file.write_text("FLASK_ENV=production\nDB_ENGINE=sqlite\nPORT=5000\n", encoding="utf-8")

    monkeypatch.setattr(Config, "CONFIG_DIR", str(tmp_path))

    update_env_engine("postgresql", {
        "DB_HOST": "192.168.1.100",
        "DB_PORT": "5432",
        "DB_NAME": "openpos_network",
        "DB_USER": "pos_admin",
        "DB_PASSWORD": "secret_password"
    })

    content = env_file.read_text(encoding="utf-8")
    assert "DB_ENGINE=postgresql" in content
    assert "DB_HOST=192.168.1.100" in content
    assert "DB_NAME=openpos_network" in content


def test_api_database_status(client):
    """Asserts GET /api/database/status returns JSON status payload."""
    res = client.get("/api/database/status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "database" in data
    assert "engine" in data["database"]


def test_api_database_test_connection_sqlite(client):
    """Asserts POST /api/database/test_connection tests SQLite connection."""
    res = client.post("/api/database/test_connection", json={"engine": "sqlite"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "SQLite OK" in data["message"]


def test_api_database_dry_run_endpoint(client):
    """Asserts POST /api/database/dry_run handles dry run requests safely."""
    with patch("core.db_migrator.test_postgres_connection", return_value={"ok": True, "latency_ms": 10.0}):
        res = client.post("/api/database/dry_run", json={
            "direction": "sqlite_to_postgres",
            "host": "localhost",
            "port": 5432,
            "dbname": "openpos",
            "user": "postgres",
            "password": ""
        })
        assert res.status_code == 200
        data = res.get_json()
        assert data["ok"] is True
        assert "total_rows" in data


def test_api_database_switch_engine(client, tmp_path, monkeypatch):
    """Asserts POST /api/database/switch_engine updates engine configuration."""
    monkeypatch.setattr(Config, "CONFIG_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("DB_ENGINE=sqlite\n", encoding="utf-8")

    res = client.post("/api/database/switch_engine", json={"engine": "sqlite"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "sqlite" in data["message"].lower()


def test_js_bridge_save_recovery_file(tmp_path):
    """Asserts JSBridge save_recovery_file invokes Win32 save dialog and writes file."""
    bridge = JSBridge()

    target_file = str(tmp_path / "Saved_Recovery_Key.txt")

    mock_win = MagicMock()
    mock_win.create_file_dialog.return_value = [target_file]
    bridge._window = mock_win

    result = bridge.save_recovery_file("RECOVERY-TEST-CONTENT", "test.txt")
    assert result["status"] == "success"
    assert result["path"] == target_file

    with open(target_file, "r", encoding="utf-8") as f:
        assert f.read() == "RECOVERY-TEST-CONTENT"


def test_lockout_guard_contains_return_to_home():
    """Asserts that static/js/lockout_guard.js contains the prominent Return to Home button."""
    guard_path = os.path.join(Config.BASE_DIR, "static", "js", "lockout_guard.js")
    with open(guard_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "Return to Home" in content
    assert "btn-lockout-return" in content
    assert "backdrop-filter" in content
    assert "blur(" in content
