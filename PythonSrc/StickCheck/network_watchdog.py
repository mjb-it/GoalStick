import json
import logging
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Tuple

from .system_files import atomic_write_text

log = logging.getLogger(__name__)

# Persisted across reboots (lives under /etc/goalstick, which stays writable
# when the read-only overlay is enabled).
DEFAULT_STATE_PATH = Path("/etc/goalstick/network_watchdog.json")


@dataclass
class NetworkWatchdogConfig:
    check_interval: int = 60                 # Seconds between checks
    interface_restart_threshold: int = 5     # Bounce WiFi after this many consecutive failures
    failure_threshold: int = 15              # Reboot after this many consecutive failures
    max_consecutive_reboots: int = 3         # Stop rebooting after this many back-to-back watchdog reboots
    ping_hosts: tuple = ("8.8.8.8", "1.1.1.1")
    ping_timeout: int = 5
    # TCP fallback for networks that block ICMP. The NHL API is what we
    # actually need to reach.
    tcp_hosts: tuple = (("api-web.nhle.com", 443), ("1.1.1.1", 443))
    tcp_timeout: int = 5
    interface: str = "wlan0"
    state_path: Path = field(default_factory=lambda: DEFAULT_STATE_PATH)


class NetworkWatchdog:
    """
    Monitors network connectivity and tries progressively stronger recovery:

    1. After `interface_restart_threshold` consecutive failures, restart the
       WiFi interface.
    2. After `failure_threshold` consecutive failures, reboot - but only if
       fewer than `max_consecutive_reboots` watchdog reboots have happened
       without connectivity being restored in between. This prevents an
       endless reboot loop when the router is simply gone.

    `on_connectivity_change(connected: bool)` is called on transitions so the
    caller can update the status LED.
    """

    def __init__(self, config: NetworkWatchdogConfig = None,
                 on_connectivity_change: Optional[Callable[[bool], None]] = None):
        self.config = config or NetworkWatchdogConfig()
        self._on_change = on_connectivity_change
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consecutive_failures = 0
        self._connected: Optional[bool] = None
        self._interface_restarted = False

    # ------------------------------------------------------------------
    # Connectivity checks
    # ------------------------------------------------------------------

    def _ping(self, host: str) -> bool:
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(self.config.ping_timeout), host],
                capture_output=True,
                text=True,
                timeout=self.config.ping_timeout + 2
            )
            return result.returncode == 0
        except Exception:
            return False

    def _tcp_connect(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=self.config.tcp_timeout):
                return True
        except OSError:
            return False

    def _check_connectivity(self) -> bool:
        """Return True if any ping or TCP probe succeeds."""
        for host in self.config.ping_hosts:
            if self._ping(host):
                return True
        for host, port in self.config.tcp_hosts:
            if self._tcp_connect(host, port):
                return True
        return False

    # ------------------------------------------------------------------
    # Recovery actions
    # ------------------------------------------------------------------

    def _restart_interface(self) -> None:
        iface = self.config.interface
        log.warning(f"Network watchdog: restarting {iface}")
        try:
            if shutil.which("nmcli"):
                subprocess.run(["sudo", "nmcli", "device", "disconnect", iface],
                               capture_output=True, timeout=20)
                time.sleep(2)
                subprocess.run(["sudo", "nmcli", "device", "connect", iface],
                               capture_output=True, timeout=45)
            else:
                subprocess.run(["sudo", "ip", "link", "set", iface, "down"],
                               capture_output=True, timeout=10)
                time.sleep(2)
                subprocess.run(["sudo", "ip", "link", "set", iface, "up"],
                               capture_output=True, timeout=10)
                subprocess.run(["sudo", "wpa_cli", "-i", iface, "reconfigure"],
                               capture_output=True, timeout=10)
        except Exception as e:
            log.error(f"Failed to restart {iface}: {e}")

    def _load_state(self) -> dict:
        try:
            if self.config.state_path.exists():
                data = json.loads(self.config.state_path.read_text())
                if isinstance(data, dict):
                    return data
        except Exception as e:
            log.debug(f"Could not read watchdog state: {e}")
        return {}

    def _save_state(self, state: dict) -> None:
        try:
            atomic_write_text(self.config.state_path, json.dumps(state), mode=0o644)
        except Exception as e:
            log.debug(f"Could not write watchdog state: {e}")

    def _record_connectivity_restored(self) -> None:
        state = self._load_state()
        if state.get("consecutive_reboots"):
            state["consecutive_reboots"] = 0
            self._save_state(state)

    def _reboot_system(self) -> bool:
        """Reboot unless the reboot budget is exhausted. Returns True if a reboot was issued."""
        state = self._load_state()
        reboots = int(state.get("consecutive_reboots", 0) or 0)
        if reboots >= self.config.max_consecutive_reboots:
            log.error(
                f"Network watchdog: {reboots} reboots without recovering connectivity - "
                "not rebooting again; will keep retrying the interface instead"
            )
            return False

        state["consecutive_reboots"] = reboots + 1
        state["last_reboot"] = time.time()
        self._save_state(state)

        log.critical(f"Network watchdog triggering system reboot ({reboots + 1}/{self.config.max_consecutive_reboots})")
        try:
            subprocess.run(["sudo", "reboot"], capture_output=True, timeout=10)
            return True
        except Exception as e:
            log.error(f"Failed to reboot: {e}")
            return False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _set_connected(self, connected: bool) -> None:
        if self._connected == connected:
            return
        self._connected = connected
        if self._on_change:
            try:
                self._on_change(connected)
            except Exception as e:
                log.error(f"Connectivity callback failed: {e}")

    def _tick(self) -> None:
        if self._check_connectivity():
            if self._consecutive_failures > 0:
                log.info(f"Network connectivity restored after {self._consecutive_failures} failures")
            self._consecutive_failures = 0
            self._interface_restarted = False
            self._record_connectivity_restored()
            self._set_connected(True)
            return

        self._consecutive_failures += 1
        log.warning(f"Network check failed ({self._consecutive_failures}/{self.config.failure_threshold})")
        self._set_connected(False)

        if (self._consecutive_failures >= self.config.interface_restart_threshold
                and not self._interface_restarted):
            self._interface_restarted = True
            self._restart_interface()

        if self._consecutive_failures >= self.config.failure_threshold:
            log.error(f"Network down for ~{self._consecutive_failures * self.config.check_interval}s")
            if not self._reboot_system():
                # Budget exhausted: keep bouncing the interface periodically.
                self._interface_restarted = False
            self._consecutive_failures = 0

    def _watchdog_loop(self) -> None:
        log.info(f"Network watchdog started (reboot after {self.config.failure_threshold} failures)")
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                log.error(f"Network watchdog error: {e}")
            self._stop_event.wait(self.config.check_interval)
        log.info("Network watchdog stopped")

    def start(self) -> bool:
        """Start the network watchdog in a background thread."""
        if self._running:
            log.warning("Network watchdog already running")
            return True

        self._running = True
        self._stop_event.clear()
        self._consecutive_failures = 0
        self._thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="NetworkWatchdog"
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop the network watchdog."""
        log.info("Stopping network watchdog...")
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def is_running(self) -> bool:
        return self._running

    def is_connected(self) -> Optional[bool]:
        """Last known connectivity, or None before the first check."""
        return self._connected
