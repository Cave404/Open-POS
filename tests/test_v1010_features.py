"""
tests/test_v1010_features.py
============================
Automated verification suite for OpenPOS v1.0.10 release milestone:
1. System version milestone strictly 1.0.10 in core/config.py and packaging/installer.iss.
2. Dynamic TCP port collision detection and sequential resolution (core/network.py).
3. Runtime configuration persistence of server_port in data/config/store_settings.json.
4. Store Activation Desk UI field and route handling for server_port (/setup and /setup/complete).
5. Template context processor and header version badge display v1.0.10.
"""

import os
import json
import socket
import pytest
from core.config import Config
from core.network import is_port_available, resolve_server_port
from ui.app import create_app


@pytest.fixture
def app_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.config.Config.DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr("core.config.Config.CONFIG_DIR", str(tmp_path / "config"))
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app_instance):
    with app_instance.test_client() as c:
        yield c


def test_v1010_version_milestone():
    """Asserts that Config.VERSION is strictly 1.0.10."""
    assert Config.VERSION == "1.0.10"


def test_installer_script_version_and_output_filename():
    """Asserts that packaging/installer.iss is configured for v1.0.10 and output filename."""
    installer_path = os.path.join(Config.BASE_DIR, "packaging", "installer.iss")
    assert os.path.isfile(installer_path)
    with open(installer_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert '#define MyAppVersion "1.0.10"' in content
    assert 'OutputBaseFilename=OpenPOS-Setup-{#MyAppVersion}' in content


def test_network_port_availability_and_resolution():
    """Asserts is_port_available and resolve_server_port handle open and occupied ports."""
    # Test free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        free_port = s.getsockname()[1]
    assert is_port_available(free_port) is True

    # Test occupied port & fallback scanning
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(1)
    occupied_port = sock.getsockname()[1]
    try:
        assert is_port_available(occupied_port) is False
        resolved = resolve_server_port(preferred_port=occupied_port, max_attempts=10)
        assert resolved > occupied_port
        assert is_port_available(resolved) is True
    finally:
        sock.close()


def test_config_port_persistence(tmp_path, monkeypatch):
    """Asserts store_settings.json server_port is read and written properly."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_file = config_dir / "store_settings.json"

    # Default fallback when settings missing
    monkeypatch.setattr(Config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr("core.config.Config.DATA_DIR", str(tmp_path))
    assert Config.get_configured_port() == 5050

    # Custom port persistence
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump({"server_port": 5080}, f)

    assert Config.get_configured_port() == 5080
    runtime = Config.determine_runtime_port()
    assert runtime == 5080
    assert Config.ACTIVE_PORT == 5080


def test_setup_activation_view_context(client, monkeypatch):
    """Asserts /setup renders with active_port and config_version in context."""
    monkeypatch.setattr("core.setup.wizard.is_setup_complete", lambda: False)
    monkeypatch.setattr("core.setup.is_setup_complete", lambda: False)
    res = client.get("/setup")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'name="server_port"' in html
    assert 'v1.0.10' in html or '1.0.10' in html


def test_setup_complete_persists_custom_port(client, tmp_path, monkeypatch):
    """Asserts POST /setup/complete extracts server_port and writes it to store_settings.json."""
    post_data = {
        "store_name": "Test Port Store",
        "currency_symbol": "$",
        "admin_pin": "1234",
        "recovery_key": "dummy_recovery_token",
        "database_engine": "sqlite",
        "server_port": "5099"
    }

    res = client.post("/setup/complete", data=post_data, follow_redirects=False)
    assert res.status_code in (200, 302)

    settings_file = tmp_path / "config" / "store_settings.json"
    assert settings_file.is_file()
    with open(settings_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("server_port") == 5099
    assert Config.ACTIVE_PORT == 5099


def test_header_version_badge_rendering(client):
    """Asserts manager routes render v1.0.10 badge."""
    res = client.get("/manager", follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "v1.0.10" in html or "1.0.10" in html


def test_manager_lock_modal_styling_and_dom_isolation(client, monkeypatch):
    """Asserts that main.css and manager_lock.html isolate the auth card from backdrop blur."""
    css_path = os.path.join(Config.BASE_DIR, "ui", "static", "css", "main.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".auth-lock-wrapper" in css
    assert ".auth-lock-card" in css
    assert "filter: none !important;" in css
    assert "backdrop-filter: none !important;" in css

    # Enable lockout guard in active Config.DATA_DIR
    config_dir = os.path.join(Config.DATA_DIR, "config")
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, ".setup_complete"), "w", encoding="utf-8") as f:
        f.write("PROVISIONED\n")

    auth_file = os.path.join(config_dir, "manager_auth.json")
    with open(auth_file, "w", encoding="utf-8") as f:
        json.dump({
            "require_password": True,
            "password_hash": "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3",
            "salt": "",
            "protected_sections": ["database", "branding", "addons"]
        }, f)

    monkeypatch.setattr("manager.routes.AUTH_CONFIG_PATH", auth_file)
    monkeypatch.setattr("core.setup.wizard.AUTH_CONFIG_PATH", auth_file)
    monkeypatch.setattr("core.services.security_service.AUTH_CONFIG_PATH", auth_file)
    monkeypatch.setattr("core.auth.AUTH_CONFIG_PATH", auth_file, raising=False)

    with client.session_transaction() as sess:
        sess.clear()

    # Test lock screen render
    res = client.get("/manager/database")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "auth-lock-wrapper" in html
    assert "auth-lock-card" in html
    assert 'id="managerLockForm"' in html
    assert 'id="adminPinInput"' in html
    assert "Manager Authentication Required" in html


def test_manager_addons_route_authenticated(client):
    """Asserts /manager/addons renders successfully with active and catalog addons."""
    with client.session_transaction() as sess:
        sess["manager_auth_verified"] = True

    res = client.get("/manager/addons")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Installed Addons" in html
    assert "Addon Catalog" in html
    assert "v1.0.10" in html or "1.0.10" in html


def test_system_tray_manager_and_packaging_spec():
    """Asserts SystemTrayManager functionality and PyInstaller packaging hiddenimports."""
    from unittest.mock import MagicMock
    from core.tray import SystemTrayManager
    from PIL import Image

    mock_win = MagicMock()
    mock_exit = MagicMock()
    tray = SystemTrayManager(app_window=mock_win, port=5050, on_exit_callback=mock_exit)

    # Test fallback icon generation
    fallback_icon = tray._create_fallback_icon()
    assert isinstance(fallback_icon, Image.Image)
    assert fallback_icon.size == (64, 64)

    # Test window show/restore
    tray.show_window("/manager")
    mock_win.load_url.assert_called_with("http://127.0.0.1:5050/manager")
    mock_win.show.assert_called_once()
    mock_win.restore.assert_called_once()

    # Test packaging spec includes tray and Pillow dependencies
    spec_path = os.path.join(Config.BASE_DIR, "packaging", "openpos.spec")
    with open(spec_path, "r", encoding="utf-8") as f:
        spec_content = f.read()
    assert '"pystray"' in spec_content
    assert '"PIL"' in spec_content
    assert '"pystray._win32"' in spec_content
    assert '"core.tray"' in spec_content

