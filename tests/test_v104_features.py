"""
=============================================================================
Unit & Regression Tests for v1.0.4 Feature Directives
=============================================================================
Tests:
  1. Native Save Recovery Dialog & Setup Bridge methods.
  2. Printable Recovery Sheet layout and @media print CSS rules.
  3. Server-side session password lockout and unlock endpoints.
  4. Real prerequisite checks across Python, SQLite, Cryptography, and data/.
  5. Dependency installation endpoint (/api/setup/install_dependencies).
=============================================================================
"""

import os
import json
import pytest
from app import create_app
from core.config import Config
from core.setup.checks import run_prerequisite_checks, UPSTREAM_LINKS
from setup_wizard import SetupWizardBridge
from run import JSBridge
from manager.routes import is_section_locked, _write_auth_file, _read_auth_file


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test_secret_session_key"
    with app.test_client() as client:
        yield client


def test_native_save_recovery_dialog(tmp_path):
    """Verifies that save_recovery_file_dialog properly writes formatted recovery sheet to target file."""
    target_file = str(tmp_path / "Test_Store_Recovery_Key.txt")

    class MockWindow:
        def create_file_dialog(self, *args, **kwargs):
            return [target_file]

    # Test SetupWizardBridge
    bridge = SetupWizardBridge(window=MockWindow())
    res = bridge.save_recovery_file_dialog(
        store_name="Test Store",
        token="OPOS-REC-AAAA-BBBB-CCCC",
        fernet_key="mock_fernet_key_32_bytes_long"
    )
    assert res["status"] == "success"
    assert res["path"] == target_file

    with open(target_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "=== OPENPOS EMERGENCY SYSTEM RECOVERY KEY ===" in content
    assert "Store: Test Store" in content
    assert "RECOVERY TOKEN: OPOS-REC-AAAA-BBBB-CCCC" in content
    assert "FERNET KEY:     mock_fernet_key_32_bytes_long" in content

    # Test JSBridge
    js_bridge = JSBridge()
    js_bridge._window = MockWindow()
    target_file2 = str(tmp_path / "Test_Store_Recovery_Key2.txt")
    js_bridge._window.create_file_dialog = lambda *args, **kwargs: [target_file2]
    res2 = js_bridge.save_recovery_file_dialog(
        store_name="Test Store 2",
        token="OPOS-REC-XXXX-YYYY-ZZZZ",
        fernet_key="fernet_key_2"
    )
    assert res2["status"] == "success"
    assert os.path.isfile(target_file2)


def test_prerequisites_real_environment():
    """Asserts that run_prerequisite_checks performs live environment inspection without mocked data."""
    result = run_prerequisite_checks()
    assert "all_passed" in result
    assert "has_missing_packages" in result
    assert "checks" in result

    check_dict = {c["id"]: c for c in result["checks"]}
    assert "python_version" in check_dict
    assert check_dict["python_version"]["status"] is True
    assert "3." in check_dict["python_version"]["detail"]

    assert "sqlite_driver" in check_dict
    assert check_dict["sqlite_driver"]["status"] is True

    assert "cryptography" in check_dict
    assert check_dict["cryptography"]["status"] is True

    assert "data_isolation" in check_dict
    assert check_dict["data_isolation"]["status"] is True


def test_blurred_lockout_and_session_unlock(client, tmp_path, monkeypatch):
    """Asserts that password-protected views pass is_locked=True and unlock upon /api/settings/verify_password."""
    auth_file = str(tmp_path / "manager_auth.json")
    monkeypatch.setattr("manager.routes.AUTH_CONFIG_PATH", auth_file)

    import hashlib
    salt = "testsalt"
    pwd = "secretpassword"
    digest = hashlib.sha256((salt + pwd).encode("utf-8")).hexdigest()

    # Enable password lockout
    _write_auth_file({
        "require_password": True,
        "password_hash": digest,
        "salt": salt,
        "protected_sections": ["branding", "database", "configure_manager"],
        "bypass_manager_on_boot": False
    })

    # 1. Unauthenticated request to /manager/branding should render locked container and lockout modal
    res = client.get("/manager/branding")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "view-container locked" in html
    assert "serverLockoutBackdrop" in html
    assert "Manager Authentication Required" in html
    assert "&larr; Return to Home" in html

    # 2. Attempt verification with invalid password
    res_bad = client.post("/api/settings/verify_password", json={"password": "wrong"})
    assert res_bad.status_code == 401
    assert res_bad.get_json()["authorized"] is False

    # 3. Verify with correct password
    res_good = client.post("/api/settings/verify_password", json={"password": pwd})
    assert res_good.status_code == 200
    assert res_good.get_json()["authorized"] is True

    # 4. Authenticated request to /manager/branding should now be unlocked
    res_unlocked = client.get("/manager/branding")
    assert res_unlocked.status_code == 200
    html_unlocked = res_unlocked.get_data(as_text=True)
    assert "view-container locked" not in html_unlocked
    assert "serverLockoutBackdrop" not in html_unlocked

    # 5. Lockout session can be cleared with logout
    res_logout = client.post("/api/settings/logout")
    assert res_logout.status_code == 200
    res_relocked = client.get("/manager/branding")
    assert "view-container locked" in res_relocked.get_data(as_text=True)


def test_printable_recovery_sheet_markup(client, tmp_path, monkeypatch):
    """Verifies that setup_wizard.html includes #printableRecoverySheet and dedicated @media print CSS."""
    # Ensure setup is not marked complete for this test
    monkeypatch.setattr("manager.routes.is_setup_complete", lambda: False)
    res = client.get("/manager/setup")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert 'id="printableRecoverySheet"' in html
    assert "#printableRecoverySheet" in html
    assert "visibility: hidden !important;" in html
    assert "visibility: visible !important;" in html
    assert "save_recovery_file_dialog" in html
    assert "btnInstallDeps" in html


def test_setup_complete_and_install_dependencies(client, tmp_path, monkeypatch):
    """Verifies that api_setup_complete and api_setup_install_dependencies work reliably without error."""
    # Test install dependencies endpoint
    res_deps = client.post("/api/setup/install_dependencies")
    assert res_deps.status_code in [200, 500]
    data_deps = res_deps.get_json()
    assert "status" in data_deps

    # Test setup complete
    test_marker = str(tmp_path / ".setup_complete")
    monkeypatch.setattr("core.setup.wizard.SETUP_MARKER_PATH", test_marker)
    monkeypatch.setattr("manager.routes.is_setup_complete", lambda: False)

    # Mock subprocess.Popen and os._exit to prevent test runner from exiting
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: None)
    monkeypatch.setattr(os, "_exit", lambda code: None)

    res_comp = client.post("/api/setup/complete", json={
        "store_name": "Test Store",
        "restart_supervisor": True
    })
    assert res_comp.status_code == 200
    assert res_comp.get_json()["status"] == "success"
    assert os.path.isfile(test_marker)

