import os
import shutil
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_DIR = os.path.join(DATA_DIR, 'db')
CACHE_DIR = os.path.join(DATA_DIR, 'cache')
UPLOAD_DIR = os.path.join(DATA_DIR, 'uploads')
LOGS_DIR = os.path.join(DATA_DIR, 'logs')
CUSTOM_ADDONS_DIR = os.path.join(DATA_DIR, 'custom_addons')
CONFIG_DIR = os.path.join(DATA_DIR, 'config')

# Priority: Load environment variables from data/config/.env first, falling back to root .env
env_path = os.path.join(CONFIG_DIR, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv(os.path.join(BASE_DIR, '.env'))

# Automatically ensure private data directories exist on startup
for _directory in (DATA_DIR, DB_DIR, CACHE_DIR, UPLOAD_DIR, LOGS_DIR, CUSTOM_ADDONS_DIR, CONFIG_DIR):
    os.makedirs(_directory, exist_ok=True)

class Config:
    VERSION = "v1.0.4"
    SECRET_KEY = os.environ.get('SECRET_KEY', os.urandom(24).hex())
    FERNET_KEY = os.environ.get('FERNET_KEY', '')
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 5000))

    # Isolated Private Data Paths
    BASE_DIR = BASE_DIR
    DATA_DIR = DATA_DIR
    DB_DIR = DB_DIR
    CACHE_DIR = CACHE_DIR
    UPLOAD_DIR = UPLOAD_DIR
    LOGS_DIR = LOGS_DIR
    CUSTOM_ADDONS_DIR = CUSTOM_ADDONS_DIR
    CONFIG_DIR = CONFIG_DIR

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