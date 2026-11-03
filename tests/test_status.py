"""Tests for svf-status."""

import subprocess
from types import SimpleNamespace

import pytest

from src.cli import status
from src.core.mpv_client import MpvIpcError
from src.core.strings import ItalianStrings as S


class FakeClient:
    def __init__(self, running=True, idle=False, info=None, fail=False):
        self.running, self.idle, self.fail = running, idle, fail
        self.info = info or {"file": "/m/a.mp4", "time_pos": 65.4, "duration": 3725.0, "paused": False}

    def is_running(self):
        return self.running

    def get_property(self, name):
        if self.fail:
            raise MpvIpcError("boom")
        return self.idle

    def get_playback_status(self):
        return self.info


def runner_for(table):
    def runner(cmd, **kwargs):
        value = table.get(tuple(cmd))
        if isinstance(value, Exception):
            raise value
        if value is None:
            return SimpleNamespace(returncode=1, stdout="")
        return SimpleNamespace(returncode=0, stdout=value)

    return runner


@pytest.mark.parametrize("sec,exp", [(0, "0:00"), (65.9, "1:05"), (3725, "1:02:05"), (-3, "0:00")])
def test_format_clock(sec, exp):
    assert status.format_clock(sec) == exp


def test_player_playing():
    lines = status.player_lines(FakeClient())
    assert lines[0] == S.MSG_STATUS_PLAYER_FILE.format(path="/m/a.mp4")
    assert "1:05" in lines[1] and "1:02:05" in lines[1]
    assert S.UI_STATUS_STATE_PLAYING in lines[2]


def test_player_paused():
    info = {"file": "x", "time_pos": 1, "duration": 2, "paused": True}
    assert S.UI_STATUS_STATE_PAUSED in status.player_lines(FakeClient(info=info))[2]


def test_player_idle_down_and_ipc_error():
    assert status.player_lines(FakeClient(idle=True)) == [S.MSG_STATUS_PLAYER_IDLE]
    assert status.player_lines(FakeClient(running=False)) == [S.MSG_STATUS_PLAYER_DOWN]
    assert status.player_lines(FakeClient(fail=True)) == [S.MSG_STATUS_PLAYER_DOWN]


def test_cpu_temperature(tmp_path):
    f = tmp_path / "temp"
    f.write_text("48500\n")
    assert status.cpu_temperature_line(str(f)) == S.MSG_STATUS_CPU_TEMP.format(temp="48.5")
    f.write_text("abc")
    assert status.cpu_temperature_line(str(f)) == S.MSG_STATUS_CPU_TEMP_UNKNOWN
    assert status.cpu_temperature_line(str(tmp_path / "none")) == S.MSG_STATUS_CPU_TEMP_UNKNOWN


def test_ram(tmp_path):
    f = tmp_path / "meminfo"
    f.write_text("MemTotal:  4096000 kB\nMemFree: 1 kB\nMemAvailable:  1024000 kB\n")
    assert status.ram_line(str(f)) == S.MSG_STATUS_RAM.format(used=3000, total=4000)
    f.write_text("MemTotal: 5 kB\n")
    assert status.ram_line(str(f)) == S.MSG_STATUS_RAM_UNKNOWN
    assert status.ram_line(str(tmp_path / "none")) == S.MSG_STATUS_RAM_UNKNOWN


def test_disk(tmp_path):
    assert "GB" in status.disk_line(tmp_path)
    assert status.disk_line(tmp_path / "missing") == S.MSG_STATUS_DISK_UNKNOWN


XRANDR = "Screen 0: minimum 8 x 8\nHDMI-1 connected primary 1920x1080+0+0 (normal) 521mm\nVGA-1 disconnected\n"


def test_display_ok_none_and_failure(monkeypatch):
    ok = status.display_line(runner_for({("xrandr", "--query"): XRANDR}))
    assert ok == S.MSG_STATUS_DISPLAY.format(value="HDMI-1 1920x1080")
    none = status.display_line(runner_for({("xrandr", "--query"): "VGA-1 disconnected\n"}))
    assert S.UI_STATUS_DISPLAY_NONE in none
    assert status.display_line(runner_for({})) == S.MSG_STATUS_DISPLAY_UNKNOWN
    err = runner_for({("xrandr", "--query"): FileNotFoundError()})
    assert status.display_line(err) == S.MSG_STATUS_DISPLAY_UNKNOWN
    to = runner_for({("xrandr", "--query"): subprocess.TimeoutExpired("x", 5)})
    assert status.display_line(to) == S.MSG_STATUS_DISPLAY_UNKNOWN


def test_display_uses_display_env(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    seen = {}

    def runner(cmd, **kw):
        seen.update(kw["env"])
        return SimpleNamespace(returncode=0, stdout="")

    status.display_line(runner)
    assert seen["DISPLAY"] == ":0"


ADDR = "AA:BB:CC:DD:EE:FF"


def test_bluetooth_connected_with_battery():
    r = runner_for({
        ("bluetoothctl", "devices", "Connected"): f"Device {ADDR} Remote\n",
        ("bluetoothctl", "info", ADDR): "Battery Percentage: 0x55 (85)\n",
    })
    assert status.bluetooth_lines(r) == [
        S.MSG_STATUS_BT_CONNECTED.format(address=ADDR), S.MSG_STATUS_BT_BATTERY.format(battery="85")]


def test_bluetooth_without_battery_disconnected_unavailable():
    r = runner_for({("bluetoothctl", "devices", "Connected"): f"Device {ADDR} R\n"})
    assert status.bluetooth_lines(r)[1] == S.MSG_STATUS_BT_BATTERY_UNKNOWN
    r = runner_for({("bluetoothctl", "devices", "Connected"): ""})
    assert status.bluetooth_lines(r) == [S.MSG_STATUS_BT_DISCONNECTED]
    assert status.bluetooth_lines(runner_for({})) == [S.MSG_STATUS_BT_UNKNOWN]


def test_report_and_main(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SVF_ROOT", str(tmp_path))
    monkeypatch.setattr(status, "MpvClient", lambda: FakeClient(running=False))
    monkeypatch.setattr(status.subprocess, "run", runner_for({}))
    report = status.build_report(FakeClient(), tmp_path, runner_for({}))
    assert report[0] == S.MSG_STATUS_HEADER and len(report) >= 8
    assert status.main([]) == 0
    assert S.MSG_STATUS_PLAYER_DOWN in capsys.readouterr().out
