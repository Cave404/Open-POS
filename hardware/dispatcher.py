import queue
import threading
import logging
from typing import Callable, Any

logger = logging.getLogger("openpos.hardware")


class HardwareDispatcher:
    def __init__(self):
        self._task_queue = queue.Queue(maxsize=100)
        self._worker_thread = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True, name="HardwareDispatcherThread")
        self._worker_thread.start()
        logger.info("Hardware worker dispatcher started.")

    def stop(self):
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._task_queue.put(None)
            self._worker_thread.join(timeout=2.0)
        logger.info("Hardware worker dispatcher stopped.")

    def dispatch(self, action_name: str, task_fn: Callable[..., Any], *args, **kwargs):
        try:
            self._task_queue.put_nowait((action_name, task_fn, args, kwargs))
        except queue.Full:
            logger.error(f"Hardware queue full. Dropped action: {action_name}")

    def _process_queue(self):
        while self._running:
            try:
                item = self._task_queue.get(timeout=1.0)
                if item is None:
                    break
                action_name, task_fn, args, kwargs = item
                try:
                    task_fn(*args, **kwargs)
                except Exception as err:
                    logger.error(f"Hardware execution error in '{action_name}': {err}", exc_info=True)
                finally:
                    self._task_queue.task_done()
            except queue.Empty:
                continue


hardware_dispatcher = HardwareDispatcher()
