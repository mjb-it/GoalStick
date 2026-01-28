# GoalStick

A Python service that monitors NHL games and alerts you when your favorite team scores. Designed to run on IoT devices with automated scheduling during hockey season.

## Features

- **Automated Scheduling**: Runs daily during hockey season (October-June)
- **Smart Sleep Management**: Wakes up 5 minutes before game start
- **Real-time Goal Detection**: Checks every 0.5 seconds during live games
- **Team Customization**: Monitor any NHL team
- **IoT Optimized**: No system dependencies like cron required
- **Graceful Shutdown**: Clean signal handling for embedded devices

## Installation

```bash
pip install -e .
```

## Quick Start

### Basic Usage

```python
from StickCheck import StickCheckScheduler, SchedulerConfig

# Use default configuration (Washington Capitals)
scheduler = StickCheckScheduler()
scheduler.start()
```

### Custom Configuration

```python
from StickCheck import StickCheckScheduler, SchedulerConfig

config = SchedulerConfig(
    team_abbr="TOR",           # Monitor Toronto Maple Leafs
    check_interval=0.5,        # Check every 0.5 seconds during games
    daily_check_hour=9,        # Check for games at 9 AM daily
    pre_game_wake_minutes=10,  # Wake up 10 minutes before game
    api_timeout=10,           # API timeout in seconds
    max_retries=3             # Retry failed API calls 3 times
)

scheduler = StickCheckScheduler(config)
scheduler.start()
```

### Command Line Usage

```bash
python main.py
```

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `team_abbr` | str | "WSH" | NHL team abbreviation (e.g., "TOR", "NYR", "CHI") |
| `check_interval` | float | 0.5 | Seconds between goal checks during live games |
| `daily_check_hour` | int | 8 | Hour (24-hour format) to check daily schedule |
| `pre_game_wake_minutes` | int | 5 | Minutes before game to wake up |
| `api_timeout` | int | 10 | API request timeout in seconds |
| `max_retries` | int | 3 | Maximum retry attempts for API failures |

## NHL Team Abbreviations

Common abbreviations include:
- Eastern Conference: BOS, BUF, CBJ, CAR, DET, FLA, MTL, NJD, NYI, NYR, OTT, PHI, PIT, TBL, TOR, WSH
- Western Conference: ANA, ARI, CGY, CHI, COL, DAL, EDM, LAK, MIN, NSH, PHI, SJS, STL, VAN, VGK, WPG

## How It Works

1. **Daily Check**: Service runs once per day during hockey season
2. **Game Detection**: Checks if your team is playing today
3. **Smart Sleep**: Sleeps until 5 minutes before game start
4. **Live Monitoring**: During games, checks every 0.5 seconds for goals
5. **Off-season**: Automatically sleeps through summer months

## Architecture

- **GameSchedule**: Handles NHL API integration and schedule parsing
- **ScoreKeeper**: Monitors live games and detects goals
- **StickCheckScheduler**: Manages timing and automated execution
- **HockeySeasonDetector**: Determines if current date is in hockey season

## Logging

The service provides detailed logging:
```python
import logging
logging.basicConfig(level=logging.INFO)
```

Log levels:
- `INFO`: Game status, scheduler events
- `DEBUG`: Detailed goal checking (useful for troubleshooting)
- `WARNING`: API retry attempts
- `ERROR`: API failures and critical errors

## IoT Deployment

Designed for embedded devices:
- No external dependencies (no cron required)
- Minimal resource usage during sleep periods
- Graceful shutdown handling
- Configurable check intervals to balance responsiveness vs. battery life

## Dependencies

- `nhlpy`: NHL API client
- `python-dateutil`: Date parsing utilities
- Python 3.14+

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request