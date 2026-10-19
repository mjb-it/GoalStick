import sys
from unittest.mock import MagicMock

import pytest

sys.modules['nhlpy'] = MagicMock()

from StickCheck.scorekeeper import Game, GameSchedule, ScoreKeeper


def make_game(state="FUT", schedule_state="OK", home="WSH", away="TOR"):
    return Game({
        "id": 2025020001,
        "gameState": state,
        "gameScheduleState": schedule_state,
        "awayTeam": {"abbrev": away},
        "homeTeam": {"abbrev": home},
        "startTimeUTC": "2026-01-15T00:00:00Z",
    })


@pytest.fixture
def keeper():
    game = make_game(state="LIVE")
    game.my_team_location = "homeTeam"
    sk = ScoreKeeper(game)
    sk._client = MagicMock()
    return sk


def pbp(state="LIVE", schedule_state="OK", score=0):
    return {"gameState": state, "gameScheduleState": schedule_state,
            "homeTeam": {"score": score}, "awayTeam": {"score": 0}}


class TestGame:
    def test_abandoned_flags(self):
        assert make_game(schedule_state="PPD").is_abandoned
        assert make_game(schedule_state="CNCL").is_abandoned
        assert make_game(schedule_state="SUSP").is_abandoned
        assert not make_game(schedule_state="OK").is_abandoned

    def test_missing_schedule_state_defaults_ok(self):
        g = Game({
            "id": 1, "gameState": "FUT",
            "awayTeam": {"abbrev": "A"}, "homeTeam": {"abbrev": "B"},
            "startTimeUTC": "2026-01-15T00:00:00Z",
        })
        assert g.schedule_state == "OK"

    def test_is_live_for_crit(self):
        assert make_game(state="CRIT").is_live


class TestGameSchedule:
    def test_skips_postponed_game(self):
        sched = GameSchedule.__new__(GameSchedule)
        sched.my_game_today = None
        sched._my_team = "WSH"
        games = {"games": [
            {"id": 1, "gameState": "FUT", "gameScheduleState": "PPD",
             "awayTeam": {"abbrev": "TOR"}, "homeTeam": {"abbrev": "WSH"},
             "startTimeUTC": "2026-01-15T00:00:00Z"},
        ]}
        sched._set_schedule(games)
        assert sched.my_game_today is None

    def test_finds_game(self):
        sched = GameSchedule.__new__(GameSchedule)
        sched.my_game_today = None
        sched._my_team = "WSH"
        games = {"games": [
            {"id": 1, "gameState": "FUT", "gameScheduleState": "OK",
             "awayTeam": {"abbrev": "WSH"}, "homeTeam": {"abbrev": "TOR"},
             "startTimeUTC": "2026-01-15T00:00:00Z"},
        ]}
        sched._set_schedule(games)
        assert sched.my_game_today.game_id == 1
        assert sched.my_game_today.my_team_location == "awayTeam"


class TestScoreKeeper:
    def test_goal_detected(self, keeper):
        keeper._client.game_center.play_by_play.return_value = pbp(score=1)
        assert keeper.check_for_goal() == (True, True)
        keeper._client.game_center.play_by_play.return_value = pbp(score=1)
        assert keeper.check_for_goal() == (False, True)

    @pytest.mark.parametrize("state", ["FINAL", "OFF"])
    def test_final_ends_game(self, keeper, state):
        keeper._client.game_center.play_by_play.return_value = pbp(state=state)
        assert keeper.check_for_goal() == (False, False)
        assert keeper.has_ended
        # Cached: no further API calls
        keeper._client.game_center.play_by_play.reset_mock()
        assert keeper.check_for_goal() == (False, False)
        keeper._client.game_center.play_by_play.assert_not_called()

    @pytest.mark.parametrize("sched", ["PPD", "SUSP", "CNCL"])
    def test_postponed_ends_game(self, keeper, sched):
        keeper._client.game_center.play_by_play.return_value = pbp(state="FUT", schedule_state=sched)
        assert keeper.check_for_goal() == (False, False)
        assert keeper.has_ended

    def test_is_in_play_marks_postponed_as_ended(self, keeper):
        keeper._client.game_center.boxscore.return_value = {"gameState": "FUT", "gameScheduleState": "PPD"}
        assert keeper.is_in_play() is False
        assert keeper.has_ended

    def test_is_in_play_not_started_not_ended(self, keeper):
        keeper._client.game_center.boxscore.return_value = {"gameState": "PRE", "gameScheduleState": "OK"}
        assert keeper.is_in_play() is False
        assert not keeper.has_ended

    def test_is_in_play_live(self, keeper):
        keeper._client.game_center.boxscore.return_value = {"gameState": "LIVE"}
        assert keeper.is_in_play() is True

    def test_api_error_assumes_still_in_play(self, keeper):
        keeper._client.game_center.play_by_play.side_effect = RuntimeError("503")
        assert keeper.check_for_goal() == (False, True)
        assert not keeper.has_ended

    def test_score_correction(self, keeper):
        keeper.last_score = 2
        keeper._client.game_center.play_by_play.return_value = pbp(score=1)
        assert keeper.check_for_goal() == (False, True)
        assert keeper.last_score == 1
