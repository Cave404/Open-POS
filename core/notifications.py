import os
import re
import uuid
import threading
from datetime import datetime
from collections import deque
from core.config import Config
from core.logger import log_event, read_system_logs

# Valid alert severity levels
VALID_LEVELS = {"INFO", "WARNING", "ERROR", "CRITICAL"}

# Thread-safe in-memory alert queue (maximum 100 rolling entries)
_queue_lock = threading.Lock()
_alerts_queue = deque(maxlen=100)

def add_alert(level: str, message: str, subsystem: str = "CORE") -> dict:
    """
    Appends a new alert to the rolling notification queue and writes to disk log.
    """
    clean_level = level.upper().strip() if level else "INFO"
    if clean_level not in VALID_LEVELS:
        clean_level = "INFO"

    clean_subsystem = subsystem.upper().strip() if subsystem else "CORE"
    time_str = datetime.now().strftime("%H:%M:%S")

    alert_item = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": time_str,
        "level": clean_level,
        "subsystem": clean_subsystem,
        "message": str(message).strip(),
        "read": False
    }

    with _queue_lock:
        _alerts_queue.appendleft(alert_item)

    log_event(clean_level, str(message).strip(), clean_subsystem)

    return alert_item

def get_alerts(limit: int = 20) -> list:
    """
    Retrieves the most recent alerts up to limit.
    """
    with _queue_lock:
        items = list(_alerts_queue)
    return items[:limit]

def get_unread_count() -> int:
    """
    Counts alerts that have not been cleared or marked read.
    """
    with _queue_lock:
        return sum(1 for a in _alerts_queue if not a.get("read", False))

def clear_alerts() -> None:
    """
    Clears all active notifications in the queue.
    """
    with _queue_lock:
        _alerts_queue.clear()

def get_system_logs(limit: int = 100) -> list:
    """
    Retrieves recent logs formatted as structured records from data/logs/openpos_system.log
    falling back to in-memory notifications if file is empty.
    """
    logs = read_system_logs(limit=limit)

    if not logs:
        # Fallback to in-memory alerts
        with _queue_lock:
            for item in _alerts_queue:
                logs.append({
                    "timestamp": item["timestamp"],
                    "subsystem": item["subsystem"],
                    "level": item["level"],
                    "message": item["message"]
                })

    return logs

# Ensure initial boot alert exists
add_alert("INFO", f"Open-POS Engine {Config.VERSION} initialized and running normally.", "CORE")
add_alert("INFO", "Telemetry collector mounted at data/logs/openpos_system.log", "CORE")
add_alert("INFO", "USB NFC polling worker registered on port COM3", "NFC")
add_alert("INFO", "Price Engine background evaluator initialized.", "PRICE_ENGINE")


