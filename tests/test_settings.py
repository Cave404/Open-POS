import os
import io
import json
import pytest
from core.config import Config
from core.db import init_db, get_db_connection, execute_sql
from core.settings import get_setting, set_setting, get_all_settings, seed_default_settings, DEFAULT_SETTINGS
from app import create_app

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """
    Sets up an isolated temporary SQLite database for each test.
    """
    test_db_file = str(tmp_path / "test_pos.db")
    monkeypatch.setattr(Config, "DB_ENGINE", "sqlite")
    monkeypatch.setattr(Config, "DB_NAME", test_db_file)
    init_db()
    yield
    # Clean up
    if os.path.exists(test_db_file):
        try:
            os.remove(test_db_file)
        except OSError:
            pass

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_default_settings_seeding():
    """Asserts that defaults are seeded on initial access when settings table is empty."""
    assert get_setting("store_name") == "Open-POS System"
    assert get_setting("store_legal_entity") == "Open-POS Retail LLC"
    assert get_setting("store_location") == "Local Network"
    assert get_setting("cash_payout_rate") == 60.0
    assert get_setting("credit_payout_rate") == 80.0
    assert get_setting("daily_trade_limit") == 10
    assert get_setting("store_logo_url") == ""
    
    pinned_raw = get_setting("pinned_tools")
    assert pinned_raw is not None
    pinned_list = json.loads(pinned_raw) if isinstance(pinned_raw, str) else pinned_raw
    assert "branding" in pinned_list
    assert "database" in pinned_list
    
    cond_raw = get_setting("condition_multipliers")
    assert cond_raw is not None
    cond_dict = json.loads(cond_raw) if isinstance(cond_raw, str) else cond_raw
    assert cond_dict["NM"] == 1.0
    assert cond_dict["LP"] == 0.85
    assert cond_dict["MP"] == 0.70
    assert cond_dict["HP"] == 0.50
    assert cond_dict["DMG"] == 0.30

def test_set_and_get_setting():
    """Asserts that values written via set_setting update the database and return properly through get_setting."""
    success = set_setting("store_name", "Card Kingdom Nexus")
    assert success is True
    assert get_setting("store_name") == "Card Kingdom Nexus"

    success = set_setting("cash_payout_rate", 65.5)
    assert success is True
    assert get_setting("cash_payout_rate") == 65.5

    success = set_setting("daily_trade_limit", 25)
    assert success is True
    assert get_setting("daily_trade_limit") == 25

def test_get_setting_fallback_default():
    """Asserts that get_setting returns the provided default when key does not exist."""
    assert get_setting("non_existent_key", "default_val") == "default_val"
    assert get_setting("another_missing_key", 999) == 999
    assert get_setting("missing_float", 12.34) == 12.34

def test_get_all_settings():
    """Asserts that get_all_settings returns all active configuration keys and values."""
    all_settings = get_all_settings()
    assert isinstance(all_settings, dict)
    assert "store_name" in all_settings
    assert "cash_payout_rate" in all_settings
    assert "credit_payout_rate" in all_settings
    assert "daily_trade_limit" in all_settings
    assert "condition_multipliers" in all_settings
    assert "store_logo_url" in all_settings
    assert "pinned_tools" in all_settings

def test_condition_multipliers_json_persistence():
    """Asserts that condition_multipliers can be set as a dict and persists as valid JSON."""
    new_multipliers = {
        "NM": 1.0,
        "LP": 0.80,
        "MP": 0.65,
        "HP": 0.40,
        "DMG": 0.20
    }
    success = set_setting("condition_multipliers", new_multipliers)
    assert success is True

    retrieved = get_setting("condition_multipliers")
    parsed = json.loads(retrieved) if isinstance(retrieved, str) else retrieved
    assert parsed == new_multipliers

def test_api_get_settings(client):
    """Asserts that GET /api/settings and GET /manager/api/settings return the configuration payload."""
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.get_json()
    assert data["store_name"] == "Open-POS System"
    assert data["cash_payout_rate"] == 60.0

    # Also test the /manager/api/settings endpoint
    res_mgr = client.get("/manager/api/settings")
    assert res_mgr.status_code == 200
    assert res_mgr.get_json()["store_name"] == "Open-POS System"

def test_api_post_settings_success(client):
    """Asserts that POST /api/settings validates and updates configuration settings."""
    payload = {
        "store_name": "Vault 101 Games",
        "store_legal_entity": "Vault 101 LLC",
        "store_location": "Austin, TX",
        "cash_payout_rate": 65.0,
        "credit_payout_rate": 85.0,
        "daily_trade_limit": 20,
        "condition_multipliers": {
            "NM": 1.0,
            "LP": 0.85,
            "MP": 0.70,
            "HP": 0.50,
            "DMG": 0.25
        }
    }
    res = client.post("/api/settings", json=payload)
    assert res.status_code == 200
    assert res.get_json() == {"status": "success"}

    # Assert persistence in database
    assert get_setting("store_name") == "Vault 101 Games"
    assert get_setting("cash_payout_rate") == 65.0
    assert get_setting("credit_payout_rate") == 85.0
    assert get_setting("daily_trade_limit") == 20

def test_api_post_settings_validation_errors(client):
    """Asserts that invalid inputs are rejected with HTTP 400 and error message."""
    # Out of range cash payout (> 100)
    res = client.post("/api/settings", json={"cash_payout_rate": 150.0})
    assert res.status_code == 400
    assert "percentage between 0 and 100" in res.get_json()["message"]

    # Negative credit payout
    res = client.post("/api/settings", json={"credit_payout_rate": -10.0})
    assert res.status_code == 400
    assert "percentage between 0 and 100" in res.get_json()["message"]

    # Invalid daily trade limit (zero or negative)
    res = client.post("/api/settings", json={"daily_trade_limit": 0})
    assert res.status_code == 400
    assert "greater than or equal to 1" in res.get_json()["message"]

    # Empty store name
    res = client.post("/api/settings", json={"store_name": "   "})
    assert res.status_code == 400
    assert "Store name cannot be empty" in res.get_json()["message"]

    # Invalid JSON body
    res = client.post("/api/settings", data="not-json", content_type="application/json")
    assert res.status_code == 400

def test_branding_view_route(client):
    """Asserts that GET /manager/branding renders the branding template with tactile navigation."""
    res = client.get("/manager/branding")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Store Identity &amp; Rules Configuration" in html or "Store Identity" in html
    assert "btn-back" in html
    assert "Return to Dashboard" in html
    assert "brandingForm" in html
    assert "cash_payout_rate" in html
    assert "logoPreviewBox" in html
    # Ensure no faux window controls exist
    assert "cde-title-controls" not in html
    assert "manager-titlebar" not in html

def test_about_view_route(client):
    """Asserts that GET /manager/about renders the credits and about template with tactile back navigation."""
    res = client.get("/manager/about")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Open-POS System" in html
    assert "btn-back" in html
    assert "Return to Dashboard" in html
    assert "Third-Party Dependencies" in html
    assert "Cave404" in html
    assert "v1.0.5" in html

def test_api_system_credits(client):
    """Asserts that GET /api/system/credits returns application metadata and dependency audit with v1.0.5."""
    res = client.get("/api/system/credits")
    assert res.status_code == 200
    data = res.get_json()
    assert data["version"] == "v1.0.5"
    assert "https://github.com/Cave404/Open-POS" in data["repository"]
    assert len(data["authors"]) >= 1
    assert len(data["dependencies"]) >= 5

    dep_names = [d["name"] for d in data["dependencies"]]
    assert "Flask" in dep_names
    assert "pywebview" in dep_names
    assert "pystray" in dep_names
    assert "Pillow" in dep_names

def test_placeholder_navigation_routes(client):
    """Asserts that non-implemented built-in applet routes render placeholder view safely with btn-back."""
    for endpoint in ["/manager/network", "/manager/cache"]:
        res = client.get(endpoint)
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Under Active Construction" in html
        assert "btn-back" in html
        assert "Return to Dashboard" in html

def test_database_view_route(client):
    """Asserts that /manager/database renders the dedicated database tools & migration template."""
    res = client.get("/manager/database")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Database Tools" in html
    assert "Active Engine" in html
    assert "Switch Engine / Migrate Database" in html
    assert "Test Connection" in html
    assert "Start Automated Conversion" in html
    assert "btn-back" in html

def test_generic_placeholder_route(client):
    """Asserts that any unconfigured applet ID safely falls back to placeholder."""
    res = client.get("/manager/placeholder/future_addon")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Future Addon" in html
    assert "Under Active Construction" in html
    assert "btn-back" in html
    assert "Return to Dashboard" in html

def test_applets_list_includes_about(client):
    """Asserts that /manager/api/applets includes the about and configure_manager applets."""
    res = client.get("/manager/api/applets")
    assert res.status_code == 200
    applets = res.get_json()
    ids = [a["id"] for a in applets]
    assert "branding" in ids
    assert "database" in ids
    assert "network" in ids
    assert "cache" in ids
    assert "logs" in ids
    assert "configure_manager" in ids
    assert "about" in ids

def test_api_logo_upload_success_and_delete(client):
    """Asserts that POST /api/settings/logo uploads a valid image to data/uploads and DELETE removes it."""
    # 1. Valid image upload
    img_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    data = {
        'logo': (io.BytesIO(img_data), 'test_logo.png')
    }
    res = client.post('/api/settings/logo', data=data, content_type='multipart/form-data')
    assert res.status_code == 200
    resp_json = res.get_json()
    assert resp_json["status"] == "success"
    assert "/data/uploads/store_logo.png" in resp_json["logo_url"]
    assert get_setting("store_logo_url") == "/data/uploads/store_logo.png"

    # 2. Verify file exists in Config.UPLOAD_DIR
    expected_path = os.path.join(Config.UPLOAD_DIR, 'store_logo.png')
    assert os.path.exists(expected_path)

    # 3. Verify static serving route /data/uploads/store_logo.png
    serve_res = client.get('/data/uploads/store_logo.png')
    assert serve_res.status_code == 200

    # 4. Delete logo
    del_res = client.delete('/api/settings/logo')
    assert del_res.status_code == 200
    assert del_res.get_json()["status"] == "success"
    assert get_setting("store_logo_url") == ""

def test_api_logo_upload_validation(client):
    """Asserts that POST /api/settings/logo validates file size and extension."""
    # Disallowed extension
    data = {
        'logo': (io.BytesIO(b"executable file"), 'malicious.exe')
    }
    res = client.post('/api/settings/logo', data=data, content_type='multipart/form-data')
    assert res.status_code == 400
    assert "Invalid image format" in res.get_json()["message"]

    # File size exceeding 2MB
    large_payload = b"0" * (2 * 1024 * 1024 + 10)
    data_large = {
        'logo': (io.BytesIO(large_payload), 'large.png')
    }
    res_large = client.post('/api/settings/logo', data=data_large, content_type='multipart/form-data')
    assert res_large.status_code == 400
    assert "File size exceeds 2MB limit" in res_large.get_json()["message"]

def test_api_pinned_tools(client):
    """Asserts GET and POST /api/settings/pinned functionality."""
    # 1. GET returns default list
    res = client.get('/api/settings/pinned')
    assert res.status_code == 200
    data = res.get_json()
    assert "pinned_tools" in data
    assert "branding" in data["pinned_tools"]
    assert "database" in data["pinned_tools"]

    # 2. POST updates pinned tools
    new_pinned = ["branding", "network", "logs"]
    post_res = client.post('/api/settings/pinned', json={"pinned_tools": new_pinned})
    assert post_res.status_code == 200
    assert post_res.get_json()["status"] == "success"

    # 3. Verify GET returns updated list
    get_updated = client.get('/api/settings/pinned')
    assert get_updated.status_code == 200
    assert get_updated.get_json()["pinned_tools"] == new_pinned

    # 4. Bad request validation
    bad_res = client.post('/api/settings/pinned', json={"pinned_tools": "not-a-list"})
    assert bad_res.status_code == 400

def test_data_directory_structure():
    """Asserts that isolated private data subdirectories are initialized."""
    assert os.path.isdir(Config.DATA_DIR)
    assert os.path.isdir(Config.DB_DIR)
    assert os.path.isdir(Config.CACHE_DIR)
    assert os.path.isdir(Config.UPLOAD_DIR)
    assert os.path.isdir(Config.LOGS_DIR)
    assert os.path.isdir(Config.CUSTOM_ADDONS_DIR)
    assert os.path.isdir(Config.CONFIG_DIR)

def test_manager_dashboard_home_view(client):
    """Asserts that GET /manager renders the Home view as default with v1.0.4 footer and notification bell."""
    res = client.get('/manager')
    assert res.status_code in (200, 308)
    if res.status_code == 308:
        res = client.get('/manager/')
    html = res.get_data(as_text=True)
    assert "Quick-Access Dashboard" in html
    assert "Home" in html
    assert "v1.0.5" in html
    assert "notifBellBtn" in html
    assert "configure_manager" in html

def test_logs_view_route(client):
    """Asserts that GET /manager/logs renders the Terminal Logs interface."""
    res = client.get('/manager/logs')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Terminal Logs &amp; Diagnostics" in html or "Terminal Logs" in html
    assert "btn-back" in html
    assert "Return to Dashboard" in html
    assert "btnExportCsv" in html
    assert "btnDownloadLog" in html
    assert "btnOpenLiveTerminal" in html
    assert "v1.0.5" in html

def test_configure_manager_view_route(client):
    """Asserts that GET /manager/configure_manager renders the Configure Manager view."""
    res = client.get('/manager/configure_manager')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Configure Manager &amp; Administration" in html or "Configure Manager" in html
    assert "btn-back" in html
    assert "Return to Dashboard" in html
    assert "requirePasswordToggle" in html
    assert "bypassManagerToggle" in html
    assert "btnScanPackages" in html
    assert "password-grid" in html
    assert "v1.0.5" in html

def test_notifications_service_and_apis(client):
    """Asserts that notification queue operations and REST endpoints function correctly."""
    # 1. GET notifications
    res = client.get('/api/notifications')
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "notifications" in data
    assert "unread_count" in data

    # 2. POST test notification
    test_alert = {
        "level": "WARNING",
        "subsystem": "PRICE_ENGINE",
        "message": "TCGdex pricing API throttle event detected."
    }
    post_res = client.post('/api/notifications/test', json=test_alert)
    assert post_res.status_code == 200
    alert_resp = post_res.get_json()
    assert alert_resp["status"] == "success"
    assert alert_resp["alert"]["level"] == "WARNING"
    assert alert_resp["alert"]["subsystem"] == "PRICE_ENGINE"

    # 3. Verify notification appears in GET /api/notifications
    res2 = client.get('/api/notifications')
    data2 = res2.get_json()
    assert any(n["message"] == "TCGdex pricing API throttle event detected." for n in data2["notifications"])

    # 4. Clear notifications
    clear_res = client.post('/api/notifications/clear')
    assert clear_res.status_code == 200
    assert clear_res.get_json()["status"] == "success"

    res_empty = client.get('/api/notifications')
    assert res_empty.get_json()["unread_count"] == 0

def test_terminal_logs_api(client):
    """Asserts that logs query, CSV export, raw txt download, and SSE live stream endpoints function."""
    # 1. Query logs
    res = client.get('/api/logs')
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert isinstance(data["logs"], list)

    # 2. Export CSV (both /api/logs/export/csv and /api/logs/export)
    for csv_url in ['/api/logs/export/csv', '/api/logs/export?format=csv']:
        csv_res = client.get(csv_url)
        assert csv_res.status_code == 200
        assert "text/csv" in csv_res.content_type
        assert "Timestamp,Subsystem,Level,Message" in csv_res.get_data(as_text=True)

    # 3. Download txt (both /api/logs/download/txt and /api/logs/download)
    for txt_url in ['/api/logs/download/txt', '/api/logs/download']:
        txt_res = client.get(txt_url)
        assert txt_res.status_code == 200
        assert "text/plain" in txt_res.content_type

    # 4. SSE live stream endpoint verification
    stream_res = client.get('/api/logs/live_stream?subsystem=CORE')
    assert stream_res.status_code == 200
    assert "text/event-stream" in stream_res.content_type

def test_admin_auth_and_lockout_api(client, tmp_path, monkeypatch):
    """Asserts password hashing, security policy persistence, and verification."""
    test_auth_file = str(tmp_path / "manager_auth.json")
    monkeypatch.setattr("manager.routes.AUTH_CONFIG_PATH", test_auth_file)

    # Read initial status (fresh isolated config)
    res = client.get('/api/admin/auth/status')
    assert res.status_code == 200
    initial_status = res.get_json()
    assert initial_status["status"] == "success"
    assert initial_status["has_password"] is False
    assert initial_status["require_password"] is False

    # Attempt to enable lockout without setting password
    bad_req = client.post('/api/admin/auth/configure', json={
        "require_password": True,
        "new_password": ""
    })
    assert bad_req.status_code == 400

    # Password confirmation mismatch test
    mismatch_req = client.post('/api/admin/auth/configure', json={
        "new_password": "password123",
        "confirm_password": "differentPassword"
    })
    assert mismatch_req.status_code == 400
    assert "do not match" in mismatch_req.get_json()["message"]

    # Initial password setup (no current password exists, should succeed without current_password)
    set_res = client.post('/api/settings/security', json={
        "require_password": True,
        "new_password": "posSecurePassword123",
        "confirm_password": "posSecurePassword123",
        "protected_sections": ["branding", "database"],
        "bypass_manager_on_boot": True
    })
    assert set_res.status_code == 200
    assert set_res.get_json()["status"] == "success"

    # Now that password exists, attempting to change without valid current_password fails
    bad_current = client.post('/api/admin/auth/configure', json={
        "current_password": "wrongOldPassword",
        "new_password": "newSecurePassword456",
        "confirm_password": "newSecurePassword456"
    })
    assert bad_current.status_code == 400
    assert "Current password does not match" in bad_current.get_json()["message"]

    # Verify status reflects updated policy
    status_res = client.get('/api/admin/auth/status')
    status_data = status_res.get_json()
    assert status_data["has_password"] is True
    assert status_data["require_password"] is True
    assert status_data["bypass_manager_on_boot"] is True
    assert "branding" in status_data["protected_sections"]

    # Verify auth verification endpoint: wrong password
    verify_fail = client.post('/api/admin/auth/verify', json={
        "password": "wrongPassword",
        "section": "branding"
    })
    assert verify_fail.status_code == 401
    assert verify_fail.get_json()["authorized"] is False

    # Verify auth verification endpoint: correct password
    verify_ok = client.post('/api/admin/auth/verify', json={
        "password": "posSecurePassword123",
        "section": "branding"
    })
    assert verify_ok.status_code == 200
    assert verify_ok.get_json()["authorized"] is True

    # Section not protected should succeed even with wrong password
    unprotected_ok = client.post('/api/admin/auth/verify', json={
        "password": "wrongPassword",
        "section": "network"
    })
    assert unprotected_ok.status_code == 200
    assert unprotected_ok.get_json()["authorized"] is True

def test_system_packages_and_restart_api(client):
    """Asserts package updates query and restart acknowledgment APIs."""
    # Query packages
    res = client.get('/api/system/packages')
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert isinstance(data["packages"], list)

    # Invalid package identifier for upgrade
    bad_upgrade = client.post('/api/system/packages/upgrade', json={
        "package": "invalid; rm -rf"
    })
    assert bad_upgrade.status_code == 400

    # Trigger system restart
    restart_res = client.post('/api/system/restart')
    assert restart_res.status_code == 200
    assert restart_res.get_json()["status"] == "success"



