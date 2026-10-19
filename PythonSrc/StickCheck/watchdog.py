"""
systemd watchdog support.

The service unit sets WatchdogSec=60, so systemd kills and restarts the
process if it does not send WATCHDOG=1 at least that often. This helper owns
a background thread that pings every `interval` seconds for the whole life of
the process, regardless of which mode (normal, no-WiFi wait, pairing) the
main thread is in.
"""

import logging
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

try:
    import sdnotify
    WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on environment
    sdnotify = None
    WATCHDOG_AVAILABLE = False
    log.debug("sdnotify not available - watchdog disabled")


class SystemdWatchdog:
    def __init__(self, interval: float = 20.0):
        self.interval = interval
        self._notifier = sdnotify.SystemdNotifier() if WATCHDOG_AVAILABLE else None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False

    def _notify(self, state: str) -> None:
        if not self._notifier:
            return
        try:
            self._notifier.notify(state)
        except Exception as e:  # never let a notify failure take the service down
            log.debug(f"sd_notify failed: {e}")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._notify("WATCHDOG=1")
            self._stop_event.wait(self.interval)

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop_event.clear()
        self._notify("READY=1")
        self._thread = threading.Thread(target=self._loop, daemon=True, name="SystemdWatchdog")
        self._thread.start()
        if self._notifier:
            log.info(f"Systemd watchdog started (ping every {self.interval:.0f}s)")

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._notify("STOPPING=1")
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def set_status(self, text: str) -> None:
        """Publish a short status line visible in `systemctl status`."""
        self._notify(f"STATUS={text}")

    def is_running(self) -> bool:
        return self._started
