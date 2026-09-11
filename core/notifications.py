"""
=============================================================================
Open-POS Core Notification Service
=============================================================================
Provides a thread-safe, rolling in-memory notification queue for capturing
subsystem warnings, telemetry alerts, and critical system events.
=============================================================================
"""

import uuid
import threading
from datetime import datetime
from collections import deque

# Valid alert severity levels
VALID_LEVELS = {"INFO", "WARNING", "ERROR", "CRITICAL"}

# Thread-safe in-memory alert queue (maximum 100 rolling entries)
_queue_lock = threading.Lock()
_alerts_queue = deque(maxlen=100)

def add_alert(level: str, message: str, subsystem: str = "CORE") -> dict:
    """
    Appends a new alert to the rolling notification queue.
    """
    clean_level = level.upper().strip() if level else "INFO"
    if clean_level not in VALID_LEVELS:
        clean_level = "INFO"

    clean_subsystem = subsystem.upper().strip() if subsystem else "CORE"

    alert_item = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "level": clean_level,
        "subsystem": clean_subsystem,
        "message": str(message).strip(),
        "read": False
    }

    with _queue_lock:
        _alerts_queue.appendleft(alert_item)

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

# Seed initial boot alert
add_alert("INFO", "Open-POS Engine v1.0.2 initialized and running normally.", "CORE")
