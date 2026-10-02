import os
import sys
import shutil
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

# 1. Read-Only Application Assets (Templates, Static CSS/JS, Migration SQL) vs Mutable Runtime Store Data
if getattr(sys, "frozen", False):
    # PyInstaller extracts/bundles assets inside _MEIPASS
    BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Development mode from source
    BUNDLE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    BASE_DIR = BUNDLE_DIR

# 2. Mutable Store Data Directory (Databases, Configs, Logs, Uploads)
# Stored alongside the executable to ensure data persistence across app updates
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_DIR = os.path.join(DATA_DIR, 'db')
CACHE_DIR = os.path.join(DATA_DIR, 'cache')
UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads')
LOGS_DIR = os.path.join(DATA_DIR, 'logs')
CUSTOM_ADDONS_DIR = os.path.join(DATA_DIR, 'custom_addons')
CONFIG_DIR = os.path.join(DATA_DIR, 'config')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
ADDONS_CONFIG_DIR = os.path.join(CONFIG_DIR, 'addons')

# Priority: Load environment variables from data/config/.env first, falling back to root .env
env_path = os.path.join(CONFIG_DIR, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv(os.path.join(BASE_DIR, '.env'))

REQUIRED_DATA_DIRS = [
    "data/config",
    "data/config/addons",
    "data/db",
    "data/logs",
    "data/cache",
    "data/custom_addons",
    "data/uploads",
    "data/backups"
]

# Automatically ensure private data directories exist on startup
for folder in REQUIRED_DATA_DIRS:
    os.makedirs(os.path.join(BASE_DIR, folder), exist_ok=True)

# Ensure persistent SECRET_KEY saved in data/config/.env
persistent_secret = os.environ.get('SECRET_KEY')
if not persistent_secret:
    import secrets
    persistent_secret = secrets.token_hex(32)
    config_env_file = os.path.join(CONFIG_DIR, '.env')
    try:
        content = ""
        if os.path.isfile(config_env_file):
            with open(config_env_file, 'r', encoding='utf-8') as ef:
                content = ef.read()
        if 'SECRET_KEY=' not in content:
            with open(config_env_file, 'a+', encoding='utf-8') as ef:
                if content and not content.endswith('\n'):
                    ef.write('\n')
                ef.write(f"SECRET_KEY={persistent_secret}\n")
    except Exception:
        pass
    os.environ['SECRET_KEY'] = persistent_secret

class Config:
    VERSION = "1.0.99"
    DEFAULT_PORT = 5050
    ACTIVE_PORT = None

    # 1. Read-Only Application Assets (Templates, Static CSS/JS, Migration SQL)
    BUNDLE_DIR = BUNDLE_DIR
    BASE_DIR = BASE_DIR

    # 2. Mutable Store Data Directory (Databases, Configs, Logs, Uploads)
    DATA_DIR = DATA_DIR
    DB_DIR = DB_DIR
    CACHE_DIR = CACHE_DIR
    UPLOAD_DIR = UPLOAD_DIR
    LOGS_DIR = LOGS_DIR
    CUSTOM_ADDONS_DIR = CUSTOM_ADDONS_DIR
    CONFIG_DIR = CONFIG_DIR
    ADDONS_CONFIG_DIR = ADDONS_CONFIG_DIR
    BACKUP_DIR = BACKUP_DIR
    REQUIRED_DATA_DIRS = REQUIRED_DATA_DIRS

    PORT = int(os.environ.get('PORT', 5050))
    DEBUG = False

    @classmethod
    def get_configured_port(cls) -> int:
        """Reads server_port from store_settings.json or returns DEFAULT_PORT."""
        settings_file = os.path.join(cls.DATA_DIR, "config", "store_settings.json")
        if os.path.exists(settings_file):
            try:
                import json
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return int(data.get("server_port", cls.DEFAULT_PORT))
            except Exception:
                pass
        return cls.DEFAULT_PORT

    @classmethod
    def determine_runtime_port(cls) -> int:
        """Resolves preferred port with collision fallback and sets ACTIVE_PORT and PORT."""
        preferred = cls.get_configured_port()
        from core.network import resolve_server_port
        cls.ACTIVE_PORT = resolve_server_port(preferred_port=preferred)
        cls.PORT = cls.ACTIVE_PORT
        return cls.ACTIVE_PORT

    @classmethod
    def init_directories(cls):
        """Ensures all runtime data folders exist on startup."""
        for sub in ["db", "config", "logs", "custom_addons", "backups", "uploads", "cache"]:
            os.makedirs(os.path.join(cls.DATA_DIR, sub), exist_ok=True)

    SECRET_KEY = persistent_secret or os.environ.get('SECRET_KEY', 'default_openpos_secret_key')
    FERNET_KEY = os.environ.get('FERNET_KEY', '')
    HOST = os.environ.get('HOST', '0.0.0.0')

    # Database Settings
    DB_ENGINE = os.environ.get('DB_ENGINE', 'sqlite').lower()
    DB_NAME = os.environ.get('DB_NAME', 'pos_store.db')
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = int(os.environ.get('DB_PORT', 5432))
    DB_USER = os.environ.get('DB_USER', 'postgres')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')

    # SQLite Database Path Resolution
    if DB_NAME == ':memory:' or os.path.isabs(DB_NAME):
        DB_PATH = DB_NAME
    else:
        DB_PATH = os.path.join(DB_DIR, DB_NAME)

    # Business Logic Defaults
    STORE_NAME = os.environ.get('STORE_NAME', 'Open-POS System')
    STORE_LEGAL_ENTITY = os.environ.get('STORE_LEGAL_ENTITY', 'Open-POS Retail LLC')
    STORE_LOCATION = os.environ.get('STORE_LOCATION', 'Local Network')
    DAILY_TRADE_LIMIT = int(os.environ.get('DAILY_TRADE_LIMIT', 10))
    CASH_PAYOUT_PERCENT = float(os.environ.get('CASH_PAYOUT_PERCENT', 60.0))
    CREDIT_PAYOUT_PERCENT = float(os.environ.get('CREDIT_PAYOUT_PERCENT', 80.0))

# Migration & cleanup check: relocate stray root pos_store.db into data/db/pos_store.db
_legacy_root_db = os.path.join(BASE_DIR, 'pos_store.db')
_target_data_db = os.path.join(DB_DIR, 'pos_store.db')
if os.path.isfile(_legacy_root_db):
    if not os.path.isfile(_target_data_db):
        try:
            shutil.copy2(_legacy_root_db, _target_data_db)
        except Exception:
            pass
    try:
        os.remove(_legacy_root_db)
    except Exception:
        pass