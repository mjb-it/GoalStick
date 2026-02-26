import logging
import logging.handlers
import signal
import subprocess
import sys
import time
import argparse
from pathlib import Path
from StickCheck import (
    StickCheckScheduler, 
    SchedulerConfig,
    BluetoothPairing,
    BluetoothConfig,
    BluetoothServer,
    BluetoothServerConfig,
    BluetoothCommandServer,
    LEDController,
    LEDConfig,
    ConfigStore,
    PairingStatus,
    ButtonHandler,
    ButtonConfig,
    factory_reset,
    check_for_updates,
    update_and_restart,
    NetworkWatchdog,
    NetworkWatchdogConfig,
    StatusLED,
    DeviceState,
    is_wifi_configured
)

def setup_logging():
    """Set up logging with rotating file handler (weekly rotation, keep 4 weeks)."""
    log_dir = Path("/var/log/goalstick")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "goalstick.log"
    
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    
    # Rotating file handler - rotate weekly, keep 4 backups
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file,
        when="W0",  # Rotate on Monday
        interval=1,
        backupCount=4,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # Console handler for systemd/journald
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Silence noisy httpx logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

setup_logging()

log = logging.getLogger(__name__)

scheduler = None
button_handler = None
network_watchdog = None
status_led = None
pairing_in_progress = False
factory_reset_enabled = False
service_start_time = None

def signal_handler(sig, frame):
    print("\nShutting down gracefully...")
    if button_handler:
        button_handler.stop()
    if network_watchdog:
        network_watchdog.stop()
    if status_led:
        status_led.stop()
    if scheduler:
        scheduler.stop()
    sys.exit(0)

def setup_button_handler(config: SchedulerConfig):
    global pairing_in_progress, factory_reset_enabled, service_start_time
    import time
    
    service_start_time = time.time()
    
    def on_button_hold():
        global pairing_in_progress
        if pairing_in_progress:
            log.info("Pairing already in progress, ignoring button hold")
            return
        
        pairing_in_progress = True
        log.info("Button held (3s) - initiating Bluetooth pairing...")
        try:
            run_pairing_mode(config)
        finally:
            pairing_in_progress = False
    
    def on_factory_reset():
        global factory_reset_enabled, service_start_time
        
        # Prevent factory reset within first 60 seconds of service start
        # This prevents accidental resets from stuck buttons or floating GPIO pins during boot
        elapsed_since_start = time.time() - service_start_time
        if elapsed_since_start < 60:
            log.warning(f"Factory reset blocked - service started only {elapsed_since_start:.1f}s ago (minimum 60s required)")
            log.warning("This prevents accidental resets during boot. Wait and try again.")
            return
        
        if not factory_reset_enabled:
            log.warning("Factory reset triggered but not yet enabled - enabling now")
            log.warning("Release button and hold again for 10s to confirm factory reset")
            factory_reset_enabled = True
            return
        
        log.warning("Button held (10s) - initiating FACTORY RESET...")
        if factory_reset():
            log.info("Factory reset complete - rebooting...")
            subprocess.run(["sudo", "reboot"], capture_output=True)
        else:
            log.error("Factory reset failed")
    
    btn_config = ButtonConfig(
        gpio_pin=config.pairing_button_pin,
        hold_time=config.pairing_button_hold_time,
        long_hold_time=config.factory_reset_hold_time
    )
    handler = ButtonHandler(config=btn_config)
    
    # Check initial button state before setting up callbacks
    # This helps detect stuck buttons or floating GPIO pins
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(config.pairing_button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        initial_state = GPIO.input(config.pairing_button_pin)
        if initial_state == GPIO.LOW:  # Button pressed at startup
            log.warning(f"WARNING: Button on GPIO {config.pairing_button_pin} is PRESSED at startup!")
            log.warning("This may indicate a stuck button or floating GPIO pin.")
            log.warning("Factory reset is DISABLED for 60 seconds to prevent accidental reset.")
        else:
            log.info(f"Button on GPIO {config.pairing_button_pin} is in normal state (released)")
    except Exception as e:
        log.debug(f"Could not check initial button state: {e}")
    
    handler.set_on_hold(on_button_hold)
    handler.set_on_long_hold(on_factory_reset)
    
    if handler.start():
        log.info(f"Button handler started on GPIO {config.pairing_button_pin}")
        log.info(f"  - Hold {config.pairing_button_hold_time}s for pairing mode")
        log.info(f"  - Hold {config.factory_reset_hold_time}s for factory reset")
        log.info(f"  - Factory reset requires 60s uptime + double confirmation")
        return handler
    else:
        log.warning("Button handler could not start - pairing via button disabled")
        return None


def run_pairing_mode(config: SchedulerConfig) -> bool:
    log.info("Entering Bluetooth pairing mode...")
    
    # Set up LED controller for status feedback
    led_config = LEDConfig(
        serial_port=config.serial_port,
        baud_rate=config.serial_baud_rate
    )
    led_controller = LEDController(
        config=led_config,
        team_colors_path=config.team_colors_path
    )
    
    # Set up Bluetooth server to receive configuration from Android app
    bt_config = BluetoothServerConfig(
        device_name=config.bluetooth_device_name,
        timeout=config.bluetooth_pairing_timeout
    )
    server = BluetoothServer(config=bt_config, led_controller=led_controller)
    
    # Set callback to save received configuration
    config_store = ConfigStore()
    
    def on_config_received(received_config):
        log.info(f"Received configuration - Team: {received_config.team_abbr}")
        config_store.set_team(received_config.team_abbr)
        
        # TODO: Apply WiFi configuration if needed
        # For now, just log it
        if received_config.wifi_ssid:
            log.info(f"WiFi SSID received: {received_config.wifi_ssid}")
    
    server.set_config_callback(on_config_received)
    
    # Start server and wait for configuration
    received = server.start()
    
    if received:
        log.info("Bluetooth configuration received successfully")
        return True
    else:
        log.warning("Bluetooth pairing timed out or failed")
        return False

def main():
    global scheduler
    
    parser = argparse.ArgumentParser(description="GoalStick - NHL Goal Light Controller")
    parser.add_argument(
        "--pair", 
        action="store_true",
        help="Enter Bluetooth pairing mode"
    )
    parser.add_argument(
        "--team",
        type=str,
        help="Set team abbreviation (e.g., WSH, TOR, NYR)"
    )
    parser.add_argument(
        "--show-team",
        action="store_true",
        help="Show currently configured team"
    )
    args = parser.parse_args()
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Configure scheduler
    config = SchedulerConfig(
        check_interval=0.5,  # Check every 0.5 seconds during live games
        daily_check_hour=8,  # Check for games at 8 AM daily
    )
    
    # Handle --show-team
    if args.show_team:
        config_store = ConfigStore()
        team = config_store.get_team()
        print(f"Currently configured team: {team}")
        return
    
    # Handle --team to set team
    if args.team:
        config_store = ConfigStore()
        if config_store.set_team(args.team.upper()):
            print(f"Team set to: {args.team.upper()}")
        else:
            print("Failed to save team configuration")
            sys.exit(1)
        return
    
    # Handle --pair for Bluetooth pairing mode
    if args.pair:
        success = run_pairing_mode(config)
        sys.exit(0 if success else 1)
    
    # Normal operation - start scheduler with button support
    global network_watchdog, status_led
    scheduler = StickCheckScheduler(config)
    
    # Set up status LED using the LED strip
    # Get the LED controller from the scheduler
    status_led = StatusLED()
    status_led.set_led_controller(scheduler.led_controller)
    status_led.start()
    
    # Check if WiFi is configured - if not, show magenta and wait for pairing
    if not is_wifi_configured():
        log.warning("WiFi not configured - waiting for Bluetooth setup")
        status_led.set_state(DeviceState.NO_WIFI_CONFIG)
        # Don't start scheduler or network watchdog without WiFi
        # Just wait for button press to enter pairing mode, or WiFi to be configured
        button_handler = setup_button_handler(config)
        try:
            while True:
                time.sleep(5)
                # Check if WiFi was configured (e.g., via Bluetooth pairing)
                if is_wifi_configured():
                    log.info("WiFi now configured - restarting service to apply")
                    # Restart the service to pick up the new WiFi config
                    subprocess.run(["sudo", "systemctl", "restart", "goalstick"], capture_output=True)
                    return
        except KeyboardInterrupt:
            pass
        finally:
            if button_handler:
                button_handler.stop()
            status_led.stop()
        return
    
    # Pass status LED to scheduler for state updates
    scheduler.set_status_led(status_led)
    
    # Set up button handler for pairing trigger
    button_handler = setup_button_handler(config)
    
    # Start background Bluetooth command server for app communication
    bt_command_server = BluetoothCommandServer(
        led_controller=scheduler.led_controller,
        config_store=scheduler.config_store
    )
    bt_command_server.start()
    log.info("Background Bluetooth command server started")
    
    # Start network watchdog (reboots if no connectivity for 5 minutes)
    network_watchdog = NetworkWatchdog()
    network_watchdog.start()
    
    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        if button_handler:
            button_handler.stop()
        if network_watchdog:
            network_watchdog.stop()
        if bt_command_server:
            bt_command_server.stop()
        if status_led:
            status_led.stop()
        scheduler.stop()

if __name__ == "__main__":
    main()
