from nhlpy import NHLClient
from typing import Dict, Optional
from datetime import datetime
from dateutil.parser import parse
import logging
log = logging.getLogger(__name__)


class Game:
    def __init__(self, game: Dict):
        self.game_id = game["id"]
        self.state = game["gameState"]
        self.away_team = game["awayTeam"]["abbrev"]
        self.home_team = game["homeTeam"]["abbrev"]
        self.my_team_location: Optional[str] = None
        self.scheduled_timestamp: float = parse(game["startTimeUTC"]).timestamp()
        self.is_live = True if self.state == "LIVE" else False

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
            log.info(f"{current_game.away_team} vs {current_game.home_team} at {datetime.fromtimestamp(current_game.scheduled_timestamp).strftime('%I:%M %p')}")
            if self._my_team in (current_game.away_team, current_game.home_team):
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

    def is_in_play(self) -> bool:
        """Check if game is still in play. Uses cached state if game has ended."""
        if self._game_ended:
            return False
        try:
            boxscore = self._client.game_center.boxscore(game_id=self.my_game.game_id)
            state = boxscore.get("gameState")
            in_play = state in ["LIVE", "CRIT"]
            if not in_play and state in ["FINAL", "OFF"]:
                self._game_ended = True
            return in_play
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
            
            # Check game state
            state = play_by_play.get("gameState")
            game_in_play = state in ["LIVE", "CRIT"]
            
            if not game_in_play:
                if state in ["FINAL", "OFF"]:
                    self._game_ended = True
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
            log.error(f"Error checking score: {e}")
            return False, True  # Assume game still in play on error
