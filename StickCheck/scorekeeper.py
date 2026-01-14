

from nhlpy import NHLClient
from typing import Dict, Optional
from datetime import datetime
from dateutil.parser import parse
import logging
log = logging.getLogger(__name__)


class Game(object):

    def __init__(self, game: Dict):
        self.game_id = game["id"]
        self.state = game["gameState"]
        self.away_team = game["awayTeam"]["abbrev"]
        self.home_team = game["homeTeam"]["abbrev"]
        self.my_team_location: Optional[str] = None # TODO: (01) Abstract this into an enum.
        self.scheduled_timestamp: float = parse(game["startTimeUTC"]).timestamp()
        self.is_live = True if self.state == "LIVE" else False

class GameSchedule(object):
    def __init__(self, my_team_abbr: str = "WSH"):
        self.game_is_in_play = False
        self.my_game_today: Optional[Game] = None
        self.game_start_timestamp: Optional[float] = None
        self._my_team = my_team_abbr
        self._client = NHLClient()
        self._set_schedule(self._client.schedule.daily_schedule())
        self.last_score: int = 0

    def has_game_started(self) -> bool:
        if self.game_is_in_play and (datetime.now().timestamp() >= self.my_game_today.scheduled_timestamp):
            return True
        return False

    def did_we_score(self) -> bool:
        if self.has_game_started():
            current_score = self._client.game_center.play_by_play(game_id=self.my_game_today.game_id)[self.my_team_location]["score"]
        return None

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
                self.my_team_location = "Home" if current_game.home_team == self._my_team else "Away" # See TODO 01
                self.my_game_today = current_game
                self.my_game_today.my_team_location = self.my_team_location
                break



class ScoreKeeper:
    def __init__(self, my_game: Game):
        self.my_game = my_game



    def is_in_play(self)->bool:
        return True if self.my_game.my_game_today.state == "LIVE" else False

    def have_they_scored(self, current: int) -> bool:
        return True if current < self.my_game.last_score else False