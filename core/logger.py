"""
=============================================================================
Open-POS Unified System Logging Pipeline
=============================================================================
Configures Python standard logging with a RotatingFileHandler targeting
data/logs/openpos_system.log (5MB max size, 3 rolling backups).
Provides structured logging helpers for core, hardware, and peripheral subsystems.
=============================================================================
"""

import os
import re
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from core.config import Config

LOG_FILE_PATH = os.path.join(Config.LOGS_DIR, 'openpos_system.log')

class SubsystemFormatter(logging.Formatter):
    """Formats log records as: YYYY-MM-DD HH:MM:SS [SUBSYSTEM] LEVEL - Message"""
    def format(self, record):
        dt = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        subsystem = getattr(record, 'subsystem', 'CORE')
        level = record.levelname
        msg = record.getMessage()
        return f"{dt} [{subsystem}] {level} - {msg}"

_logger = None

def get_system_logger():
    """Initializes and returns the singleton system logger."""
    global _logger
    if _logger is not None:
        return _logger

    os.makedirs(Config.LOGS_DIR, exist_ok=True)

    logger = logging.getLogger("OpenPOS")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if already registered
    if not logger.handlers:
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setFormatter(SubsystemFormatter())
        logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(SubsystemFormatter())
        logger.addHandler(console_handler)

    _logger = logger
    return _logger

def log_event(level: str, message: str, subsystem: str = "CORE"):
    """
    Logs an event into data/logs/openpos_system.log with subsystem attribution.
    """
    logger = get_system_logger()
    lvl = getattr(logging, level.upper(), logging.INFO)
    extra = {'subsystem': subsystem.upper()}
    logger.log(lvl, message, extra=extra)

def read_system_logs(limit: int = 250) -> list:
    """
    Reads structured log records from data/logs/openpos_system.log in reverse chronological order.
    """
    logs = []
    if not os.path.isfile(LOG_FILE_PATH):
        return logs

    try:
        with open(LOG_FILE_PATH, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        for line in reversed(lines[-limit:]):
            line = line.strip()
            if not line:
                continue
            # Regex: YYYY-MM-DD HH:MM:SS [SUBSYSTEM] LEVEL - Message
            match = re.match(r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(.*?)\]\s+(\w+)\s+-\s+(.*)$', line)
            if match:
                dt, sub, lvl, msg = match.groups()
                logs.append({
                    "timestamp": dt,
                    "subsystem": sub.strip(),
                    "level": lvl.strip(),
                    "message": msg.strip()
                })
            else:
                logs.append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "subsystem": "CORE",
                    "level": "INFO",
                    "message": line
                })
    except Exception as err:
        logging.warning(f"Error reading system logs: {err}")

    return logs

# Initialize baseline logs if file does not exist
if not os.path.isfile(LOG_FILE_PATH) or os.path.getsize(LOG_FILE_PATH) == 0:
    log_event("INFO", f"Open-POS System Logger initialized. Version {Config.VERSION}", "CORE")
    log_event("INFO", "Logging pipeline mounted to data/logs/openpos_system.log", "CORE")
    log_event("INFO", "Subsystem telemetry active: CORE, NFC, PRICE_ENGINE, DISCORD", "CORE")
