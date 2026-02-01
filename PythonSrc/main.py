import logging
import signal
import sys
import argparse
from StickCheck import (
    StickCheckScheduler, 
    SchedulerConfig,
    BluetoothPairing,
    BluetoothConfig,
    BluetoothServer,
    BluetoothServerConfig,
    LEDController,
    LEDConfig,
    ConfigStore,
    PairingStatus,
    ButtonHandler,
    ButtonConfig
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

log = logging.getLogger(__name__)

scheduler = None
button_handler = None
pairing_in_progress = False

def signal_handler(sig, frame):
    print("\nShutting down gracefully...")
    if button_handler:
        button_handler.stop()
    if scheduler:
        scheduler.stop()
    sys.exit(0)

def setup_button_handler(config: SchedulerConfig):
    global pairing_in_progress
    
    def on_button_hold():
        global pairing_in_progress
        if pairing_in_progress:
            log.info("Pairing already in progress, ignoring button hold")
            return
        
        pairing_in_progress = True
        log.info("Button held - initiating Bluetooth pairing...")
        try:
            run_pairing_mode(config)
        finally:
            pairing_in_progress = False
    
    btn_config = ButtonConfig(
        gpio_pin=config.pairing_button_pin,
        hold_time=config.pairing_button_hold_time
    )
    handler = ButtonHandler(config=btn_config)
    handler.set_on_hold(on_button_hold)
    
    if handler.start():
        log.info(f"Button handler started on GPIO {config.pairing_button_pin} (hold {config.pairing_button_hold_time}s for pairing)")
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
    scheduler = StickCheckScheduler(config)
    
    # Set up button handler for pairing trigger
    button_handler = setup_button_handler(config)
    
    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        if button_handler:
            button_handler.stop()
        scheduler.stop()

if __name__ == "__main__":
    main()
