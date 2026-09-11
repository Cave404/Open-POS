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
    assert "v1.0.1" in html

def test_api_system_credits(client):
    """Asserts that GET /api/system/credits returns application metadata and dependency audit with v1.0.1."""
    res = client.get("/api/system/credits")
    assert res.status_code == 200
    data = res.get_json()
    assert data["version"] == "v1.0.1"
    assert "https://github.com/Cave404/Open-POS" in data["repository"]
    assert len(data["authors"]) >= 1
    assert len(data["dependencies"]) >= 5

    dep_names = [d["name"] for d in data["dependencies"]]
    assert "Flask" in dep_names
    assert "pywebview" in dep_names
    assert "pystray" in dep_names
    assert "Pillow" in dep_names

def test_placeholder_navigation_routes(client):
    """Asserts that all non-implemented built-in applet routes render placeholder view safely with btn-back."""
    for endpoint in ["/manager/database", "/manager/network", "/manager/cache", "/manager/logs"]:
        res = client.get(endpoint)
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Under Active Construction" in html
        assert "btn-back" in html
        assert "Return to Dashboard" in html

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
    """Asserts that /manager/api/applets includes the new about applet."""
    res = client.get("/manager/api/applets")
    assert res.status_code == 200
    applets = res.get_json()
    ids = [a["id"] for a in applets]
    assert "branding" in ids
    assert "database" in ids
    assert "network" in ids
    assert "cache" in ids
    assert "logs" in ids
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

def test_manager_dashboard_home_view(client):
    """Asserts that GET /manager renders the Home view as default with v1.0.1 footer."""
    res = client.get('/manager')
    assert res.status_code in (200, 308)
    if res.status_code == 308:
        res = client.get('/manager/')
    html = res.get_data(as_text=True)
    assert "Quick-Access Dashboard" in html
    assert "Home" in html
    assert "v1.0.1" in html

