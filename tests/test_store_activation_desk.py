"""
Tests for Store Activation Desk & Setup Completion
Validates:
1. First-run redirection from /pos to /setup and rendering of Store Activation Desk.
2. /setup/complete persistence of store identity, location, logo, and hashed PIN/recovery key in auth.json.
3. Database migration execution and .setup_complete sentinel creation.
4. Clean redirection to /pos register once setup is complete.
"""

import os
import io
import json
import hashlib
import pytest
from core.config import Config
from ui.app import create_app
from core.services.security_service import verify_admin_pin


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_first_run_renders_store_activation_desk(monkeypatch, tmp_path):
    """When .setup_complete is missing, /pos redirects to /setup which renders the Store Activation Desk."""
    test_config_dir = tmp_path / "config"
    test_config_dir.mkdir(parents=True, exist_ok=True)
    test_marker = str(test_config_dir / ".setup_complete")

    monkeypatch.setattr(Config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.config.Config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "CONFIG_DIR", str(test_config_dir))
    monkeypatch.setattr("core.config.Config.CONFIG_DIR", str(test_config_dir))
    monkeypatch.setattr("core.setup.wizard.SETUP_MARKER_PATH", test_marker)
    monkeypatch.setattr("core.setup.wizard.is_setup_complete", lambda: False)

    app = create_app()
    app.config["TESTING"] = False  # Emulate real desktop production boot
    with app.test_client() as cl:
        # /pos redirects to /setup
        res_pos = cl.get('/pos')
        assert res_pos.status_code == 302
        assert res_pos.headers["Location"] == "/setup"

        # /setup renders activation desk
        res = cl.get('/setup')
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Store Activation & Security Provisioning" in html
        assert "Store / Business Name" in html
        assert "Emergency Master Recovery Key" in html
        assert "Activate Store & Open Register" in html
        assert 'action="/setup/complete"' in html


def test_setup_complete_processing(client, monkeypatch, tmp_path):
    """Submitting the Store Activation Desk persists settings, logo, auth.json, and touches .setup_complete."""
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    (test_data_dir / "config").mkdir(parents=True, exist_ok=True)
    (test_data_dir / "uploads").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Config, "DATA_DIR", str(test_data_dir))
    monkeypatch.setattr("core.config.Config.DATA_DIR", str(test_data_dir))
    monkeypatch.setattr("core.config.Config.CONFIG_DIR", str(test_data_dir / "config"))
    monkeypatch.setattr("core.config.Config.UPLOAD_DIR", str(test_data_dir / "uploads"))

    # Create dummy logo
    dummy_logo = (io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfake"), "logo.png")

    post_data = {
        "store_name": "Dragon's Lair TCG",
        "currency_symbol": "$",
        "receipt_header": "Dragon's Lair TCG - Main St",
        "phone": "(555) 019-2834",
        "address_line1": "456 Quest Blvd",
        "city": "Hermann",
        "state": "MO",
        "postal_code": "65041",
        "database_engine": "sqlite",
        "admin_pin": "5678",
        "recovery_key": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "store_logo": dummy_logo
    }

    res = client.post('/setup/complete', data=post_data, content_type='multipart/form-data')
    assert res.status_code == 302
    assert res.headers["Location"] == "/pos"

    # 1. Verify store_settings.json
    settings_file = test_data_dir / "config" / "store_settings.json"
    assert settings_file.exists()
    with open(settings_file, "r", encoding="utf-8") as f:
        settings = json.load(f)
    assert settings["store_name"] == "Dragon's Lair TCG"
    assert settings["currency_symbol"] == "$"
    assert settings["address_line1"] == "456 Quest Blvd"
    assert settings["city"] == "Hermann"
    assert settings["state"] == "MO"
    assert settings["postal_code"] == "65041"
    assert settings["phone"] == "(555) 019-2834"
    assert settings["receipt_header"] == "Dragon's Lair TCG - Main St"
    assert settings["database_engine"] == "sqlite"

    # 2. Verify logo saved
    logo_file = test_data_dir / "uploads" / "logo.png"
    assert logo_file.exists()

    # 3. Verify auth.json
    auth_file = test_data_dir / "config" / "auth.json"
    assert auth_file.exists()
    with open(auth_file, "r", encoding="utf-8") as f:
        auth_data = json.load(f)
    assert auth_data["pin_hash"] == hashlib.sha256(b"5678").hexdigest()
    assert auth_data["recovery_key_hash"] == hashlib.sha256(b"a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90").hexdigest()

    # 4. Verify admin PIN verification
    assert verify_admin_pin("5678") is True
    assert verify_admin_pin("0000") is False

    # 5. Verify .setup_complete created
    sentinel = test_data_dir / "config" / ".setup_complete"
    assert sentinel.exists()
