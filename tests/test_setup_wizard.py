import os
import json
import pytest
from app import create_app
from core.config import Config
from core.setup import (
    is_setup_complete,
    mark_setup_complete,
    check_prerequisites,
    generate_crypto_keys,
    save_setup_configuration,
    get_recovery_key_text
)

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_check_prerequisites():
    """Asserts that runtime prerequisite inspection returns passing checks for python, drivers, and storage."""
    result = check_prerequisites()
    assert "all_passed" in result
    assert "checks" in result
    assert result["all_passed"] is True
    check_ids = [c["id"] for c in result["checks"]]
    assert "python_version" in check_ids
    assert "sqlite_driver" in check_ids
    assert "cryptography" in check_ids
    assert "data_isolation" in check_ids

def test_generate_crypto_keys():
    """Asserts that crypto generation produces 32-byte Fernet key, Secret key, and Recovery Token."""
    keys = generate_crypto_keys()
    assert "fernet_key" in keys
    assert "secret_key" in keys
    assert "recovery_token" in keys
    assert len(keys["fernet_key"]) >= 32
    assert len(keys["secret_key"]) == 64  # 32 bytes in hex
    assert keys["recovery_token"].startswith("OPOS-REC-")

def test_setup_wizard_views_and_apis(client, tmp_path, monkeypatch):
    """Asserts full onboarding flow: prerequisites, configuration, keys, recovery file, and 403 lockout."""
    # Ensure fresh setup marker path in temporary directory
    test_marker = str(tmp_path / ".setup_complete")
    test_env = str(tmp_path / ".env")
    test_auth = str(tmp_path / "manager_auth.json")

    monkeypatch.setattr("core.setup.wizard.SETUP_MARKER_PATH", test_marker)
    monkeypatch.setattr("core.setup.wizard.ENV_CONFIG_PATH", test_env)
    monkeypatch.setattr("core.setup.wizard.AUTH_CONFIG_PATH", test_auth)
    monkeypatch.setattr("manager.routes.AUTH_CONFIG_PATH", test_auth)

    # 1. Initially, setup is NOT complete
    assert is_setup_complete() is False

    # 2. View /setup renders setup wizard HTML
    view_res = client.get('/setup')
    assert view_res.status_code == 200
    html = view_res.get_data(as_text=True)
    assert "OpenPOS Setup Wizard" in html
    assert "Store Identity" in html
    assert "Emergency Recovery Sheet" in html

    # 3. API /api/setup/prerequisites
    prereq_res = client.get('/api/setup/prerequisites')
    assert prereq_res.status_code == 200
    assert prereq_res.get_json()["all_passed"] is True

    # 4. API /api/setup/submit
    submit_data = {
        "store_name": "Dragon's Lair TCG",
        "store_legal_name": "Dragon's Lair LLC",
        "store_location": "Seattle, WA",
        "admin_password": "masterAdminPassword99",
        "require_password": True,
        "db_engine": "sqlite"
    }
    submit_res = client.post('/api/setup/submit', json=submit_data)
    assert submit_res.status_code == 200
    res_data = submit_res.get_json()
    assert res_data["status"] == "success"
    assert res_data["store_name"] == "Dragon's Lair TCG"
    assert "fernet_key" in res_data
    assert "recovery_token" in res_data
    assert res_data["roundtrip_verified"] is True

    # Verify .env was written
    assert os.path.isfile(test_env)
    with open(test_env, 'r', encoding='utf-8') as f:
        env_content = f.read()
    assert "Dragon's Lair" not in env_content  # Store name lives in DB, not secrets
    assert "FERNET_KEY" in env_content
    assert "SECRET_KEY" in env_content

    # Verify manager_auth.json was written with salt and hash
    assert os.path.isfile(test_auth)
    with open(test_auth, 'r', encoding='utf-8') as f:
        auth_data = json.load(f)
    assert auth_data["require_password"] is True
    assert auth_data["password_hash"] != ""
    assert auth_data["salt"] != ""

    # 5. API /api/setup/recovery_file
    rec_res = client.get(f"/api/setup/recovery_file?store_name=Dragon's%20Lair%20TCG&recovery_token={res_data['recovery_token']}")
    assert rec_res.status_code == 200
    assert "text/plain" in rec_res.content_type
    rec_text = rec_res.get_data(as_text=True)
    assert "OPENPOS EMERGENCY SYSTEM DECRYPTION" in rec_text
    assert "Dragon's Lair TCG" in rec_text
    assert res_data['recovery_token'] in rec_text

    # 6. API /api/setup/complete
    complete_res = client.post('/api/setup/complete', json={"store_name": "Dragon's Lair TCG"})
    assert complete_res.status_code == 200
    assert complete_res.get_json()["status"] == "success"
    assert is_setup_complete() is True
    assert os.path.isfile(test_marker)

    # 7. Verify permanent lockout: /setup returns 403 Forbidden
    locked_view = client.get('/setup')
    assert locked_view.status_code == 403
    assert "403" in locked_view.get_data(as_text=True)
    assert "Setup Wizard Locked" in locked_view.get_data(as_text=True)

    # 8. Subsequent API submit calls return 403 Forbidden
    repeat_submit = client.post('/api/setup/submit', json=submit_data)
    assert repeat_submit.status_code == 403

    # 9. Subsequent API complete calls return 403 Forbidden
    repeat_complete = client.post('/api/setup/complete', json={})
    assert repeat_complete.status_code == 403

def test_recovery_key_sheet_formatter():
    """Asserts plain text recovery token document structure."""
    doc = get_recovery_key_text(
        store_name="Alpha Games",
        recovery_token="OPOS-REC-1111-2222-3333-4444-5555-6666",
        fernet_key="dummy_fernet_key_abc123"
    )
    assert "OPENPOS EMERGENCY SYSTEM DECRYPTION" in doc
    assert "Alpha Games" in doc
    assert "OPOS-REC-1111-2222-3333-4444-5555-6666" in doc
    assert "dummy_fernet_key_abc123" in doc
    assert "WARNING & SECURITY ADVISORY" in doc


def test_setup_wizard_fitment_and_sticky_footer(client, monkeypatch):
    """Asserts that setup_wizard.html implements sticky action footer, flex card, and scrollable content."""
    monkeypatch.setattr("manager.routes.is_setup_complete", lambda: False)
    monkeypatch.setattr("manager.routes.check_existing_installation", lambda: {"exists": False, "has_password": False, "has_keys": False})

    res = client.get("/manager/setup")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    # CSS flex column structure and viewport fitment
    assert "wizard-card" in html
    assert "wizard-step-content" in html
    assert "max-height: calc(100vh - 120px);" in html
    assert "overflow-y: auto;" in html

    # Sticky action footer
    assert "wizard-footer" in html
    assert "wizard-actions" in html
    assert "position: sticky;" in html
    assert "bottom: 0;" in html
    assert "flex-shrink: 0;" in html

    # Subtle scrollbars
    assert ".wizard-step-content::-webkit-scrollbar" in html
    assert "var(--border-color, #30363d)" in html
    assert "border-radius: 3px;" in html


def test_run_and_setup_window_dimensions():
    """Asserts that run.py and setup_wizard.py configure enlarged dimensions and easy_drag=False for setup."""
    with open("run.py", "r", encoding="utf-8") as f:
        run_content = f.read()

    with open("setup_wizard.py", "r", encoding="utf-8") as f:
        wizard_content = f.read()

    # run.py setup window
    assert "width=1080" in run_content
    assert "height=800" in run_content
    assert "min_size=(960, 650)" in run_content
    assert "easy_drag=False" in run_content

    # setup_wizard.py window
    assert "width=1080" in wizard_content
    assert "height=800" in wizard_content
    assert "min_size=(960, 650)" in wizard_content
    assert "easy_drag=False" in wizard_content

