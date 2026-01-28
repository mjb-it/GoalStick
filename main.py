import logging
import signal
import sys
from StickCheck import StickCheckScheduler, SchedulerConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

def signal_handler(sig, frame):
    print("\nShutting down gracefully...")
    sys.exit(0)

if __name__ == "__main__":
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Configure scheduler (you can customize these settings)
    config = SchedulerConfig(
        team_abbr="WSH",  # Default to Washington Capitals
        check_interval=0.5,  # Check every 0.5 seconds during live games
        daily_check_hour=8,  # Check for games at 8 AM daily
        timezone_offset=0  # Adjust for your timezone if needed
    )
    
    # Create and start scheduler
    scheduler = StickCheckScheduler(config)
    
    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        scheduler.stop()

