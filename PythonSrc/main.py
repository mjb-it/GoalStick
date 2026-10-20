import logging
import logging.handlers
import signal
import subprocess
import sys
import threading
import time
import argparse
from pathlib import Path
from StickCheck import (
    StickCheckScheduler,
    SchedulerConfig,
    BluetoothServer,
    BluetoothServerConfig,
    BluetoothCommandServer,
    LEDController,
    LEDConfig,
    ConfigStore,
    ButtonHandler,
    ButtonConfig,
    factory_reset,
    NetworkWatchdog,
    StatusLED,
    DeviceState,
    SystemdWatchdog,
    is_wifi_configured
)

# Factory reset is ignored for this long after start so a stuck button or a
# floating GPIO pin during boot cannot wipe the device.
FACTORY_RESET_MIN_UPTIME = 60


def setup_logging():
    """Set up logging with rotating file handler (weekly rotation, keep 4 weeks)."""
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler for systemd/journald
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    # Rotating file handler - rotate weekly, keep 4 backups. Optional: on a
    # developer machine /var/log may not be writable.
    try:
        log_dir = Path("/var/log/goalstick")
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_dir / "goalstick.log",
            when="W0",  # Rotate on Monday
            interval=1,
            backupCount=4,
            encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)
    except OSError as e:
        root_logger.warning(f"File logging disabled: {e}")

    # Silence noisy httpx logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

setup_logging()

log = logging.getLogger(__name__)


class Service:
    """Owns every long-running component so shutdown is one place."""

    def __init__(self, config: SchedulerConfig):
        self.config = config
        self.scheduler = None
        self.button_handler = None
        self.network_watchdog = None
        self.status_led = None
        self.bt_command_server = None
        self.systemd_watchdog = SystemdWatchdog()
        self.pairing_in_progress = False
        self.factory_reset_enabled = False
        self.service_start_time = time.time()
        self._stop_event = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shut_down = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        with self._shutdown_lock:
            if self._shut_down:
                return
            self._shut_down = True
        log.info("Shutting down...")
        self._stop_event.set()
        for name in ("button_handler", "network_watchdog", "bt_command_server", "scheduler", "status_led"):
            component = getattr(self, name)
            if component:
                try:
                    component.stop()
                except Exception as e:
                    log.warning(f"Error stopping {name}: {e}")
        self.systemd_watchdog.stop()

    def install_signal_handlers(self) -> None:
        def handler(sig, frame):
            log.info(f"Received signal {sig}")
            self._stop_event.set()
            if self.scheduler:
                self.scheduler.stop()
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    # ------------------------------------------------------------------
    # Button
    # ------------------------------------------------------------------

    def _on_button_hold(self) -> None:
        if self.pairing_in_progress:
            log.info("Pairing already in progress, ignoring button hold")
            return

        self.pairing_in_progress = True
        log.info("Button held (3s) - initiating Bluetooth pairing...")
        # The pairing server drives the strip itself (blue blink while waiting,
        # green flash once the app connects). Park the status LED so its blink
        # thread cannot overwrite those colours.
        if self.status_led:
            self.status_led.set_state(DeviceState.OFF)
        try:
            # Stop background BT server to free up the channel
            if self.bt_command_server and self.bt_command_server.is_running():
                log.info("Stopping background Bluetooth server for pairing mode...")
                self.bt_command_server.stop()
            # Let the socket close and any in-flight status LED pattern finish
            time.sleep(1)

            run_pairing_mode(self.config, led_controller=self.scheduler.led_controller if self.scheduler else None)
        except Exception:
            log.exception("Pairing mode failed")
        finally:
            self.pairing_in_progress = False
            if self.status_led:
                # Resume the magenta "needs WiFi" blink if we are still unconfigured
                self.status_led.set_state(
                    DeviceState.OFF if is_wifi_configured() else DeviceState.NO_WIFI_CONFIG)
            # Restart background BT server after pairing
            if self.bt_command_server and not self._stop_event.is_set():
                log.info("Restarting background Bluetooth server...")
                self.bt_command_server.start()

    def _on_factory_reset(self) -> None:
        elapsed_since_start = time.time() - self.service_start_time
        if elapsed_since_start < FACTORY_RESET_MIN_UPTIME:
            log.warning(f"Factory reset blocked - service started only {elapsed_since_start:.1f}s ago "
                        f"(minimum {FACTORY_RESET_MIN_UPTIME}s required)")
            return

        if not self.factory_reset_enabled:
            log.warning("Factory reset triggered but not yet enabled - enabling now")
            log.warning("Release button and hold again for 10s to confirm factory reset")
            self.factory_reset_enabled = True
            return

        log.warning("Button held (10s) - initiating FACTORY RESET...")
        led = self.scheduler.led_controller if self.scheduler else None
        if factory_reset(led_controller=led):
            log.info("Factory reset complete - rebooting...")
            subprocess.run(["sudo", "reboot"], capture_output=True)
        else:
            log.error("Factory reset failed")

    def setup_button_handler(self):
        btn_config = ButtonConfig(
            gpio_pin=self.config.pairing_button_pin,
            hold_time=self.config.pairing_button_hold_time,
            long_hold_time=self.config.factory_reset_hold_time
        )
        handler = ButtonHandler(config=btn_config)

        # Check initial button state to detect stuck buttons or floating pins
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.config.pairing_button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            if GPIO.input(self.config.pairing_button_pin) == GPIO.LOW:
                log.warning(f"WARNING: Button on GPIO {self.config.pairing_button_pin} is PRESSED at startup!")
                log.warning("This may indicate a stuck button or floating GPIO pin.")
                log.warning(f"Factory reset is DISABLED for {FACTORY_RESET_MIN_UPTIME} seconds to prevent accidental reset.")
            else:
                log.info(f"Button on GPIO {self.config.pairing_button_pin} is in normal state (released)")
        except Exception as e:
            log.debug(f"Could not check initial button state: {e}")

        handler.set_on_hold(self._on_button_hold)
        handler.set_on_long_hold(self._on_factory_reset)

        if handler.start():
            log.info(f"Button handler started on GPIO {self.config.pairing_button_pin}")
            log.info(f"  - Hold {self.config.pairing_button_hold_time}s for pairing mode")
            log.info(f"  - Hold {self.config.factory_reset_hold_time}s for factory reset")
            log.info(f"  - Factory reset requires {FACTORY_RESET_MIN_UPTIME}s uptime + double confirmation")
            self.button_handler = handler
        else:
            log.warning("Button handler could not start - pairing via button disabled")
            self.button_handler = None
        return self.button_handler

    # ------------------------------------------------------------------
    # Modes
    # ------------------------------------------------------------------

    def wait_for_wifi_setup(self) -> None:
        """No WiFi configured: blink magenta and wait for pairing to configure it."""
        log.warning("WiFi not configured - waiting for Bluetooth setup")
        self.status_led.set_state(DeviceState.NO_WIFI_CONFIG)
        self.systemd_watchdog.set_status("Waiting for WiFi configuration")
        self.setup_button_handler()

        while not self._stop_event.wait(5):
            if is_wifi_configured():
                log.info("WiFi now configured - restarting service to apply")
                subprocess.run(["sudo", "systemctl", "restart", "goalstick"], capture_output=True)
                return

    def run(self) -> None:
        self.systemd_watchdog.start()
        self.scheduler = StickCheckScheduler(self.config)

        self.status_led = StatusLED()
        self.status_led.set_led_controller(self.scheduler.led_controller)
        self.status_led.start()

        try:
            if not is_wifi_configured():
                self.wait_for_wifi_setup()
                return

            self.scheduler.set_status_led(self.status_led)
            self.setup_button_handler()

            # Background Bluetooth command server for app communication
            self.bt_command_server = BluetoothCommandServer(
                led_controller=self.scheduler.led_controller,
                config_store=self.scheduler.config_store
            )
            self.bt_command_server.start()
            log.info("Background Bluetooth command server started")

            # Network watchdog: restarts WiFi, then reboots (with a cap) if offline
            def on_connectivity(connected: bool):
                if connected:
                    if self.status_led.get_state() == DeviceState.NO_NETWORK:
                        self.status_led.set_state(DeviceState.OFF)
                else:
                    self.status_led.set_state(DeviceState.NO_NETWORK)

            self.network_watchdog = NetworkWatchdog(on_connectivity_change=on_connectivity)
            self.network_watchdog.start()

            # Flash yellow to indicate boot sequence complete
            if self.scheduler.led_controller and self.scheduler.led_controller.is_connected():
                try:
                    log.info("Boot sequence complete - flashing yellow indicator")
                    self.scheduler.led_controller._send_command("C:AAAA00")
                    time.sleep(2)
                    self.scheduler.led_controller._send_command("I")
                except Exception as e:
                    log.warning(f"Could not send boot complete LED indicator: {e}")

            self.systemd_watchdog.set_status(f"Monitoring team {self.scheduler.get_team()}")
            if not self._stop_event.is_set():
                self.scheduler.start()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()


def run_pairing_mode(config: SchedulerConfig, led_controller=None) -> bool:
    log.info("Entering Bluetooth pairing mode...")

    if led_controller is None:
        led_config = LEDConfig(
            serial_port=config.serial_port,
            baud_rate=config.serial_baud_rate
        )
        led_controller = LEDController(
            config=led_config,
            team_colors_path=config.team_colors_path
        )

    bt_config = BluetoothServerConfig(
        device_name=config.bluetooth_device_name,
        timeout=config.bluetooth_pairing_timeout
    )
    server = BluetoothServer(config=bt_config, led_controller=led_controller)

    def on_config_received(received_config):
        # The server has already validated and saved team/delay/WiFi.
        log.info(f"Received configuration - Team: {received_config.team_abbr}"
                 + (f", WiFi SSID: {received_config.wifi_ssid}" if received_config.wifi_ssid else ""))

    server.set_config_callback(on_config_received)

    paired = server.start()
    if paired:
        log.info("Bluetooth pairing complete"
                 + ("" if server.last_received_config else " (no configuration sent)"))
        return True
    log.warning("Bluetooth pairing timed out or failed")
    return False


def main():
    parser = argparse.ArgumentParser(description="GoalStick - NHL Goal Light Controller")
    parser.add_argument("--pair", action="store_true", help="Enter Bluetooth pairing mode")
    parser.add_argument("--team", type=str, help="Set team abbreviation (e.g., WSH, TOR, NYR)")
    parser.add_argument("--show-team", action="store_true", help="Show currently configured team")
    args = parser.parse_args()

    config = SchedulerConfig(
        check_interval=0.5,  # Check every 0.5 seconds during live games
        daily_check_hour=8,  # Check for games at 8 AM daily
    )

    if args.show_team:
        print(f"Currently configured team: {ConfigStore().get_team()}")
        return

    if args.team:
        if ConfigStore().set_team(args.team):
            print(f"Team set to: {args.team.strip().upper()}")
        else:
            print("Failed to save team configuration (expected a 2-3 letter abbreviation)")
            sys.exit(1)
        return

    if args.pair:
        watchdog = SystemdWatchdog()
        watchdog.start()
        try:
            success = run_pairing_mode(config)
        finally:
            watchdog.stop()
        sys.exit(0 if success else 1)

    service = Service(config)
    service.install_signal_handlers()
    service.run()


if __name__ == "__main__":
    main()
