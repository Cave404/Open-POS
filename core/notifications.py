import os
import re
import uuid
import threading
from datetime import datetime
from collections import deque
from core.config import Config

# Valid alert severity levels
VALID_LEVELS = {"INFO", "WARNING", "ERROR", "CRITICAL"}

# Thread-safe in-memory alert queue (maximum 100 rolling entries)
_queue_lock = threading.Lock()
_alerts_queue = deque(maxlen=100)

def _log_file_path() -> str:
    return os.path.join(Config.LOGS_DIR, 'open_pos.log')

def _write_log_to_disk(timestamp: str, subsystem: str, level: str, message: str) -> None:
    """Appends structured log trace to data/logs/open_pos.log."""
    try:
        os.makedirs(Config.LOGS_DIR, exist_ok=True)
        log_path = _log_file_path()
        full_dt = datetime.now().strftime("%Y-%m-%d")
        line = f"{full_dt} {timestamp} [{subsystem}] [{level}] {message}\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

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

    _write_log_to_disk(time_str, clean_subsystem, clean_level, str(message).strip())

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
    Retrieves recent logs formatted as structured records from data/logs/open_pos.log
    falling back to in-memory notifications if file is empty.
    """
    log_path = _log_file_path()
    logs = []

    if os.path.isfile(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # Read from end
            for line in reversed(lines[-limit:]):
                line = line.strip()
                if not line:
                    continue
                # Format: YYYY-MM-DD HH:MM:SS [SUBSYSTEM] [LEVEL] Message
                match = re.match(r'^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(.*?)\]\s+\[(.*?)\]\s*(.*)$', line)
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
        except Exception:
            pass

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
if not os.path.isfile(_log_file_path()) or os.path.getsize(_log_file_path()) == 0:
    add_alert("INFO", "Open-POS Engine v1.0.2 initialized and running normally.", "CORE")
    add_alert("INFO", "Telemetry collector mounted at data/logs/open_pos.log", "CORE")
    add_alert("INFO", "USB NFC polling worker registered on port COM3", "NFC")
    add_alert("INFO", "Price Engine background evaluator initialized.", "PRICE_ENGINE")

