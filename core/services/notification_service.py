"""
Open-POS Universal Notification Service
Routes actionable warnings, operational errors, and system alerts to the UI notification drawer
while strictly filtering out routine INFO telemetry.
"""

from core.logger import NotificationLogHandler
from core.notifications import (
    add_system_notification,
    add_alert,
    get_alerts,
    get_unread_count,
    clear_alerts,
    get_system_logs,
)

__all__ = [
    "NotificationLogHandler",
    "add_system_notification",
    "add_alert",
    "get_alerts",
    "get_unread_count",
    "clear_alerts",
    "get_system_logs",
]
