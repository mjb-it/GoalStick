"""
Bluetooth pairing agent that automatically accepts pairing requests without PIN.
Uses bluetoothctl as a subprocess so BlueZ's own D-Bus/mainloop integration
handles the agent registration — more reliable than a Python D-Bus agent in a thread.
"""

import logging
import subprocess
import threading
import time

log = logging.getLogger(__name__)


class BluetoothAgentManager:
    """
    Runs bluetoothctl as a persistent subprocess registered as a NoInputNoOutput
    Bluetooth agent. bluetoothctl handles the BlueZ D-Bus wiring internally, which
    avoids GLib mainloop threading issues that cause Python D-Bus agents to not
    receive calls from bluetoothd.
    """

    def __init__(self):
        self._proc = None
        self._monitor_thread = None
        self._running = False

    def start(self):
        """Start bluetoothctl and register it as the default Bluetooth agent."""
        if self._running:
            return

        self._running = True
        try:
            self._proc = subprocess.Popen(
                ['bluetoothctl'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0
            )

            # Drain stdout in background so the process never blocks on output
            self._drain_thread = threading.Thread(
                target=self._drain_stdout, daemon=True
            )
            self._drain_thread.start()

            # Give bluetoothctl a moment to initialize its D-Bus connection
            time.sleep(0.5)

            self._proc.stdin.write(b'agent NoInputNoOutput\n')
            self._proc.stdin.flush()
            time.sleep(0.2)
            self._proc.stdin.write(b'default-agent\n')
            self._proc.stdin.flush()

            log.info("Bluetooth agent started (bluetoothctl NoInputNoOutput)")

            # Monitor for unexpected exit
            self._monitor_thread = threading.Thread(
                target=self._monitor, daemon=True
            )
            self._monitor_thread.start()

        except Exception as e:
            log.error(f"Failed to start bluetoothctl agent: {e}")
            self._running = False

    def _drain_stdout(self):
        """Read and discard bluetoothctl output to prevent stdout buffer from filling."""
        try:
            for line in iter(self._proc.stdout.readline, b''):
                if line.strip():
                    log.debug(f"bluetoothctl: {line.decode(errors='replace').strip()}")
        except Exception:
            pass

    def _monitor(self):
        """Detect if bluetoothctl exits unexpectedly."""
        if self._proc:
            self._proc.wait()
            if self._running:
                log.warning("bluetoothctl agent process exited unexpectedly")

    def stop(self):
        """Stop the bluetoothctl agent."""
        self._running = False
        if self._proc:
            try:
                self._proc.stdin.write(b'exit\n')
                self._proc.stdin.flush()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        log.info("Bluetooth agent stopped")


# Global agent manager instance
_agent_manager = None


def start_agent():
    """Start the global Bluetooth agent."""
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = BluetoothAgentManager()
    _agent_manager.start()


def stop_agent():
    """Stop the global Bluetooth agent."""
    global _agent_manager
    if _agent_manager:
        _agent_manager.stop()
        _agent_manager = None
