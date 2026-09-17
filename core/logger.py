"""
=============================================================================
Open-POS Universal Centralized Logging Pipeline
=============================================================================
Centralizes logging using Python's standard logging library with rotating file
handlers targeting:
  - data/logs/openpos_system.log (5MB, 5 rolling backups)
  - data/logs/openpos_addons.log (5MB, 5 rolling backups)

Provides global exception hooks (sys.excepthook, threading.excepthook) and
structured log parsing for System Manager telemetry.
=============================================================================
"""

import os
import sys
import re
import logging
import threading
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path

from core.config import Config

LOGS_DIR = Path(getattr(Config, 'LOGS_DIR', os.path.join(Config.DATA_DIR, 'logs')))
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_LOG = LOGS_DIR / "openpos_system.log"
ADDONS_LOG = LOGS_DIR / "openpos_addons.log"
LOG_FILE_PATH = str(SYSTEM_LOG)

# Formatter with precise ISO timestamps, level, module name, and line tracking
FORMATTER = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

_system_logger = None
_addons_logger = None


def setup_system_logger():
    """
    Initializes root OpenPOS system logger and dedicated addons logger
    with rotating file handlers and console output.
    """
    global _system_logger, _addons_logger

    if _system_logger is not None and _addons_logger is not None:
        return _system_logger, _addons_logger

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Root OpenPOS System Logger
    root_logger = logging.getLogger("openpos")
    root_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if already initialized
    if not root_logger.handlers:
        sys_handler = RotatingFileHandler(
            str(SYSTEM_LOG),
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=5,
            encoding="utf-8"
        )
        sys_handler.setFormatter(FORMATTER)
        root_logger.addHandler(sys_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(FORMATTER)
        root_logger.addHandler(console_handler)

    # 2. Addons Dedicated Logger
    addons_logger = logging.getLogger("openpos.addons")
    addons_logger.setLevel(logging.INFO)

    if not addons_logger.handlers:
        addons_handler = RotatingFileHandler(
            str(ADDONS_LOG),
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=5,
            encoding="utf-8"
        )
        addons_handler.setFormatter(FORMATTER)
        addons_logger.addHandler(addons_handler)
        # Prevent double logging to root openpos handlers if propagated
        addons_logger.propagate = True

    _system_logger = root_logger
    _addons_logger = addons_logger
    return _system_logger, _addons_logger


logger, addon_logger = setup_system_logger()


def get_system_logger():
    """Singleton getter returning the root system logger."""
    global _system_logger
    if _system_logger is None:
        setup_system_logger()
    return _system_logger


def get_addon_logger():
    """Singleton getter returning the addons dedicated logger."""
    global _addons_logger
    if _addons_logger is None:
        setup_system_logger()
    return _addons_logger


def install_global_excepthooks():
    """
    Hooks into Python's global exception pipelines (sys.excepthook and
    threading.excepthook) to guarantee uncaught errors and full stack traces
    are safely captured into data/logs/openpos_system.log.
    """
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Uncaught Global Exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

    if hasattr(threading, 'excepthook'):
        def handle_thread_exception(args):
            if issubclass(args.exc_type, KeyboardInterrupt):
                return
            t_name = getattr(args.thread, 'name', 'WorkerThread')
            logger.critical(f"Uncaught Thread Exception in {t_name}", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

        threading.excepthook = handle_thread_exception


def log_event(level: str, message: str, subsystem: str = "CORE"):
    """
    Structured logging helper maintaining backward compatibility across
    setup wizard, database migrators, and notification subsystems.
    """
    log = get_system_logger()
    lvl = getattr(logging, str(level).upper(), logging.INFO)
    log.log(lvl, f"[{subsystem.upper()}] {message}")


def _parse_log_line(line: str, default_subsystem: str = "CORE") -> dict:
    line = line.strip()
    # 1. New Format: [%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s
    # Example: [2026-09-17 15:30:00] [INFO] [openpos:45]: [CORE] Message
    match_new = re.match(r'^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\]\s+\[([A-Z]+)\]\s+\[(.*?)\]:\s*(.*)$', line)
    if match_new:
        dt, lvl, mod, msg = match_new.groups()
        # Check if msg begins with [SUBSYSTEM]
        sub_match = re.match(r'^\[([A-Za-z0-9_\-]+)\]\s*(.*)$', msg)
        if sub_match:
            sub = sub_match.group(1)
            msg = sub_match.group(2)
        else:
            sub = default_subsystem
        return {
            "timestamp": dt,
            "subsystem": sub,
            "level": lvl,
            "message": msg,
            "source": mod
        }

    # 2. Historical Format: YYYY-MM-DD HH:MM:SS [SUBSYSTEM] LEVEL - Message
    match_old = re.match(r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(.*?)\]\s+(\w+)\s+-\s+(.*)$', line)
    if match_old:
        dt, sub, lvl, msg = match_old.groups()
        return {
            "timestamp": dt,
            "subsystem": sub.strip(),
            "level": lvl.strip(),
            "message": msg.strip(),
            "source": "openpos"
        }

    # 3. Fallback unparsed line (e.g. raw traceback lines)
    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "subsystem": default_subsystem,
        "level": "INFO",
        "message": line,
        "source": "raw"
    }


def read_system_logs(limit: int = 250) -> list:
    """
    Reads structured log records from data/logs/openpos_system.log in reverse chronological order.
    """
    logs = []
    if not SYSTEM_LOG.is_file():
        return logs

    try:
        with open(SYSTEM_LOG, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        for line in reversed(lines[-limit:]):
            if not line.strip():
                continue
            logs.append(_parse_log_line(line, default_subsystem="CORE"))
    except Exception as err:
        logging.warning(f"Error reading system logs: {err}")

    return logs


def read_addon_logs(limit: int = 250) -> list:
    """
    Reads structured log records from data/logs/openpos_addons.log in reverse chronological order.
    """
    logs = []
    if not ADDONS_LOG.is_file():
        return logs

    try:
        with open(ADDONS_LOG, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        for line in reversed(lines[-limit:]):
            if not line.strip():
                continue
            logs.append(_parse_log_line(line, default_subsystem="ADDONS"))
    except Exception as err:
        logging.warning(f"Error reading addon logs: {err}")

    return logs


# Baseline init marker
if not SYSTEM_LOG.is_file() or SYSTEM_LOG.stat().st_size == 0:
    log_event("INFO", f"Open-POS System Logger initialized. Version {Config.VERSION}", "CORE")
    log_event("INFO", f"Logging pipeline active at {SYSTEM_LOG} and {ADDONS_LOG}", "CORE")
