import sys
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

sys.modules['nhlpy'] = MagicMock()

import StickCheck.scheduler as sched_mod
from StickCheck.scheduler import StickCheckScheduler, SchedulerConfig


@pytest.fixture
def scheduler(monkeypatch):
    store = MagicMock()
    store.get_team.return_value = "WSH"
    store.get_celebration_delay.return_value = 0
    monkeypatch.setattr(sched_mod, "ConfigStore", lambda: store)
    monkeypatch.setattr(sched_mod, "LEDController", lambda **kw: MagicMock())
    monkeypatch.setattr(sched_mod, "ESP32Reset", lambda **kw: MagicMock())
    s = StickCheckScheduler(SchedulerConfig(pre_game_check_interval=0.01))
    s.running = True
    return s


class TestSleep:
    def test_sleep_until_time_recomputes_against_wall_clock(self, scheduler, monkeypatch):
        monkeypatch.setattr(sched_mod, "MAX_SLEEP_CHUNK_SECONDS", 0.01)
        sleeps = []
        monkeypatch.setattr(scheduler, "_sleep", lambda s: sleeps.append(s))

        # Clock "jumps" forward past the target after the first chunk
        base = datetime(2026, 1, 1, 7, 59, 0)
        times = iter([base, base, base + timedelta(hours=5)])
        monkeypatch.setattr(sched_mod, "datetime", MagicMock(now=lambda: next(times)))

        scheduler._sleep_until_time(base + timedelta(minutes=1))
        assert len(sleeps) == 1  # woke immediately once the clock passed the target

    def test_sleep_until_time_in_past_returns(self, scheduler, monkeypatch):
        called = []
        monkeypatch.setattr(scheduler, "_sleep", lambda s: called.append(s))
        scheduler._sleep_until_time(datetime.now() - timedelta(seconds=1))
        assert called == []

    def test_stop_wakes_sleep(self, scheduler):
        t = threading.Thread(target=lambda: scheduler._sleep(10))
        start = time.monotonic()
        t.start()
        scheduler.stop()
        t.join(timeout=2)
        assert not t.is_alive()
        assert time.monotonic() - start < 2


class TestWaitForGameStart:
    def test_returns_when_live(self, scheduler):
        scheduler.scorekeeper = MagicMock()
        scheduler.scorekeeper.is_in_play.side_effect = [False, True]
        scheduler.scorekeeper.has_ended = False
        assert scheduler._wait_for_game_start() is True

    def test_bails_out_when_game_ended(self, scheduler):
        scheduler.scorekeeper = MagicMock()
        scheduler.scorekeeper.is_in_play.return_value = False
        scheduler.scorekeeper.has_ended = True
        assert scheduler._wait_for_game_start() is False
        assert scheduler.scorekeeper.is_in_play.call_count == 1

    def test_gives_up_after_max_checks(self, scheduler, monkeypatch):
        monkeypatch.setattr(scheduler, "MAX_WAIT_FOR_START_MINUTES", 1)
        scheduler.scorekeeper = MagicMock()
        scheduler.scorekeeper.is_in_play.return_value = False
        scheduler.scorekeeper.has_ended = False
        assert scheduler._wait_for_game_start() is False
        assert scheduler.scorekeeper.is_in_play.call_count == 60


class TestRunLoop:
    def test_exception_in_cycle_does_not_stop_scheduler(self, scheduler, monkeypatch):
        monkeypatch.setattr(sched_mod, "ERROR_BACKOFF_SECONDS", 0)
        calls = []

        def cycle():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("NHL API exploded")
            scheduler.running = False

        monkeypatch.setattr(scheduler, "run_daily_cycle", cycle)
        scheduler.start()
        assert len(calls) == 2
        assert scheduler.running is False

    def test_keyboard_interrupt_stops(self, scheduler, monkeypatch):
        def cycle():
            raise KeyboardInterrupt
        monkeypatch.setattr(scheduler, "run_daily_cycle", cycle)
        scheduler.start()
        assert scheduler.running is False
