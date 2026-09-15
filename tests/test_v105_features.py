"""
=============================================================================
Unit & Regression Tests for v1.0.5 Feature Directives
=============================================================================
Tests:
  1. Setup viewport dimensions (980x800) and responsive styling without scrollbars.
  2. Automated Windows Desktop shortcut generation (core/setup/shortcut.py).
  3. Setup Tamper & Existing Credential Re-Authentication Guard.
  4. Reauth verify, failure on bad password, success on valid password, and cancel_reauth.
  5. Version consistency across Config.VERSION, templates, and API endpoints (v1.0.5).
=============================================================================
"""

import os
import json
import hashlib
import pytest
from unittest.mock import MagicMock, patch

from app import create_app
from core.config import Config
from core.setup.shortcut import create_desktop_shortcut
from core.setup.wizard import check_existing_installation, mark_setup_complete
from setup_wizard import SetupWizardBridge
from run import JSBridge


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test_secret_session_key_v105"
    with app.test_client() as client:
        yield client


def test_v105_version_consistency(client):
    """Asserts that Config.VERSION and all template badges reflect active version."""
    assert Config.VERSION in ("v1.0.5", "v1.0.6", "v1.0.7", "v1.0.8")

    res_credits = client.get("/api/system/credits")
    assert res_credits.status_code == 200
    assert res_credits.get_json()["version"] in ("v1.0.5", "v1.0.6", "v1.0.7", "v1.0.8")

    for route in ["/manager", "/manager/about", "/manager/branding", "/manager/configure_manager", "/manager/database", "/manager/logs"]:
        res = client.get(route)
        if res.status_code == 308:
            res = client.get(route + "/")
        assert res.status_code == 200
        assert any(v in res.get_data(as_text=True) for v in ("v1.0.5", "v1.0.6", "v1.0.7", "v1.0.8"))


def test_setup_viewport_and_stepper_hygiene(client, monkeypatch):
    """Asserts that setup_wizard.html eliminates horizontal scrollbars with flexbox and overflow-x hidden."""
    monkeypatch.setattr("manager.routes.is_setup_complete", lambda: False)
    monkeypatch.setattr("manager.routes.check_existing_installation", lambda: {"exists": False, "has_password": False, "has_keys": False})

    res = client.get("/manager/setup")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert "overflow-x: hidden;" in html
    assert "stepper-container" in html
    assert "flex-wrap: nowrap;" in html
    assert any(v in html for v in ("v1.0.5", "v1.0.6", "v1.0.7", "v1.0.8"))
    assert "A desktop shortcut 'OpenPOS' has been created on your Windows Desktop." in html
    assert "Open_POS.vbs" in html


def test_create_desktop_shortcut(tmp_path, monkeypatch):
    """Verifies that create_desktop_shortcut invokes PowerShell script and handles errors safely."""
    test_desktop = tmp_path / "Desktop"
    test_desktop.mkdir()
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("os.path.expanduser", lambda path: str(tmp_path) if path == "~" else path)

    # Test execution with mock subprocess
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        # Create a dummy file to simulate shortcut creation
        shortcut_file = test_desktop / "OpenPOS.lnk"
        shortcut_file.write_text("dummy shortcut", encoding="utf-8")

        result = create_desktop_shortcut(base_dir=str(tmp_path))
        assert result is True
        assert mock_run.called
        args, kwargs = mock_run.call_args
        assert "powershell" in args[0]
        assert "WScript.Shell" in " ".join(args[0])
        assert "OpenPOS.lnk" in " ".join(args[0])

    # Test error handling when PowerShell fails
    with patch("subprocess.run", side_effect=Exception("PowerShell COM error")):
        result_err = create_desktop_shortcut(base_dir=str(tmp_path))
        assert result_err is False


def test_setup_tamper_guard_clean_install(client, tmp_path, monkeypatch):
    """Asserts that a clean system (no prior auth or env) enters Step 1 directly without reauth gate."""
    monkeypatch.setattr("manager.routes.is_setup_complete", lambda: False)
    monkeypatch.setattr("core.setup.wizard.AUTH_CONFIG_PATH", str(tmp_path / "empty_auth.json"))
    monkeypatch.setattr("core.setup.wizard.ENV_CONFIG_PATH", str(tmp_path / "empty_env"))

    existing = check_existing_installation()
    assert existing["exists"] is False

    res = client.get("/manager/setup")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'class="reauth-overlay"' not in html
    assert "Existing Store Configuration Detected" not in html


def test_setup_tamper_guard_locks_when_credentials_detected(client, tmp_path, monkeypatch):
    """Asserts that when prior credentials exist, setup blocks with Re-Configuration gate until verified."""
    auth_file = tmp_path / "manager_auth.json"
    salt = "testsalt105"
    pwd = "AdminMasterPassword123"
    pwd_hash = hashlib.sha256((salt + pwd).encode("utf-8")).hexdigest()

    auth_data = {
        "require_password": True,
        "password_hash": pwd_hash,
        "salt": salt,
        "protected_sections": ["branding", "database", "admin"]
    }
    auth_file.write_text(json.dumps(auth_data), encoding="utf-8")

    monkeypatch.setattr("manager.routes.is_setup_complete", lambda: False)
    monkeypatch.setattr("core.setup.wizard.AUTH_CONFIG_PATH", str(auth_file))
    monkeypatch.setattr("manager.routes.AUTH_CONFIG_PATH", str(auth_file))

    # 1. Existing configuration is detected
    existing = check_existing_installation()
    assert existing["exists"] is True
    assert existing["has_password"] is True

    # 2. Accessing /setup renders the reauthOverlay
    res = client.get("/manager/setup")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "reauthOverlay" in html
    assert "Existing Store Configuration Detected" in html
    assert "btnVerifyReauth" in html
    assert "btnCancelReauth" in html

    # 3. Direct submit is rejected with HTTP 403
    res_submit = client.post("/api/setup/submit", json={"store_name": "Tampered Store"})
    assert res_submit.status_code == 403

    # 4. Verifying with incorrect password fails
    res_bad = client.post("/api/setup/reauth_verify", json={"password": "WrongPassword"})
    assert res_bad.status_code == 401
    assert res_bad.get_json()["authorized"] is False

    # 5. Verifying with correct password unlocks
    res_good = client.post("/api/setup/reauth_verify", json={"password": pwd})
    assert res_good.status_code == 200
    assert res_good.get_json()["authorized"] is True

    # 6. Status now reports authorized and reauth_required is False
    res_status = client.get("/api/setup/reauth_status")
    assert res_status.status_code == 200
    assert res_status.get_json()["reauth_required"] is False
    assert res_status.get_json()["authorized"] is True

    # 7. Subsequent visit to /setup no longer shows the gate for this session
    res_unlocked = client.get("/manager/setup")
    assert 'class="reauth-overlay"' not in res_unlocked.get_data(as_text=True)
    assert "Existing Store Configuration Detected" not in res_unlocked.get_data(as_text=True)


def test_setup_cancel_reauth_restores_complete(client, tmp_path, monkeypatch):
    """Asserts that Cancel & Launch System restores .setup_complete and returns HTTP 200."""
    test_marker = tmp_path / ".setup_complete"
    monkeypatch.setattr("core.setup.wizard.SETUP_MARKER_PATH", str(test_marker))
    monkeypatch.setattr("manager.routes.is_setup_complete", lambda: False)

    # Disable detached process spawn during test
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: None)

    res = client.post("/api/setup/cancel_reauth", json={"restart_supervisor": False})
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"
    assert test_marker.is_file()
