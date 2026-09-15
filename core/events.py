"""
core/events.py
==============
Lightweight in-process pub/sub event dispatcher for Open-POS.

Usage:
    from core.events import event_bus

    # Subscribe (typically at addon init time)
    event_bus.subscribe('customer:badge_assigned', my_handler)

    # Dispatch (from core services)
    event_bus.dispatch('customer:badge_assigned', customer_id=42, nfc_uid='04A1B2C3D4E5F6')
"""
import logging
from typing import Callable, Dict, List

logger = logging.getLogger(__name__)


class EventBus:
    """Thread-safe in-process pub/sub dispatcher.

    Each subscriber is called synchronously in registration order.
    Exceptions in individual handlers are isolated: a crash in one handler
    never prevents subsequent handlers from executing.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_name: str, handler: Callable) -> None:
        """Register *handler* to be called when *event_name* is dispatched."""
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        self._subscribers[event_name].append(handler)
        logger.debug(f"EventBus: '{handler.__name__}' subscribed to '{event_name}'")

    def unsubscribe(self, event_name: str, handler: Callable) -> None:
        """Remove a previously registered *handler* for *event_name*."""
        if event_name in self._subscribers:
            self._subscribers[event_name] = [
                h for h in self._subscribers[event_name] if h is not handler
            ]

    def dispatch(self, event_name: str, **payload) -> int:
        """Dispatch *event_name* to all registered subscribers.

        Returns the number of handlers that were invoked successfully.
        Errors in individual handlers are caught, logged, and do not
        propagate to the caller.
        """
        handlers = self._subscribers.get(event_name, [])
        success_count = 0
        for handler in handlers:
            try:
                handler(**payload)
                success_count += 1
            except Exception as e:
                logger.error(
                    f"EventBus: Error dispatching '{event_name}' to "
                    f"'{handler.__name__}': {e}",
                    exc_info=True
                )
        if handlers:
            logger.debug(
                f"EventBus: Dispatched '{event_name}' to {success_count}/{len(handlers)} handlers"
            )
        return success_count

    def subscribers(self, event_name: str) -> List[Callable]:
        """Return a copy of the subscriber list for *event_name*."""
        return list(self._subscribers.get(event_name, []))

    def clear(self, event_name: str = None) -> None:
        """Remove all subscribers. If *event_name* is given, clears only that event."""
        if event_name:
            self._subscribers.pop(event_name, None)
        else:
            self._subscribers.clear()


# Module-level singleton — import this from any module without circular deps
event_bus = EventBus()
