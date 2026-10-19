import json
import sys
from unittest.mock import MagicMock

import pytest

sys.modules['nhlpy'] = MagicMock()

from StickCheck.network_watchdog import NetworkWatchdog, NetworkWatchdogConfig


@pytest.fixture
def wd(temp_dir):
    config = NetworkWatchdogConfig(
        check_interval=1,
        interface_restart_threshold=2,
        failure_threshold=4,
        max_consecutive_reboots=2,
        state_path=temp_dir / "state.json",
    )
    events = []
    w = NetworkWatchdog(config=config, on_connectivity_change=events.append)
    w.events = events
    w.actions = []
    w._restart_interface = lambda: w.actions.append("restart")
    w._reboot_system_real = w._reboot_system
    return w


def fail(w):
    w._check_connectivity = lambda: False


def succeed(w):
    w._check_connectivity = lambda: True


class TestEscalation:
    def test_connected_emits_once(self, wd):
        succeed(wd)
        wd._tick()
        wd._tick()
        assert wd.events == [True]
        assert wd.is_connected() is True

    def test_interface_restart_before_reboot(self, wd, monkeypatch):
        reboots = []
        monkeypatch.setattr(wd, "_reboot_system", lambda: reboots.append(1) or True)
        fail(wd)
        wd._tick()
        assert wd.actions == []
        wd._tick()
        assert wd.actions == ["restart"]
        wd._tick()
        assert wd.actions == ["restart"]  # only once per outage
        assert reboots == []
        wd._tick()
        assert reboots == [1]
        assert wd.events == [False]

    def test_recovery_resets_counters(self, wd, monkeypatch):
        reboots = []
        monkeypatch.setattr(wd, "_reboot_system", lambda: reboots.append(1) or True)
        fail(wd)
        wd._tick(); wd._tick()
        succeed(wd)
        wd._tick()
        assert wd.events == [False, True]
        fail(wd)
        wd._tick(); wd._tick(); wd._tick()
        assert reboots == []
        assert wd.actions == ["restart", "restart"]


class TestRebootBudget:
    def test_reboot_count_persisted_and_capped(self, wd, monkeypatch):
        issued = []
        monkeypatch.setattr(wd.__class__, "_reboot_system", wd._reboot_system_real)
        import StickCheck.network_watchdog as nw
        monkeypatch.setattr(nw.subprocess, "run", lambda cmd, **k: issued.append(cmd))

        assert wd._reboot_system() is True
        assert json.loads(wd.config.state_path.read_text())["consecutive_reboots"] == 1
        assert wd._reboot_system() is True
        assert wd._reboot_system() is False  # budget (2) exhausted
        assert len(issued) == 2

    def test_connectivity_clears_reboot_count(self, wd):
        wd.config.state_path.write_text(json.dumps({"consecutive_reboots": 2}))
        succeed(wd)
        wd._tick()
        assert json.loads(wd.config.state_path.read_text())["consecutive_reboots"] == 0

    def test_exhausted_budget_keeps_restarting_interface(self, wd, monkeypatch):
        monkeypatch.setattr(wd, "_reboot_system", lambda: False)
        fail(wd)
        for _ in range(8):
            wd._tick()
        assert wd.actions.count("restart") == 2

    def test_corrupt_state_file_tolerated(self, wd):
        wd.config.state_path.write_text("{not json")
        assert wd._load_state() == {}


class TestConnectivityCheck:
    def test_tcp_fallback_when_ping_blocked(self, wd, monkeypatch):
        monkeypatch.setattr(wd, "_ping", lambda host: False)
        monkeypatch.setattr(wd, "_tcp_connect", lambda host, port: host == "api-web.nhle.com")
        assert wd._check_connectivity() is True

    def test_all_probes_fail(self, wd, monkeypatch):
        monkeypatch.setattr(wd, "_ping", lambda host: False)
        monkeypatch.setattr(wd, "_tcp_connect", lambda host, port: False)
        assert wd._check_connectivity() is False


class TestThread:
    def test_start_stop(self, wd):
        succeed(wd)
        assert wd.start() is True
        assert wd.is_running()
        wd.stop()
        assert not wd.is_running()
        assert not wd._thread.is_alive()
