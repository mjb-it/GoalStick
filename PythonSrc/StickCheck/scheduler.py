import os
import subprocess
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable
from dataclasses import dataclass
from .scorekeeper import GameSchedule, ScoreKeeper, EASTERN_TZ
from .led_controller import LEDController, LEDConfig
from .config_store import ConfigStore, UserConfig
from .esp32_reset import ESP32Reset, ResetConfig
from .auto_update import check_for_updates, update_code, run_system_updates, is_overlay_active, disable_overlay_for_update, enable_overlay_after_update, check_esp32_changes, update_esp32_firmware

log = logging.getLogger(__name__)

# How long to pause after an unexpected error in the daily cycle before
# trying again, so a persistent fault (e.g. API outage) does not spin.
ERROR_BACKOFF_SECONDS = 60
# Maximum single sleep; the wall clock is re-read between chunks so an NTP
# step (common right after boot on a Pi with no RTC) cannot push the next
# daily check out by a day.
MAX_SLEEP_CHUNK_SECONDS = 60


@dataclass
class SchedulerConfig:
    team_abbr: str = None  # If None, will load from persistent config
    check_interval: float = 2.0  # seconds during live game
    pre_game_check_interval: float = 30.0  # seconds when waiting for game to start
    daily_check_hour: int = 8  # hour to check for games (24-hour format)
    pre_game_wake_minutes: int = 5  # minutes before game to wake up
    api_timeout: int = 10  # seconds for API timeouts
    max_retries: int = 3  # retry attempts for API calls
    # LED controller settings
    serial_port: str = "/dev/serial0"  # Default UART on Raspberry Pi
    serial_baud_rate: int = 115200
    team_colors_path: str = None  # Path to team_colors.json, None for default
    # Bluetooth settings
    bluetooth_device_name: str = None  # Will use hostname if None
    bluetooth_pairing_timeout: int = 180  # 3 minutes
    # Button settings
    pairing_button_pin: int = 17  # BCM GPIO pin for pairing button
    pairing_button_hold_time: float = 3.0  # Seconds to hold for pairing
    factory_reset_hold_time: float = 10.0  # Seconds to hold for factory reset
    # ESP32 reset settings
    esp32_reset_pin: int = 27  # BCM GPIO pin connected to ESP32 EN pin
    esp32_reset_retries: int = 2  # Number of reset attempts before giving up


class HockeySeasonDetector:
    @staticmethod
    def is_hockey_season(date: datetime = None) -> bool:
        if date is None:
            date = datetime.now()
        
        year = date.year
        month = date.month
        
        # NHL season typically runs from October to June
        # Pre-season starts in September, regular season October-April, playoffs May-June
        if month >= 10 or month <= 6:
            return True
        elif month == 9:
            # September - assume pre-season starts around mid-September
            return date.day >= 15
        else:
            return False


class StickCheckScheduler:
    # Give up waiting for a game to start this long after its scheduled time
    MAX_WAIT_FOR_START_MINUTES = 60

    def __init__(self, config: SchedulerConfig = None):
        self.config = config or SchedulerConfig()
        self.game_schedule: Optional[GameSchedule] = None
        self.scorekeeper: Optional[ScoreKeeper] = None
        self.running = False
        
        # Initialize persistent config store
        self.config_store = ConfigStore()
        
        # Load team from persistent storage if not specified
        if self.config.team_abbr is None:
            self.config.team_abbr = self.config_store.get_team()
            log.info(f"Loaded team from persistent config: {self.config.team_abbr}")
        
        # Initialize LED controller
        led_config = LEDConfig(
            serial_port=self.config.serial_port,
            baud_rate=self.config.serial_baud_rate
        )
        self.led_controller = LEDController(
            config=led_config,
            team_colors_path=self.config.team_colors_path
        )
        
        # Initialize ESP32 reset controller
        reset_config = ResetConfig(reset_pin=self.config.esp32_reset_pin)
        self.esp32_reset = ESP32Reset(config=reset_config)
        
        # Wakes the sleeping main loop promptly on stop()
        self._wake_event = threading.Event()

        # Status LED (set externally via set_status_led)
        self._status_led = None
    
    def set_status_led(self, status_led) -> None:
        """Set the status LED controller for state updates."""
        self._status_led = status_led
    
    def _update_status(self, state) -> None:
        """Update the status LED if available."""
        if self._status_led:
            from .status_led import DeviceState
            self._status_led.set_state(state)
    
    def set_team(self, team_abbr: str) -> bool:
        team_abbr = team_abbr.upper()
        if self.config_store.set_team(team_abbr):
            self.config.team_abbr = team_abbr
            log.info(f"Team updated to: {team_abbr}")
            return True
        return False
    
    def get_team(self) -> str:
        return self.config.team_abbr
        
    def _sleep(self, seconds: float) -> None:
        """Sleep that returns early when stop() is called."""
        if seconds > 0:
            self._wake_event.wait(seconds)

    def _sleep_until_time(self, target_time: datetime) -> None:
        now = datetime.now()
        if target_time <= now:
            return
        log.info(f"Sleeping for {(target_time - now).total_seconds():.0f} seconds until {target_time.strftime('%Y-%m-%d %H:%M:%S')}")
        while self.running:
            remaining = (target_time - datetime.now()).total_seconds()
            if remaining <= 0:
                return
            self._sleep(min(remaining, MAX_SLEEP_CHUNK_SECONDS))
    
    def _sleep_until_daily_check(self) -> None:
        now = datetime.now()
        target_time = now.replace(
            hour=self.config.daily_check_hour,
            minute=0,
            second=0,
            microsecond=0
        )
        
        # If target time has passed today, set it for tomorrow
        if target_time <= now:
            target_time += timedelta(days=1)
        
        self._sleep_until_time(target_time)
    
    def _sleep_until_game_start(self) -> None:
        if not self.game_schedule or not self.game_schedule.my_game_today:
            return
        
        game_start = datetime.fromtimestamp(self.game_schedule.my_game_today.scheduled_timestamp)
        now = datetime.now()
        
        # Wake up configured minutes before game start
        wake_time = game_start - timedelta(minutes=self.config.pre_game_wake_minutes)
        
        if wake_time > now:
            self._sleep_until_time(wake_time)
    
    def _setup_today_game(self) -> bool:
        for attempt in range(self.config.max_retries):
            try:
                self.game_schedule = GameSchedule(self.config.team_abbr)
                if self.game_schedule.my_game_today:
                    self.scorekeeper = ScoreKeeper(self.game_schedule.my_game_today)
                    game = self.game_schedule.my_game_today
                    game_time = datetime.fromtimestamp(game.scheduled_timestamp, tz=EASTERN_TZ).strftime('%I:%M %p %Z')
                    log.info(f"Found game today: {game.away_team} vs {game.home_team} at {game_time}")
                    return True
                else:
                    log.info(f"No game for {self.config.team_abbr} today")
                    return False
            except ValueError as e:
                log.info(f"No games today: {e}")
                return False
            except Exception as e:
                if attempt < self.config.max_retries - 1:
                    log.warning(f"Attempt {attempt + 1} failed, retrying: {e}")
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    log.error(f"Error setting up today's game after {self.config.max_retries} attempts: {e}")
                    return False
        return False
    
    def _check_esp32_health(self) -> bool:
        log.info("Performing ESP32 health check...")
        
        if not self.led_controller.connect():
            log.error("Could not connect to ESP32")
            return False
        
        if self.led_controller.ping():
            log.info("ESP32 is responsive and ready")
            return True
        else:
            log.warning("ESP32 did not respond to ping")
            return False
    
    def _ensure_esp32_ready(self) -> bool:
        for attempt in range(self.config.esp32_reset_retries + 1):
            if self._check_esp32_health():
                return True
            
            if attempt < self.config.esp32_reset_retries:
                log.warning(f"ESP32 health check failed, attempting reset ({attempt + 1}/{self.config.esp32_reset_retries})...")
                
                # Disconnect serial before reset
                self.led_controller.disconnect()
                
                # Reset ESP32
                if self.esp32_reset.reset():
                    log.info("ESP32 reset complete, retrying health check...")
                else:
                    log.error("ESP32 reset failed")
        
        log.error("ESP32 could not be recovered after reset attempts")
        return False
    
    def _monitor_live_game(self) -> None:
        if not self.scorekeeper:
            return
        
        log.info("Starting live game monitoring")
        goals_detected = 0
        
        # Health check ESP32 before game monitoring, reset if needed
        if not self._ensure_esp32_ready():
            log.warning("ESP32 not available, continuing without lights")
        
        try:
            game_in_play = True
            check_count = 0
            while self.running and game_in_play:
                scored, game_in_play = self.scorekeeper.check_for_goal()
                check_count += 1
                
                if scored:
                    goals_detected += 1
                    game = self.scorekeeper.my_game
                    log.info(f"GOAL! {game.away_team} vs {game.home_team} - Goal #{goals_detected}")
                    
                    # Apply celebration delay (for broadcast sync)
                    delay = self.config_store.get_celebration_delay()
                    if delay > 0:
                        log.info(f"Waiting {delay}s for broadcast delay...")
                        self._sleep(delay)
                    
                    # Trigger LED celebration
                    self.led_controller.celebrate(self.config.team_abbr)
                
                # Log status every ~60 seconds (30 checks at 2s interval)
                if check_count % 30 == 0:
                    log.info(f"Monitoring... (score: {self.scorekeeper.last_score})")
                
                if game_in_play:
                    self._sleep(self.config.check_interval)
        finally:
            # Clean up LED controller
            self.led_controller.idle()
            self.led_controller.disconnect()
        
        if goals_detected > 0:
            log.info(f"Game monitoring complete. Detected {goals_detected} goals!")
        else:
            log.info("Game monitoring complete. No goals detected.")
    
    def _wait_for_game_start(self) -> bool:
        """Wait for game to actually start. Returns True if game started, False if gave up."""
        if not self.scorekeeper:
            return False
        
        log.info(f"Waiting for game to start (checking every {self.config.pre_game_check_interval:.0f} seconds)...")
        checks = 0
        max_checks = max(1, int((self.MAX_WAIT_FOR_START_MINUTES * 60) // max(1.0, self.config.pre_game_check_interval)))

        while self.running and checks < max_checks:
            if self.scorekeeper.is_in_play():
                log.info("Game has started!")
                return True
            if self.scorekeeper.has_ended:
                log.info("Game is final, postponed or cancelled - nothing to monitor")
                return False
            checks += 1
            self._sleep(self.config.pre_game_check_interval)

        log.warning("Game did not start within expected time")
        return False
    
    def _run_updates(self) -> None:
        """Run code and system updates."""
        try:
            # Check if we're running with overlay (read-only root)
            overlay_active = is_overlay_active()
            if overlay_active:
                log.debug("Overlay filesystem active - updates require reboot cycle")
            
            # Check for GoalStick code updates
            if check_for_updates():
                log.info("GoalStick updates available")
                
                if overlay_active:
                    # Need to disable overlay, reboot, apply update, re-enable, reboot
                    log.info("Disabling overlay for update (will reboot twice)...")
                    if disable_overlay_for_update():
                        # Schedule reboot - on next boot, overlay will be off
                        # and we can apply the update
                        log.info("Rebooting to apply updates...")
                        subprocess.run(["sudo", "reboot"], capture_output=True)
                        return
                else:
                    # No overlay, can update directly
                    if update_code():
                        # Check if ESP32 firmware needs updating before restarting
                        if check_esp32_changes():
                            log.info("ESP32 code changed - updating firmware...")
                            if update_esp32_firmware():
                                log.info("ESP32 firmware updated successfully")
                            else:
                                log.warning("ESP32 firmware update failed")

                        log.info("Restarting service to apply updates...")
                        subprocess.run(
                            ["sudo", "systemctl", "restart", "goalstick"],
                            capture_output=True,
                            text=True
                        )
                        # If we reach here, restart failed (normally this process is killed)
                        log.error("Service restart may have failed - continuing with old code")
            
            # Run system security updates (weekly, on Sundays)
            if datetime.now().weekday() == 6:  # Sunday
                log.info("Running weekly system updates...")
                if overlay_active:
                    log.info("Skipping system updates - overlay active")
                else:
                    run_system_updates()
                
        except Exception as e:
            log.error(f"Error during updates: {e}")
    
    def run_daily_cycle(self) -> None:
        from .status_led import DeviceState
        
        # Clear boot state and run updates silently
        self._update_status(DeviceState.OFF)
        self._run_updates()
        
        if not HockeySeasonDetector.is_hockey_season():
            log.info("Not hockey season - sleeping until tomorrow")
            self._sleep_until_daily_check()
            return
        
        log.info("Starting daily check for games")
        
        if self._setup_today_game():
            # Game found today - waiting for game time
            self._sleep_until_game_start()
            
            # Wait for game to actually start (with slower polling)
            if self._wait_for_game_start():
                self._monitor_live_game()
                log.info("Game ended - sleeping until tomorrow's check")
                self._sleep_until_daily_check()
            else:
                log.info("Game not in progress or already finished")
                self._sleep_until_daily_check()
        else:
            # No game today, sleep until tomorrow
            log.info("No game to monitor today")
            self._sleep_until_daily_check()
    
    def start(self) -> None:
        log.info(f"Starting StickCheck scheduler for team: {self.config.team_abbr}")
        self.running = True
        self._wake_event.clear()

        try:
            while self.running:
                try:
                    self.run_daily_cycle()
                except KeyboardInterrupt:
                    raise
                except Exception:
                    # Never let one bad cycle (API error, serial hiccup, bad
                    # schedule payload) take the whole service down.
                    log.exception(f"Scheduler cycle failed - retrying in {ERROR_BACKOFF_SECONDS}s")
                    self._sleep(ERROR_BACKOFF_SECONDS)
        except KeyboardInterrupt:
            log.info("Scheduler stopped by user")
        finally:
            self.running = False
            log.info("Scheduler stopped")

    def stop(self) -> None:
        log.info("Stopping scheduler...")
        self.running = False
        self._wake_event.set()
