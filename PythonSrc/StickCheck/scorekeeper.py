from nhlpy import NHLClient
from typing import Dict, Optional
from datetime import datetime
from dateutil.parser import parse
from zoneinfo import ZoneInfo
import logging
log = logging.getLogger(__name__)

# All game times displayed in Eastern Time
EASTERN_TZ = ZoneInfo("America/New_York")

# NHL API gameState values
LIVE_STATES = ("LIVE", "CRIT")
FINAL_STATES = ("FINAL", "OFF")
# NHL API gameScheduleState values that mean the game will not be played today
ABANDONED_SCHEDULE_STATES = ("PPD", "SUSP", "CNCL")


def _is_terminal(game_state: Optional[str], schedule_state: Optional[str]) -> bool:
    """True when nothing more will happen for this game today."""
    return game_state in FINAL_STATES or schedule_state in ABANDONED_SCHEDULE_STATES


class Game:
    def __init__(self, game: Dict):
        self.game_id = game["id"]
        self.state = game["gameState"]
        self.schedule_state = game.get("gameScheduleState", "OK")
        self.away_team = game["awayTeam"]["abbrev"]
        self.home_team = game["homeTeam"]["abbrev"]
        self.my_team_location: Optional[str] = None
        self.scheduled_timestamp: float = parse(game["startTimeUTC"]).timestamp()
        self.is_live = self.state in LIVE_STATES

    @property
    def is_abandoned(self) -> bool:
        """Postponed, suspended or cancelled."""
        return self.schedule_state in ABANDONED_SCHEDULE_STATES

class GameSchedule:
    def __init__(self, my_team_abbr: str = "WSH"):
        log.info(f"Initializing game schedule for {my_team_abbr}")
        self.my_game_today: Optional[Game] = None
        self._my_team = my_team_abbr
        self._client = NHLClient()
        self._set_schedule(self._client.schedule.daily_schedule())

    def _set_schedule(self, games: Dict) -> None:
        if len(games["games"]) == 0:
            raise ValueError("No games found for today")
        else:
            log.info(f"Found {len(games['games'])} games for today")
        for game in games["games"]:
            current_game = Game(game)
            game_time_et = datetime.fromtimestamp(current_game.scheduled_timestamp, tz=EASTERN_TZ)
            log.info(f"{current_game.away_team} vs {current_game.home_team} at {game_time_et.strftime('%I:%M %p %Z')}")
            if self._my_team in (current_game.away_team, current_game.home_team):
                if current_game.is_abandoned:
                    log.info(f"Game for {self._my_team} is {current_game.schedule_state} - skipping")
                    continue
                log.info(f"Found game for {self._my_team}, stopping search.")
                self.my_team_location = "homeTeam" if current_game.home_team == self._my_team else "awayTeam"
                self.my_game_today = current_game
                self.my_game_today.my_team_location = self.my_team_location
                break

class ScoreKeeper:
    def __init__(self, my_game: Game):
        self.my_game = my_game
        self._client = NHLClient()
        self.last_score: int = 0
        self._game_ended = False
        self._consecutive_errors = 0

    @property
    def has_ended(self) -> bool:
        """True once the game is final, postponed, suspended or cancelled."""
        return self._game_ended

    def is_in_play(self) -> bool:
        """Check if game is still in play. Uses cached state if game has ended."""
        if self._game_ended:
            return False
        try:
            boxscore = self._client.game_center.boxscore(game_id=self.my_game.game_id)
            state = boxscore.get("gameState")
            schedule_state = boxscore.get("gameScheduleState")
            if _is_terminal(state, schedule_state):
                log.info(f"Game is over (state={state}, schedule={schedule_state})")
                self._game_ended = True
                return False
            return state in LIVE_STATES
        except Exception as e:
            log.error(f"Error checking game state: {e}")
            return False

    def check_for_goal(self) -> tuple[bool, bool]:
        """
        Check if we scored and if game is still in play.
        Returns (scored: bool, game_in_play: bool)
        Uses single API call to play-by-play which contains both score and game state.
        """
        if self._game_ended:
            return False, False

        try:
            play_by_play = self._client.game_center.play_by_play(game_id=self.my_game.game_id)
            self._consecutive_errors = 0

            # Check game state
            state = play_by_play.get("gameState")
            schedule_state = play_by_play.get("gameScheduleState")

            if _is_terminal(state, schedule_state):
                log.info(f"Game is over (state={state}, schedule={schedule_state})")
                self._game_ended = True
                return False, False

            if state not in LIVE_STATES:
                # Intermission-like states (e.g. PRE/FUT) - not over, not scoring.
                return False, False

            # Check score
            current_score = play_by_play[self.my_game.my_team_location]["score"]

            if current_score > self.last_score:
                self.last_score = current_score
                return True, True
            elif current_score < self.last_score:
                # Score correction (rare but possible)
                self.last_score = current_score
                log.warning(f"Score corrected: {current_score}")
                return False, True
            else:
                return False, True
        except Exception as e:
            self._consecutive_errors += 1
            log.error(f"Error checking score ({self._consecutive_errors} in a row): {e}")
            return False, True  # Assume game still in play on error
