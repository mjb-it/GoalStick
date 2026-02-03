import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class NetworkWatchdogConfig:
    check_interval: int = 60  # Check every 60 seconds
    failure_threshold: int = 5  # Reboot after 5 consecutive failures (5 minutes)
    ping_hosts: tuple = ("8.8.8.8", "1.1.1.1")  # Google and Cloudflare DNS
    ping_timeout: int = 5  # Seconds to wait for ping response


class NetworkWatchdog:
    """
    Monitors network connectivity and reboots the system if connectivity
    is lost for an extended period.
    """
    
    def __init__(self, config: NetworkWatchdogConfig = None):
        self.config = config or NetworkWatchdogConfig()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._consecutive_failures = 0
    
    def _check_connectivity(self) -> bool:
        """
        Check if we can reach the internet by pinging known hosts.
        Returns True if any host is reachable.
        """
        for host in self.config.ping_hosts:
            try:
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", str(self.config.ping_timeout), host],
                    capture_output=True,
                    text=True,
                    timeout=self.config.ping_timeout + 2
                )
                if result.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, Exception):
                continue
        return False
    
    def _reboot_system(self) -> None:
        """Reboot the system."""
        log.critical("Network watchdog triggering system reboot!")
        try:
            subprocess.run(["sudo", "reboot"], capture_output=True, timeout=10)
        except Exception as e:
            log.error(f"Failed to reboot: {e}")
    
    def _watchdog_loop(self) -> None:
        """Main watchdog loop."""
        log.info(f"Network watchdog started (threshold: {self.config.failure_threshold} failures)")
        
        while self._running:
            if self._check_connectivity():
                if self._consecutive_failures > 0:
                    log.info(f"Network connectivity restored after {self._consecutive_failures} failures")
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1
                log.warning(f"Network check failed ({self._consecutive_failures}/{self.config.failure_threshold})")
                
                if self._consecutive_failures >= self.config.failure_threshold:
                    log.error(f"Network down for {self._consecutive_failures * self.config.check_interval}s - rebooting")
                    self._reboot_system()
                    # If reboot fails, reset counter and try again
                    self._consecutive_failures = 0
            
            time.sleep(self.config.check_interval)
        
        log.info("Network watchdog stopped")
    
    def start(self) -> bool:
        """Start the network watchdog in a background thread."""
        if self._running:
            log.warning("Network watchdog already running")
            return True
        
        self._running = True
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
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
    
    def is_running(self) -> bool:
        return self._running
