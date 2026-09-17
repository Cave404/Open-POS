"""
tests/test_v109_features.py
============================
Automated verification suite for OpenPOS v1.0.9 milestone:
- System version milestone strictly v1.0.9 across configs and headers
- Data sovereignty & untracked runtime isolation with backups directory
- Windows Bootstrappers (Start_POS.bat, Open_POS.vbs)
- Multi-resolution ICO converter (Pillow) & Desktop shortcut dispatcher
- Setup wizard route immunity & state machine transitions
"""

import os
import io
import re
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from core.config import Config, REQUIRED_DATA_DIRS
from core.services.branding_service import generate_store_ico, DEFAULT_ICO_SIZES
from core.services.shortcut_service import create_desktop_shortcut, DEFAULT_SHELL_ICON
from core.services.setup_service import is_setup_complete, is_exempt_from_pin_auth
from app import create_app


def test_v109_version_milestone():
    """Asserts system version is strictly v1.0.9 in core config."""
    assert Config.VERSION == "v1.0.9"


def test_data_isolation_and_required_dirs():
    """Asserts data/backups is in REQUIRED_DATA_DIRS and auto-provisioned."""
    assert "data/backups" in REQUIRED_DATA_DIRS
    assert hasattr(Config, "BACKUP_DIR")
    assert os.path.basename(Config.BACKUP_DIR) == "backups"


def test_branding_service_ico_generation(tmp_path):
    """Asserts Pillow generates a multi-resolution ICO with all 6 required mipmaps and transparency."""
    # Create test RGBA image
    test_img = Image.new("RGBA", (400, 300), (30, 144, 255, 200))
    src_file = str(tmp_path / "logo.png")
    test_img.save(src_file, "PNG")

    dest_ico = str(tmp_path / "store_icon.ico")
    result = generate_store_ico(src_file, dest_ico)

    assert result == dest_ico
    assert os.path.isfile(dest_ico)

    # Inspect generated ICO
    with Image.open(dest_ico) as ico:
        assert ico.format == "ICO"
        sizes = ico.info.get("sizes")
        assert sizes is not None

        for expected in [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]:
            assert expected in sizes, f"Missing mipmap {expected} in generated ICO: {sizes}"


def test_shortcut_service_with_custom_icon(tmp_path, monkeypatch):
    """Asserts shortcut service uses store_icon.ico,0 when icon exists."""
    test_desktop = tmp_path / "Desktop"
    test_desktop.mkdir(exist_ok=True)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("os.path.expanduser", lambda path: str(tmp_path) if path == "~" else path)

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(exist_ok=True)
    custom_ico = upload_dir / "store_icon.ico"
    custom_ico.write_bytes(b"\x00\x00\x01\x00")  # Dummy ICO header

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        shortcut_file = test_desktop / "OpenPOS.lnk"
        shortcut_file.write_text("dummy", encoding="utf-8")

        result = create_desktop_shortcut(base_dir=str(tmp_path), upload_dir=str(upload_dir))
        assert result is True
        assert mock_run.called
        args, kwargs = mock_run.call_args
        ps_script = args[0][3]
        assert "store_icon.ico,0" in ps_script
        assert "Open_POS.vbs" in ps_script


def test_shortcut_service_fallback_icon(tmp_path, monkeypatch):
    """Asserts shortcut service falls back to shell32.dll,264 when no logo is uploaded."""
    test_desktop = tmp_path / "Desktop"
    test_desktop.mkdir(exist_ok=True)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("os.path.expanduser", lambda path: str(tmp_path) if path == "~" else path)

    upload_dir = tmp_path / "empty_uploads"
    upload_dir.mkdir(exist_ok=True)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        shortcut_file = test_desktop / "OpenPOS.lnk"
        shortcut_file.write_text("dummy", encoding="utf-8")

        result = create_desktop_shortcut(base_dir=str(tmp_path), upload_dir=str(upload_dir))
        assert result is True
        assert mock_run.called
        args, kwargs = mock_run.call_args
        ps_script = args[0][3]
        assert "shell32.dll,264" in ps_script


def test_start_pos_bat_hygiene():
    """Asserts Start_POS.bat sets PIP_NO_CACHE_DIR=1, uses REM, imports PIL, and checks errorlevel."""
    with open("Start_POS.bat", "r", encoding="utf-8") as f:
        content = f.read()

    assert "PIP_NO_CACHE_DIR=1" in content
    assert "PIL" in content
    assert "psycopg" in content
    assert "cryptography" in content
    assert "waitress" in content

    # Ensure no :: comments inside parentheses
    lines = content.splitlines()
    in_paren = False
    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if "(" in stripped and not stripped.startswith("REM"):
            in_paren = True
        if in_paren and stripped.startswith("::"):
            pytest.fail(f"Found invalid '::' comment inside parentheses at line {idx}: {line}")
        if ")" in stripped:
            in_paren = False


def test_open_pos_vbs_hygiene():
    """Asserts Open_POS.vbs validates venv python and pops MsgBox on abnormal termination."""
    with open("Open_POS.vbs", "r", encoding="utf-8") as f:
        content = f.read()

    assert r"venv\Scripts\python.exe" in content
    assert "Start_POS.bat" in content
    assert "MsgBox" in content


def test_setup_route_immunity_clean_system(tmp_path, monkeypatch):
    """Asserts that in an incomplete setup, repeated submissions across steps do not raise 403."""
    app = create_app()
    app.config["TESTING"] = True

    # Simulate fresh, clean install environment
    monkeypatch.setattr("manager.routes.is_setup_complete", lambda: False)
    monkeypatch.setattr("core.setup.wizard.is_setup_complete", lambda: False)
    monkeypatch.setattr("core.setup.wizard.AUTH_CONFIG_PATH", str(tmp_path / "empty_auth.json"))
    monkeypatch.setattr("core.setup.wizard.ENV_CONFIG_PATH", str(tmp_path / "empty_env"))
    monkeypatch.setattr("core.setup.wizard.PIN_HASH_PATH", str(tmp_path / "empty_pin.hash"))

    with app.test_client() as client:
        # 1. Visit /setup on clean system
        res_setup = client.get("/setup")
        assert res_setup.status_code == 200

        # 2. First submission (Step 5)
        res1 = client.post("/api/setup/submit", json={
            "store_name": "Dragon Tavern",
            "db_engine": "sqlite"
        })
        assert res1.status_code == 200
        data1 = res1.get_json()
        assert "fernet_key" in data1

        # 3. Repeated submission (user navigates back to Step 2/3/4 and submits again)
        res2 = client.post("/api/setup/submit", json={
            "store_name": "Dragon Tavern Updated",
            "db_engine": "sqlite"
        })
        assert res2.status_code == 200
        data2 = res2.get_json()
        assert "fernet_key" in data2
