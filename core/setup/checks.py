"""
=============================================================================
Open-POS Setup Prerequisite Verification & Auto-Pip Pipeline
=============================================================================
Executes real system introspection checks before onboarding:
  1. Python runtime >= 3.12 check.
  2. Package import tests: sqlite3, psycopg, cryptography, pywebview, pystray.
  3. Upstream official download links for missing runtimes and drivers.
  4. Write permissions across private data/ subdirectories.
  5. Automated pip installation pipeline via subprocess execution.
=============================================================================
"""

import os
import sys
import subprocess
import logging
from typing import Dict, Any, List

from core.config import Config

logger = logging.getLogger(__name__)

# Upstream distribution download links
UPSTREAM_LINKS = {
    "python": "https://www.python.org/downloads/",
    "postgresql": "https://www.postgresql.org/download/",
    "pypi": "https://pypi.org/",
}


def run_prerequisite_checks() -> Dict[str, Any]:
    """
    Performs live runtime environment checks for Open-POS.
    Eliminates all mocked responses: uses active Python sys.version and real imports.
    """
    checks: List[Dict[str, Any]] = []

    # 1. Python version >= 3.12 check
    py_ver = sys.version_info
    py_ok = (py_ver.major == 3 and py_ver.minor >= 12) or (py_ver.major > 3)
    py_str = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
    checks.append({
        "id": "python_version",
        "name": "Python 3.12+ Runtime",
        "status": py_ok,
        "detail": f"Running Python {py_str} ({sys.executable})" if py_ok else f"Running Python {py_str} (Python 3.12 or higher required)",
        "required": True,
        "upstream_url": UPSTREAM_LINKS["python"] if not py_ok else None,
        "package_name": None
    })

    # 2. SQLite3 engine check
    sqlite_ok = False
    sqlite_detail = ""
    try:
        import sqlite3
        sqlite_ok = True
        sqlite_detail = f"SQLite3 module available (v{sqlite3.sqlite_version})"
    except Exception as e:
        sqlite_detail = f"SQLite3 unavailable: {e}"
    checks.append({
        "id": "sqlite_driver",
        "name": "SQLite3 Database Driver",
        "status": sqlite_ok,
        "detail": sqlite_detail,
        "required": True,
        "upstream_url": None,
        "package_name": None
    })

    # 3. PostgreSQL driver check (psycopg)
    pg_ok = False
    pg_detail = ""
    try:
        import psycopg
        pg_ok = True
        pg_detail = f"psycopg v3 loaded successfully (v{getattr(psycopg, '__version__', '3.x')})"
    except Exception as e:
        pg_detail = f"psycopg driver not installed ({e})"
    checks.append({
        "id": "psycopg",
        "name": "PostgreSQL Driver (psycopg)",
        "status": pg_ok,
        "detail": pg_detail,
        "required": False,  # Optional if running pure SQLite standalone
        "upstream_url": UPSTREAM_LINKS["postgresql"],
        "package_name": "psycopg[binary,pool]"
    })

    # 4. Cryptography / Fernet key check
    crypto_ok = False
    crypto_detail = ""
    try:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        f = Fernet(key)
        sample = b"OpenPOS_Prereq_Check"
        enc = f.encrypt(sample)
        dec = f.decrypt(enc)
        crypto_ok = (dec == sample)
        crypto_detail = "Fernet AES-128-CBC encryption verified"
    except Exception as e:
        crypto_detail = f"cryptography package failed: {e}"
    checks.append({
        "id": "cryptography",
        "name": "Fernet Security Cryptography",
        "status": crypto_ok,
        "detail": crypto_detail,
        "required": True,
        "upstream_url": None,
        "package_name": "cryptography"
    })

    # 5. pywebview desktop container check
    webview_ok = False
    webview_detail = ""
    try:
        import webview
        webview_ok = True
        webview_detail = f"pywebview desktop wrapper available (v{getattr(webview, '__version__', '5.x')})"
    except Exception as e:
        webview_detail = f"pywebview not installed: {e}"
    checks.append({
        "id": "pywebview",
        "name": "Edge/Chromium Desktop Window (pywebview)",
        "status": webview_ok,
        "detail": webview_detail,
        "required": True,
        "upstream_url": None,
        "package_name": "pywebview"
    })

    # 6. pystray system tray supervisor check
    tray_ok = False
    tray_detail = ""
    try:
        import pystray
        tray_ok = True
        tray_detail = "pystray background supervisor available"
    except Exception as e:
        tray_detail = f"pystray not installed: {e}"
    checks.append({
        "id": "pystray",
        "name": "Windows System Tray Supervisor (pystray)",
        "status": tray_ok,
        "detail": tray_detail,
        "required": True,
        "upstream_url": None,
        "package_name": "pystray"
    })

    # 7. Isolated data/ directories write checks
    dirs_to_verify = [
        ("data_root", Config.DATA_DIR),
        ("config_dir", Config.CONFIG_DIR),
        ("db_dir", Config.DB_DIR),
        ("logs_dir", Config.LOGS_DIR),
        ("uploads_dir", Config.UPLOAD_DIR),
        ("cache_dir", Config.CACHE_DIR),
    ]
    all_dirs_ok = True
    dir_details = []
    for d_name, d_path in dirs_to_verify:
        try:
            os.makedirs(d_path, exist_ok=True)
            test_file = os.path.join(d_path, ".write_check")
            with open(test_file, "w", encoding="utf-8") as tf:
                tf.write("ok")
            os.remove(test_file)
        except Exception as e:
            all_dirs_ok = False
            dir_details.append(f"{d_name}: {e}")

    checks.append({
        "id": "data_isolation",
        "name": "Private Data Directories (data/)",
        "status": all_dirs_ok,
        "detail": "All private data/ folders writable" if all_dirs_ok else "; ".join(dir_details),
        "required": True,
        "upstream_url": None,
        "package_name": None
    })

    all_passed = all(c["status"] for c in checks if c["required"])
    has_missing_packages = any(
        not c["status"] and c["package_name"] is not None for c in checks
    )

    return {
        "all_passed": all_passed,
        "has_missing_packages": has_missing_packages,
        "checks": checks
    }


def install_missing_requirements() -> Dict[str, Any]:
    """
    Executes pip install -r requirements.txt using current Python interpreter.
    Provides live progress and output feedback for the Setup Wizard UI.
    """
    req_file = os.path.join(Config.BASE_DIR, "requirements.txt")
    if not os.path.isfile(req_file):
        return {
            "status": "error",
            "message": f"requirements.txt not found at {req_file}"
        }

    cmd = [sys.executable, "-m", "pip", "install", "-r", req_file]
    try:
        logger.info(f"[SETUP] Executing dependency installation: {' '.join(cmd)}")
        proc = subprocess.run(
            cmd,
            cwd=Config.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=180
        )
        if proc.returncode == 0:
            return {
                "status": "success",
                "message": "All dependencies from requirements.txt installed successfully.",
                "output": proc.stdout
            }
        else:
            return {
                "status": "error",
                "message": f"pip install exited with code {proc.returncode}.",
                "output": proc.stderr or proc.stdout
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": "Installation timed out after 180 seconds. Please check your network connection."
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to execute pip install: {e}"
        }
