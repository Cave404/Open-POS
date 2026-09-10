import os
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

class Config:
    VERSION = "v1.1.0"
    SECRET_KEY = os.environ.get('SECRET_KEY', os.urandom(24).hex())
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 5000))

    # Database Settings
    DB_ENGINE = os.environ.get('DB_ENGINE', 'sqlite').lower()
    DB_NAME = os.environ.get('DB_NAME', 'pos_store.db')
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = int(os.environ.get('DB_PORT', 5432))
    DB_USER = os.environ.get('DB_USER', 'postgres')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')

    # Business Logic Defaults
    STORE_NAME = os.environ.get('STORE_NAME', 'Open-POS System')
    STORE_LEGAL_ENTITY = os.environ.get('STORE_LEGAL_ENTITY', 'Open-POS Retail LLC')
    STORE_LOCATION = os.environ.get('STORE_LOCATION', 'Local Network')
    DAILY_TRADE_LIMIT = int(os.environ.get('DAILY_TRADE_LIMIT', 10))
    CASH_PAYOUT_PERCENT = float(os.environ.get('CASH_PAYOUT_PERCENT', 60.0))
    CREDIT_PAYOUT_PERCENT = float(os.environ.get('CREDIT_PAYOUT_PERCENT', 80.0))