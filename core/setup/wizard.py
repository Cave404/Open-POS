"""
=============================================================================
Open-POS First-Run Setup Engine & Hardware/Crypto Initialization
=============================================================================
Automated onboarding wizard backend logic:
  1. System prerequisite validation (Python 3.12+, DB drivers, data isolation).
  2. Symmetric 32-byte Fernet key & Flask Secret key generation.
  3. Emergency System Decryption & Recovery Token generation.
  4. Encrypted configuration persistence to data/config/.env.
  5. Password hashing and security policy persistence to data/config/manager_auth.json.
  6. Database initialization and roundtrip verification.
  7. Permanent one-way lockout via data/config/.setup_complete.
=============================================================================
"""

import os
import sys
import json
import secrets
import hashlib
from datetime import datetime
from cryptography.fernet import Fernet
from dotenv import load_dotenv

from core.config import Config
from core.logger import log_event
from core.setup.shortcut import create_desktop_shortcut

SETUP_MARKER_PATH = os.path.join(Config.CONFIG_DIR, '.setup_complete')
AUTH_CONFIG_PATH = os.path.join(Config.CONFIG_DIR, 'manager_auth.json')
PIN_HASH_PATH = os.path.join(Config.CONFIG_DIR, 'admin_pin.hash')
ENV_CONFIG_PATH = os.path.join(Config.CONFIG_DIR, '.env')

def get_pin_hash_path() -> str:
    """Returns active admin_pin.hash path, dynamically aligned with AUTH_CONFIG_PATH directory."""
    default_path = os.path.join(Config.CONFIG_DIR, 'admin_pin.hash')
    if PIN_HASH_PATH != default_path:
        return PIN_HASH_PATH
    if AUTH_CONFIG_PATH and os.path.dirname(AUTH_CONFIG_PATH):
        return os.path.join(os.path.dirname(AUTH_CONFIG_PATH), 'admin_pin.hash')
    return PIN_HASH_PATH

def is_setup_complete() -> bool:
    """Checks whether the first-run onboarding wizard has completed."""
    if not os.path.isfile(SETUP_MARKER_PATH):
        return False
    # Check if admin_pin.hash or manager_auth.json exists
    active_pin = get_pin_hash_path()
    return os.path.isfile(active_pin) or os.path.isfile(AUTH_CONFIG_PATH)

def check_existing_installation() -> dict:
    """
    Checks whether an existing store configuration or credential set is registered,
    even if .setup_complete was removed or deleted.
    Inspects data/config/manager_auth.json, data/config/admin_pin.hash, and data/config/.env.
    """
    has_auth = False
    has_password = False
    has_keys = False

    active_pin = get_pin_hash_path()
    if os.path.isfile(active_pin):
        try:
            with open(active_pin, 'r', encoding='utf-8') as f:
                if f.read().strip():
                    has_auth = True
                    has_password = True
        except Exception:
            pass


    if os.path.isfile(AUTH_CONFIG_PATH):
        try:
            with open(AUTH_CONFIG_PATH, 'r', encoding='utf-8') as f:
                auth = json.load(f)
                if auth.get("password_hash"):
                    has_auth = True
                    has_password = True
        except Exception:
            pass

    if os.path.isfile(ENV_CONFIG_PATH):
        try:
            with open(ENV_CONFIG_PATH, 'r', encoding='utf-8') as f:
                content = f.read()
                if "FERNET_KEY=" in content:
                    for line in content.splitlines():
                        line_s = line.strip()
                        if line_s.startswith("FERNET_KEY=") and len(line_s.split("=", 1)[1].strip()) > 8:
                            has_keys = True
                            break
        except Exception:
            pass

    exists = has_auth or has_keys
    return {
        "exists": exists,
        "has_password": has_password,
        "has_keys": has_keys
    }


def mark_setup_complete(metadata: dict = None) -> bool:
    """
    Creates data/config/.setup_complete, permanently locking out the setup wizard.
    Also ensures Windows Desktop shortcut 'OpenPOS.lnk' is generated.
    """
    try:
        os.makedirs(Config.CONFIG_DIR, exist_ok=True)
        now_str = datetime.now().isoformat()
        sig = hashlib.sha256(f"OPENPOS_INSTALLED_{now_str}".encode('utf-8')).hexdigest()
        payload = {
            "completed_at": now_str,
            "version": Config.VERSION,
            "signature": sig,
            "metadata": metadata or {}
        }
        with open(SETUP_MARKER_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)

        # Ensure admin_pin.hash marker exists on completion
        active_pin = get_pin_hash_path()
        if not os.path.isfile(active_pin):
            try:
                with open(active_pin, 'w', encoding='utf-8') as pf:
                    pf.write(sig)
            except Exception:
                pass


        # Generate automated desktop shortcut on completion
        try:
            create_desktop_shortcut(Config.BASE_DIR)
        except Exception as sc_err:
            logger.warning(f"Could not create desktop shortcut during completion: {sc_err}")

        log_event("INFO", f"First-run setup completed and locked permanently. Version: {Config.VERSION}", "SETUP")
        return True
    except Exception as e:
        log_event("ERROR", f"Failed to mark setup complete: {e}", "SETUP")
        return False

def check_prerequisites() -> dict:
    """
    Validates live runtime environment prerequisites for Open-POS:
    Python >= 3.12, SQLite3, psycopg, cryptography, pywebview, pystray,
    and private data/ directory write permissions.
    """
    from core.setup.checks import run_prerequisite_checks
    return run_prerequisite_checks()

def generate_crypto_keys() -> dict:
    """
    Generates cryptographic materials for initial system deployment:
      - Fernet symmetric encryption key (32 bytes url-safe base64)
      - Flask application SECRET_KEY (32 bytes hex)
      - Emergency System Decryption & Recovery Token
    """
    fernet_key = Fernet.generate_key().decode('utf-8')
    secret_key = secrets.token_hex(32)
    # Formatted high-entropy emergency token: OPOS-REC-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX
    token_parts = [secrets.token_hex(2).upper() + secrets.token_hex(2).upper() for _ in range(6)]
    recovery_token = "OPOS-REC-" + "-".join(token_parts)

    return {
        "fernet_key": fernet_key,
        "secret_key": secret_key,
        "recovery_token": recovery_token
    }

def test_crypto_roundtrip(fernet_key: str) -> dict:
    """Verifies that the provided Fernet key can encrypt and decrypt payload."""
    try:
        f = Fernet(fernet_key.encode('utf-8'))
        sample = f"OpenPOS_Test_Payload_{secrets.token_hex(8)}"
        ciphertext = f.encrypt(sample.encode('utf-8'))
        decrypted = f.decrypt(ciphertext).decode('utf-8')
        return {
            "success": (decrypted == sample),
            "sample_len": len(ciphertext)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def save_setup_configuration(data: dict) -> dict:
    """
    Persists first-run configuration parameters into:
      1. data/config/.env (SECRET_KEY, FERNET_KEY, DB settings)
      2. data/config/manager_auth.json (Salted password hash)
      3. Database settings table (Store name, legal name, logo, location)
      4. Verifies database roundtrip test
    """
    try:
        os.makedirs(Config.CONFIG_DIR, exist_ok=True)
        os.makedirs(Config.DB_DIR, exist_ok=True)

        store_name = str(data.get('store_name', '')).strip() or "Main Street Games"
        store_legal_name = str(data.get('store_legal_name', '')).strip()
        store_location = str(data.get('store_location', '')).strip()
        store_logo_url = str(data.get('store_logo_url', '')).strip()

        admin_password = str(data.get('admin_password', '')).strip()
        require_password = bool(data.get('require_password', False))

        db_engine = str(data.get('db_engine', 'sqlite')).strip().lower()
        db_host = str(data.get('db_host', '127.0.0.1')).strip()
        db_port = str(data.get('db_port', '5432')).strip()
        db_name = str(data.get('db_name', 'pos_store.db')).strip()
        db_user = str(data.get('db_user', 'postgres')).strip()
        db_password = str(data.get('db_password', '')).strip()

        # Keys
        crypto = generate_crypto_keys()
        fernet_key = data.get('fernet_key') or crypto['fernet_key']
        secret_key = data.get('secret_key') or crypto['secret_key']
        recovery_token = data.get('recovery_token') or crypto['recovery_token']

        # Verify Fernet encryption
        roundtrip_res = test_crypto_roundtrip(fernet_key)
        if not roundtrip_res.get("success"):
            return {
                "status": "error",
                "message": f"Cryptographic roundtrip verification failed: {roundtrip_res.get('error')}"
            }

        # 1. Write data/config/.env
        env_lines = [
            f"# =============================================================================",
            f"# Open-POS System Configuration ({Config.VERSION})",
            f"# Auto-generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# =============================================================================",
            f"FLASK_ENV=production",
            f"PORT=5000",
            f"SECRET_KEY={secret_key}",
            f"FERNET_KEY={fernet_key}",
            f"DB_ENGINE={db_engine}",
        ]
        if db_engine in ('postgres', 'postgresql'):
            env_lines.extend([
                f"DB_HOST={db_host}",
                f"DB_PORT={db_port}",
                f"DB_NAME={db_name}",
                f"DB_USER={db_user}",
                f"DB_PASSWORD={db_password}",
            ])
        else:
            env_lines.append(f"DB_NAME=pos_store.db")

        # Add Recovery Token Hash for safe verification
        rec_salt = secrets.token_hex(16)
        rec_hash = hashlib.sha256((rec_salt + recovery_token).encode('utf-8')).hexdigest()
        env_lines.append(f"RECOVERY_TOKEN_SALT={rec_salt}")
        env_lines.append(f"RECOVERY_TOKEN_HASH={rec_hash}")

        with open(ENV_CONFIG_PATH, 'w', encoding='utf-8') as f:
            f.write("\n".join(env_lines) + "\n")

        # Load generated env into runtime
        load_dotenv(ENV_CONFIG_PATH, override=True)

        # 2. Write data/config/manager_auth.json
        auth_data = {
            "require_password": require_password,
            "password_hash": "",
            "salt": "",
            "protected_sections": ["branding", "database", "admin"],
            "bypass_manager_on_boot": False
        }
        if admin_password:
            pwd_salt = secrets.token_hex(16)
            pwd_hash = hashlib.sha256((pwd_salt + admin_password).encode('utf-8')).hexdigest()
            auth_data["password_hash"] = pwd_hash
            auth_data["salt"] = pwd_salt

        with open(AUTH_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(auth_data, f, indent=2)

        # Ensure admin_pin.hash marker is persisted
        try:
            pin_to_hash = admin_password if admin_password else "openpos_admin"
            active_pin = get_pin_hash_path()
            with open(active_pin, 'w', encoding='utf-8') as pf:
                pf.write(hashlib.sha256(pin_to_hash.encode('utf-8')).hexdigest())
        except Exception:
            pass


        # 3. Database initialization & seed
        from core.db import init_db
        from core.settings import set_setting, get_setting

        init_db()
        set_setting('store_name', store_name)
        if store_legal_name:
            set_setting('store_legal_name', store_legal_name)
        if store_location:
            set_setting('store_location', store_location)
        if store_logo_url:
            set_setting('store_logo_url', store_logo_url)

        # Verify DB roundtrip
        retrieved_store = get_setting('store_name', '')
        if retrieved_store != store_name:
            return {
                "status": "error",
                "message": "Database write roundtrip test failed to retrieve saved store name."
            }

        log_event("INFO", f"First-run setup successfully saved settings for store '{store_name}'.", "SETUP")

        return {
            "status": "success",
            "store_name": store_name,
            "fernet_key": fernet_key,
            "secret_key": secret_key,
            "recovery_token": recovery_token,
            "roundtrip_verified": True
        }

    except Exception as e:
        log_event("ERROR", f"Setup configuration failed: {e}", "SETUP")
        return {
            "status": "error",
            "message": str(e)
        }

def get_recovery_key_text(store_name: str, recovery_token: str, fernet_key: str = None) -> str:
    """Formats the plain text content for OpenPOS_Emergency_Recovery_Key.txt."""
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""=============================================================================
OPENPOS EMERGENCY SYSTEM DECRYPTION & RECOVERY CREDENTIAL SHEET
=============================================================================
Store Name:     {store_name}
Created At:     {created_at}
System Version: {Config.VERSION}
=============================================================================

MASTER RECOVERY TOKEN:
{recovery_token}

SYMMETRIC FERNET ENCRYPTION KEY:
{fernet_key or "Configured in data/config/.env"}

=============================================================================
WARNING & SECURITY ADVISORY:
- This recovery token is required to decrypt sensitive store data, databases,
  and restore system access if your administrative password/PIN is lost.
- Store this document in a secure location (e.g., printed on paper in a locked
  fireproof safe or on an encrypted offline USB drive).
- OpenPOS staff and developers NEVER have access to this key and CANNOT
  restore your encrypted database if this key is lost.
=============================================================================
"""
