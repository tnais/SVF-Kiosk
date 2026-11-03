"""Tests for the playback controller, key mapping, mpv supervision and remote listener."""
import asyncio
import os
import signal

import pytest

from src.core.mpv_client import MpvIpcError
from src.core.strings import ItalianStrings as S
from src.daemon import kiosk_player as kp
from src.daemon.kiosk_player import (
    AMBIENT, EMPTY, ONDEMAND, MpvSupervisor, PlaybackController, key_from_event, mpv_command_line,
    next_index, osd_escape,
)
from src.db.database import Database


class FakeMpv:
    def __init__(self):
        self.calls = []
        self.idle = False
        self.fail = False

    def _check(self):
        if self.fail:
            raise MpvIpcError("down")

    def load_file(self, path, mode="replace"):
        self._check()
        self.calls.append(("load", path))
        self.idle = False

    def resume(self):
        self.calls.append(("resume",))

    def stop(self):
        self._check()
        self.calls.append(("stop",))

    def show_osd(self, text, duration_ms=3000):
        self._check()
        self.calls.append(("osd", text, duration_ms))

    def get_property(self, name):
        self._check()
        assert name == "idle-active"
        return self.idle

    @property
    def loaded(self):
        return [c[1] for c in self.calls if c[0] == "load"]

    @property
    def osds(self):
        return [c[1] for c in self.calls if c[0] == "osd"]


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def env(tmp_path):
    db = Database(tmp_path)
    ids = {}
    for name in ("A", "B", "C", "D"):
        f = tmp_path / f"{name}.mp4"
        f.write_bytes(b"x")
        ids[name] = db.add_video(str(f), f"Video {name}", None, 60, "1920x1080")
    db.set_playlist([ids["A"], ids["B"], ids["C"]])
    mpv, clock = FakeMpv(), Clock()
    ctl = PlaybackController(db, mpv, clock)
    return ctl, db, mpv, clock, ids, tmp_path


def finish(ctl, mpv, clock):
    clock.advance(2)
    mpv.idle = True
    ctl.tick()


def name_of(ctl):
    return ctl.current["display_title"]


# ---- pure functions -------------------------------------------------
@pytest.mark.parametrize("idx,total,expected", [(0, 3, 1), (1, 3, 2), (2, 3, 0), (0, 1, 0), (0, 0, 0)])
def test_next_index(idx, total, expected):
    assert next_index(idx, total) == expected


def test_mpv_command_line_has_required_flags():
    cmd = mpv_command_line("/run/svf-kiosk/mpv.sock")
    for flag in ("--vo=gpu", "--hwdec=auto-safe", "--fullscreen", "--no-terminal",
                 "--cursor-autohide=always", "--cursor-autohide-fs-only",
                 "--input-ipc-server=/run/svf-kiosk/mpv.sock", "--loop-playlist=inf",
                 "--osd-font=DejaVu Sans", "--osd-font-size=32"):
        assert flag in cmd
    assert not any("wayland" in a.lower() or "gpu-context=wayland" in a for a in cmd)


def test_osd_escape():
    assert osd_escape("a$b{c}\\d") == "a$$b(c)/d"


@pytest.mark.parametrize("code,value,expected", [
    (2, 1, "1"), (10, 1, "9"), (79, 1, "1"), (73, 1, "9"), (1, 1, "esc"), (158, 1, "esc"),
    (28, 1, "ok"), (352, 1, "ok"), (139, 1, "menu"), (103, 2, "up"), (108, 1, "down"),
    (2, 0, None), (2, 2, None), (999, 1, None), (11, 1, None),
])
def test_key_from_event(code, value, expected):
    assert key_from_event(code, value) == expected


# ---- ambient loop ---------------------------------------------------
def test_start_plays_first_video(env):
    ctl, _, mpv, *_ = env
    ctl.start()
    assert ctl.mode == AMBIENT and name_of(ctl) == "Video A"
    assert mpv.loaded == [str(env[5] / "A.mp4")]


def test_ambient_rotates_and_wraps(env):
    ctl, _, mpv, clock, *_ = env
    ctl.start()
    seen = [name_of(ctl)]
    for _ in range(4):
        finish(ctl, mpv, clock)
        seen.append(name_of(ctl))
    assert seen == ["Video A", "Video B", "Video C", "Video A", "Video B"]


def test_no_advance_while_playing_or_in_grace(env):
    ctl, _, mpv, clock, *_ = env
    ctl.start()
    mpv.idle = True
    ctl.tick()  # still inside the start grace period
    assert name_of(ctl) == "Video A"
    clock.advance(2)
    mpv.idle = False
    ctl.tick()
    assert name_of(ctl) == "Video A"


def test_empty_playlist_shows_standby(env):
    ctl, db, mpv, clock, *_ = env
    db.set_playlist([])
    ctl.start()
    assert ctl.mode == EMPTY
    assert S.MSG_BOOT_EMPTY in mpv.osds
    n = len(mpv.osds)
    clock.advance(1)
    ctl.tick()
    assert len(mpv.osds) == n  # not re-sent before the interval
    clock.advance(6)
    ctl.tick()
    assert len(mpv.osds) == n + 1


def test_standby_starts_ambient_when_playlist_filled(env):
    ctl, db, mpv, clock, ids, _ = env
    db.set_playlist([])
    ctl.start()
    db.set_playlist([ids["B"]])
    clock.advance(6)
    ctl.tick()
    assert ctl.mode == AMBIENT and name_of(ctl) == "Video B"


def test_playlist_emptied_during_ambient_goes_to_standby(env):
    ctl, db, mpv, clock, *_ = env
    ctl.start()
    db.set_playlist([])
    finish(ctl, mpv, clock)
    assert ctl.mode == EMPTY


def test_playlist_edit_is_picked_up_without_restart(env):
    ctl, db, mpv, clock, ids, _ = env
    ctl.start()
    db.set_playlist([ids["D"], ids["A"]])
    clock.advance(6)
    ctl.tick()
    assert [v["display_title"] for v in ctl.playlist] == ["Video D", "Video A"]
    assert name_of(ctl) == "Video A" and ctl.index == 1  # keeps playing the current video
    finish(ctl, mpv, clock)
    assert name_of(ctl) == "Video D"


def test_missing_file_is_skipped(env):
    ctl, _, mpv, _, _, root = env
    (root / "A.mp4").unlink()
    ctl.start()
    assert name_of(ctl) == "Video B"


def test_all_files_missing_falls_back_to_standby(env):
    ctl, _, mpv, _, _, root = env
    for n in "ABC":
        (root / f"{n}.mp4").unlink()
    ctl.start()
    assert ctl.mode == EMPTY and S.MSG_BOOT_EMPTY in mpv.osds


# ---- presets and resumption ------------------------------------------
def test_preset_interrupts_and_shows_osd(env):
    ctl, db, mpv, _, ids, root = env
    db.set_remote_preset(4, ids["D"])
    ctl.start()
    ctl.handle_key("4")
    assert ctl.mode == ONDEMAND and name_of(ctl) == "Video D"
    assert mpv.loaded[-1] == str(root / "D.mp4")
    assert mpv.osds[-1] == S.MSG_OSD_TRIGGER.format(title="Video D")
    assert ("osd", S.MSG_OSD_TRIGGER.format(title="Video D"), 3000) in mpv.calls


def test_unmapped_preset_does_nothing_but_inform(env):
    ctl, _, mpv, *_ = env
    ctl.start()
    ctl.handle_key("7")
    assert ctl.mode == AMBIENT and name_of(ctl) == "Video A"
    assert mpv.osds[-1] == S.MSG_DAEMON_PRESET_EMPTY.format(key=7)


@pytest.mark.parametrize("interrupted,expected", [(0, "Video B"), (1, "Video C"), (2, "Video A")])
def test_resume_after_natural_end_plays_next_video(env, interrupted, expected):
    ctl, db, mpv, clock, ids, _ = env
    db.set_remote_preset(1, ids["D"])
    ctl.start()
    for _ in range(interrupted):
        finish(ctl, mpv, clock)
    ctl.handle_key("1")
    finish(ctl, mpv, clock)
    assert ctl.mode == AMBIENT and name_of(ctl) == expected
    assert mpv.osds[-1] == S.MSG_OSD_RESUME_NEXT


def test_resume_after_esc_plays_next_video_not_the_interrupted(env):
    ctl, db, mpv, clock, ids, root = env
    db.set_remote_preset(1, ids["D"])
    ctl.start()
    finish(ctl, mpv, clock)  # now playing B
    ctl.handle_key("1")
    ctl.handle_key("esc")
    assert name_of(ctl) == "Video C"
    assert mpv.loaded[-1] == str(root / "C.mp4")
    assert mpv.osds[-1] == S.MSG_OSD_RESUME_NEXT


def test_second_preset_keeps_original_interrupted_index(env):
    ctl, db, mpv, clock, ids, _ = env
    db.set_remote_preset(1, ids["D"])
    db.set_remote_preset(2, ids["C"])
    ctl.start()
    ctl.handle_key("1")
    ctl.handle_key("2")
    assert name_of(ctl) == "Video C" and ctl.mode == ONDEMAND
    ctl.handle_key("esc")
    assert name_of(ctl) == "Video B"  # next after A, the real interrupted video


def test_esc_during_ambient_is_ignored(env):
    ctl, _, mpv, *_ = env
    ctl.start()
    n = len(mpv.calls)
    ctl.handle_key("esc")
    assert len(mpv.calls) == n and name_of(ctl) == "Video A"


def test_resume_wraps_when_single_item_playlist(env):
    ctl, db, mpv, clock, ids, _ = env
    db.set_playlist([ids["A"]])
    db.set_remote_preset(1, ids["D"])
    ctl.start()
    ctl.handle_key("1")
    finish(ctl, mpv, clock)
    assert name_of(ctl) == "Video A"


def test_on_demand_from_empty_playlist_then_standby(env):
    ctl, db, mpv, clock, ids, _ = env
    db.set_playlist([])
    db.set_remote_preset(1, ids["D"])
    ctl.start()
    ctl.handle_key("1")
    assert ctl.mode == ONDEMAND
    finish(ctl, mpv, clock)
    assert ctl.mode == EMPTY


def test_preset_with_missing_file_reports_error(env):
    ctl, db, mpv, _, ids, root = env
    db.set_remote_preset(1, ids["D"])
    (root / "D.mp4").unlink()
    ctl.start()
    ctl.handle_key("1")
    assert ctl.mode == AMBIENT
    assert "Video D" in mpv.osds[-1] and mpv.osds[-1].startswith("ERRORE")


def test_preset_for_deleted_video_is_unmapped(env):
    ctl, db, mpv, _, ids, root = env
    db.set_remote_preset(1, ids["D"])
    db.soft_delete_video(ids["D"], root / "trash")
    ctl.start()
    ctl.handle_key("1")
    assert ctl.mode == AMBIENT


# ---- carousel menu ----------------------------------------------------
def test_menu_opens_navigates_wraps_and_selects(env):
    ctl, _, mpv, *_ = env
    ctl.start()
    ctl.handle_key("menu")
    assert ctl.menu_open and ctl.menu_cursor == 0
    ctl.handle_key("down")
    ctl.handle_key("down")
    assert ctl.menu_cursor == 2
    ctl.handle_key("down")
    assert ctl.menu_cursor == 3  # D is the 4th available video
    ctl.handle_key("down")
    assert ctl.menu_cursor == 0  # wraps
    ctl.handle_key("up")
    assert ctl.menu_cursor == 3
    ctl.handle_key("ok")
    assert not ctl.menu_open and ctl.mode == ONDEMAND and name_of(ctl) == "Video D"


def test_ok_opens_menu_when_closed(env):
    ctl, *_ = env
    ctl.start()
    ctl.handle_key("ok")
    assert ctl.menu_open


def test_menu_renders_lower_third_with_titles(env):
    ctl, _, mpv, *_ = env
    ctl.start()
    ctl.handle_key("menu")
    text = mpv.osds[-1]
    assert "{\\an2}" in text and "Video A" in text and S.UI_MENU_HINT in text


def test_esc_closes_menu_without_aborting(env):
    ctl, db, mpv, _, ids, _ = env
    db.set_remote_preset(1, ids["D"])
    ctl.start()
    ctl.handle_key("1")
    ctl.handle_key("menu")
    ctl.handle_key("esc")
    assert not ctl.menu_open and ctl.mode == ONDEMAND


def test_menu_times_out(env):
    ctl, _, mpv, clock, *_ = env
    ctl.start()
    ctl.handle_key("menu")
    clock.advance(11)
    ctl.tick()
    assert not ctl.menu_open


def test_menu_toggle_with_menu_key(env):
    ctl, *_ = env
    ctl.start()
    ctl.handle_key("menu")
    ctl.handle_key("menu")
    assert not ctl.menu_open


def test_menu_ignored_when_archive_empty(tmp_path):
    db = Database(tmp_path)
    mpv = FakeMpv()
    ctl = PlaybackController(db, mpv, Clock())
    ctl.start()
    ctl.handle_key("menu")
    assert not ctl.menu_open


def test_up_down_ignored_when_menu_closed(env):
    ctl, _, mpv, *_ = env
    ctl.start()
    n = len(mpv.calls)
    ctl.handle_key("up")
    ctl.handle_key("down")
    assert len(mpv.calls) == n


# ---- recovery ---------------------------------------------------------
def test_recover_replays_current_ambient_video(env):
    ctl, _, mpv, clock, *_ = env
    ctl.start()
    finish(ctl, mpv, clock)
    ctl.recover()
    assert mpv.loaded[-1].endswith("B.mp4") and name_of(ctl) == "Video B"


def test_recover_keeps_on_demand_state_and_index(env):
    ctl, db, mpv, clock, ids, _ = env
    db.set_remote_preset(1, ids["D"])
    ctl.start()
    ctl.handle_key("1")
    ctl.recover()
    assert mpv.loaded[-1].endswith("D.mp4") and ctl.mode == ONDEMAND
    ctl.handle_key("esc")
    assert name_of(ctl) == "Video B"


def test_recover_when_empty_shows_standby(env):
    ctl, db, mpv, *_ = env
    db.set_playlist([])
    ctl.start()
    n = len(mpv.osds)
    ctl.recover()
    assert len(mpv.osds) == n + 1


def test_mpv_error_propagates_from_tick(env):
    ctl, _, mpv, clock, *_ = env
    ctl.start()
    clock.advance(2)
    mpv.fail = True
    with pytest.raises(MpvIpcError):
        ctl.tick()


# ---- supervisor ---------------------------------------------------------
class FakeProc:
    def __init__(self, dead=False):
        self.dead = dead
        self.terminated = self.killed = False

    def poll(self):
        return 1 if self.dead else None

    def terminate(self):
        self.terminated = True
        self.dead = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def make_supervisor(tmp_path, procs):
    launched = []

    def popen(cmd, env=None):
        launched.append((cmd, env))
        return procs.pop(0)

    sup = MpvSupervisor(str(tmp_path / "run" / "mpv.sock"), popen=popen)
    return sup, launched


def test_supervisor_starts_with_x11_env_and_no_wayland(tmp_path, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    sup, launched = make_supervisor(tmp_path, [FakeProc()])
    sup.start()
    cmd, env = launched[0]
    assert env["DISPLAY"] == ":0" and "WAYLAND_DISPLAY" not in env
    assert f"--input-ipc-server={sup.socket_path}" in cmd


def test_supervisor_removes_stale_socket_on_start(tmp_path):
    sup, _ = make_supervisor(tmp_path, [FakeProc()])
    os.makedirs(os.path.dirname(sup.socket_path))
    open(sup.socket_path, "w").close()
    sup.start()
    assert not os.path.exists(sup.socket_path)


def test_watchdog_restarts_dead_mpv(tmp_path):
    first, second = FakeProc(), FakeProc()
    sup, launched = make_supervisor(tmp_path, [first, second])
    sup.start()
    assert sup.ensure_running() is False
    first.dead = True
    assert sup.ensure_running() is True
    assert sup.proc is second and sup.restarts == 1 and len(launched) == 2
    assert sup.ensure_running() is False


def test_stop_terminates_and_removes_socket(tmp_path):
    proc = FakeProc()
    sup, _ = make_supervisor(tmp_path, [proc])
    sup.start()
    open(sup.socket_path, "w").close()
    sup.stop()
    assert proc.terminated and not os.path.exists(sup.socket_path)


def test_stop_kills_when_terminate_times_out(tmp_path):
    import subprocess

    class Stubborn(FakeProc):
        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            if not self.killed:
                raise subprocess.TimeoutExpired("mpv", timeout)

    proc = Stubborn()
    sup, _ = make_supervisor(tmp_path, [proc])
    sup.start()
    sup.stop()
    assert proc.killed


def test_wait_for_socket(tmp_path):
    sup, _ = make_supervisor(tmp_path, [FakeProc()])
    sup.start()
    assert sup.wait_for_socket(0.2) is False
    open(sup.socket_path, "w").close()
    assert sup.wait_for_socket(0.2) is True


def test_wait_for_socket_gives_up_when_process_dies(tmp_path):
    sup, _ = make_supervisor(tmp_path, [FakeProc(dead=True)])
    sup.start()
    assert sup.wait_for_socket(1) is False


# ---- run loop ------------------------------------------------------------
def test_run_graceful_shutdown_and_restart(tmp_path, monkeypatch):
    db = Database(tmp_path)
    f = tmp_path / "A.mp4"
    f.write_bytes(b"x")
    vid = db.add_video(str(f), "A")
    db.set_playlist([vid])
    procs = [FakeProc(), FakeProc()]
    sup, launched = make_supervisor(tmp_path, procs)
    calls = []
    monkeypatch.setattr(kp.MpvClient, "load_file", lambda self, p, mode="replace": calls.append(p))
    monkeypatch.setattr(kp.MpvClient, "resume", lambda self: None)
    monkeypatch.setattr(kp.MpvClient, "show_osd", lambda self, *a: None)
    monkeypatch.setattr(kp.MpvClient, "get_property", lambda self, n: False)

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(kp.run(db, sup, stop, devices=[], tick_seconds=0.05))
        await asyncio.sleep(0.3)
        sup.proc.dead = True  # simulate an mpv crash
        await asyncio.sleep(0.4)
        os.kill(os.getpid(), signal.SIGTERM)  # graceful shutdown through the signal handler
        await asyncio.wait_for(task, 3)

    asyncio.run(scenario())
    assert len(launched) == 2 and len(calls) >= 2  # restarted and replayed
    assert procs == [] and not os.path.exists(sup.socket_path)


def test_listen_remote_without_devices_returns(monkeypatch):
    asyncio.run(asyncio.wait_for(kp.listen_remote(lambda k: None, devices=[]), 2))


def test_listen_remote_without_evdev_returns(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "evdev":
            raise ImportError
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    asyncio.run(asyncio.wait_for(kp.listen_remote(lambda k: None), 2))


def test_find_input_devices(tmp_path):
    for n in (2, 1):
        (tmp_path / f"event{n}").touch()
    assert kp.find_input_devices(str(tmp_path / "event*")) == [
        str(tmp_path / "event1"), str(tmp_path / "event2")]


def test_main_runs_and_defaults_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(kp, "run", lambda: asyncio.sleep(0))
    assert kp.main() == 0
    assert os.environ["DISPLAY"] == ":0"


# ---- gap closing: controller branches -----------------------------------
def test_reload_keeps_following_current_video_when_playlist_reordered(env):
    ctl, db, mpv, clock, ids, _ = env
    ctl.start()
    finish(ctl, mpv, clock)  # B playing
    db.set_playlist([ids["C"], ids["B"], ids["A"]])
    ctl.reload_playlist()
    assert ctl.index == 1 and name_of(ctl) == "Video B"


def test_reload_when_current_video_removed_clamps_index(env):
    ctl, db, mpv, clock, ids, _ = env
    ctl.start()
    finish(ctl, mpv, clock)
    finish(ctl, mpv, clock)  # C playing, index 2
    db.set_playlist([ids["A"]])
    ctl.reload_playlist()
    assert ctl.index == 0
    finish(ctl, mpv, clock)
    assert name_of(ctl) == "Video A"


def test_reload_during_standby_clamps_index(env):
    ctl, db, *_ = env
    ctl.mode, ctl.index = EMPTY, 7
    ctl.reload_playlist()
    assert ctl.index == 2


def test_playlist_not_reloaded_during_on_demand(env):
    ctl, db, mpv, clock, ids, _ = env
    db.set_remote_preset(1, ids["D"])
    ctl.start()
    ctl.handle_key("1")
    db.set_playlist([ids["B"]])
    clock.advance(10)
    ctl.tick()
    assert len(ctl.playlist) == 3


def test_resume_uses_playlist_edited_during_on_demand(env):
    ctl, db, mpv, clock, ids, _ = env
    db.set_remote_preset(1, ids["D"])
    ctl.start()
    ctl.handle_key("1")
    db.set_playlist([ids["A"], ids["C"]])
    finish(ctl, mpv, clock)
    assert name_of(ctl) == "Video C"


def test_recover_when_current_file_vanished_restarts_rotation(env):
    ctl, _, mpv, _, _, root = env
    ctl.start()
    (root / "A.mp4").unlink()
    ctl.recover()
    assert name_of(ctl) == "Video B"


def test_recover_during_menu_keeps_menu_state_consistent(env):
    ctl, *_ = env
    ctl.start()
    ctl.handle_key("menu")
    ctl.recover()
    ctl.handle_key("esc")
    assert not ctl.menu_open


def test_menu_cursor_starts_on_current_video(env):
    ctl, _, mpv, clock, *_ = env
    ctl.start()
    finish(ctl, mpv, clock)
    ctl.handle_key("menu")
    assert ctl.menu_cursor == 1


def test_menu_includes_archive_videos_not_in_playlist(env):
    ctl, *_ = env
    ctl.start()
    ctl.handle_key("menu")
    assert [v["display_title"] for v in ctl._menu_videos] == ["Video A", "Video B", "Video C", "Video D"]


@pytest.mark.parametrize("count", [1, 2, 3])
def test_menu_rendering_with_few_videos(tmp_path, count):
    db = Database(tmp_path)
    for i in range(count):
        f = tmp_path / f"{i}.mp4"
        f.write_bytes(b"x")
        db.add_video(str(f), f"T{i}")
    mpv = FakeMpv()
    ctl = PlaybackController(db, mpv, Clock())
    ctl.start()
    ctl.handle_key("menu")
    text = mpv.osds[-1]
    assert text.count("▶ ") >= 1 and "T0" in text
    assert ("◀ T" in text.replace("▶ T0 ◀", "")) == (count > 2)
    ctl.handle_key("down")
    ctl.handle_key("up")
    assert ctl.menu_cursor == 0


def test_menu_titles_are_escaped(tmp_path):
    db = Database(tmp_path)
    f = tmp_path / "x.mp4"
    f.write_bytes(b"x")
    db.add_video(str(f), "A ${pause} {\\b1}")
    mpv = FakeMpv()
    ctl = PlaybackController(db, mpv, Clock())
    ctl.start()
    ctl.handle_key("menu")
    text = mpv.osds[-1]
    assert "$$(pause)" in text and "{\\b1}" not in text and "(/b1)" in text


def test_trigger_osd_title_is_escaped(env):
    ctl, db, mpv, _, ids, root = env
    f = root / "E.mp4"
    f.write_bytes(b"x")
    vid = db.add_video(str(f), "Titolo $x {y}")
    db.set_remote_preset(5, vid)
    ctl.start()
    ctl.handle_key("5")
    assert mpv.osds[-1] == S.MSG_OSD_TRIGGER.format(title="Titolo $$x (y)")


def test_menu_selection_from_standby_plays_on_demand(env):
    ctl, db, mpv, clock, *_ = env
    db.set_playlist([])
    ctl.start()
    ctl.handle_key("menu")
    ctl.handle_key("ok")
    assert ctl.mode == ONDEMAND
    ctl.handle_key("esc")
    assert ctl.mode == EMPTY


def test_mpv_error_in_handle_key_propagates(env):
    ctl, db, mpv, _, ids, _ = env
    db.set_remote_preset(1, ids["D"])
    ctl.start()
    mpv.fail = True
    with pytest.raises(MpvIpcError):
        ctl.handle_key("1")


def test_unknown_key_names_are_ignored(env):
    ctl, _, mpv, *_ = env
    ctl.start()
    n = len(mpv.calls)
    ctl.handle_key("zzz")
    assert len(mpv.calls) == n


def test_every_digit_key_code_maps_once():
    digits = sorted(v for v in kp.KEY_CODES.values() if v.isdigit())
    assert digits == sorted(list("123456789") * 2)
    assert {kp.KEY_CODES[c] for c in (2, 3, 4, 5, 6, 7, 8, 9, 10)} == set("123456789")


def test_missing_mpv_state_after_restart_keeps_index(env):
    ctl, _, mpv, clock, *_ = env
    ctl.start()
    finish(ctl, mpv, clock)
    before = ctl.index
    ctl.recover()
    finish(ctl, mpv, clock)
    assert before == 1 and name_of(ctl) == "Video C"


# ---- gap closing: run loop errors, wayland, main ---------------------------
def _run_for(db, sup, seconds=0.4, **patches):
    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(kp.run(db, sup, stop, devices=[], tick_seconds=0.05))
        await asyncio.sleep(seconds)
        stop.set()
        await asyncio.wait_for(task, 3)
    asyncio.run(scenario())


def test_run_survives_mpv_errors_and_logs_them(tmp_path, monkeypatch, caplog):
    db = Database(tmp_path)
    f = tmp_path / "A.mp4"
    f.write_bytes(b"x")
    db.set_playlist([db.add_video(str(f), "A")])
    sup, _ = make_supervisor(tmp_path, [FakeProc()])
    attempts = []

    def boom(self, *a, **k):
        attempts.append(1)
        raise MpvIpcError("down")

    monkeypatch.setattr(kp.MpvClient, "load_file", boom)
    with caplog.at_level("WARNING", logger="svf-kiosk"):
        _run_for(db, sup)
    assert attempts and "mpv error" in caplog.text


def test_run_logs_when_mpv_socket_never_appears(tmp_path, monkeypatch, caplog):
    db = Database(tmp_path)
    sup, _ = make_supervisor(tmp_path, [FakeProc(dead=True), FakeProc()])
    monkeypatch.setattr(kp.MpvClient, "stop", lambda self: None)
    monkeypatch.setattr(kp.MpvClient, "show_osd", lambda self, *a: None)
    with caplog.at_level("ERROR", logger="svf-kiosk"):
        _run_for(db, sup, 0.3)
    assert S.MSG_DAEMON_MPV_START_FAILED in caplog.text


def test_main_warns_on_wayland(monkeypatch, caplog):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(kp, "run", lambda: asyncio.sleep(0))
    with caplog.at_level("WARNING", logger="svf-kiosk"):
        kp.main()
    assert "X11 only" in caplog.text


def test_main_module_entry_point_exists():
    from importlib.metadata import entry_points
    names = {e.name: e.value for e in entry_points(group="console_scripts")}
    assert names.get("svf-kiosk-daemon") == "src.daemon.kiosk_player:main"


# ---- gap closing: evdev listener with a fake evdev -------------------------
class FakeEvdevModule:
    class ecodes:
        EV_KEY = 1

    def __init__(self, devices):
        self.devices = devices

    def InputDevice(self, path):
        dev = self.devices[path]
        if isinstance(dev, Exception):
            raise dev
        return dev


class FakeEvent:
    def __init__(self, type_, code, value):
        self.type, self.code, self.value = type_, code, value


class FakeDevice:
    def __init__(self, path, events, caps=(1,), fail=False):
        self.path, self._events, self._caps, self._fail = path, events, caps, fail

    def capabilities(self):
        return {c: [] for c in self._caps}

    async def async_read_loop(self):
        for ev in self._events:
            yield ev
            await asyncio.sleep(0)
        if self._fail:
            raise OSError("gone")


@pytest.fixture
def fake_evdev(monkeypatch):
    def install(devices):
        module = FakeEvdevModule(devices)
        monkeypatch.setitem(__import__("sys").modules, "evdev", module)
        return module
    return install


def test_listen_remote_dispatches_presses_only(fake_evdev):
    events = [FakeEvent(1, 3, 1), FakeEvent(1, 3, 0), FakeEvent(0, 3, 1), FakeEvent(1, 1, 1),
              FakeEvent(1, 108, 2), FakeEvent(1, 3, 2), FakeEvent(1, 999, 1)]
    fake_evdev({"/dev/input/event1": FakeDevice("/dev/input/event1", events)})
    keys = []
    asyncio.run(kp.listen_remote(keys.append, ["/dev/input/event1"]))
    assert keys == ["2", "esc", "down"]


def test_listen_remote_merges_several_devices(fake_evdev):
    fake_evdev({
        "a": FakeDevice("a", [FakeEvent(1, 2, 1)]),
        "b": FakeDevice("b", [FakeEvent(1, 3, 1)]),
    })
    keys = []
    asyncio.run(kp.listen_remote(keys.append, ["a", "b"]))
    assert sorted(keys) == ["1", "2"]


def test_listen_remote_skips_non_key_and_unreadable_devices(fake_evdev, caplog):
    fake_evdev({
        "mouse": FakeDevice("mouse", [FakeEvent(1, 2, 1)], caps=(2,)),
        "denied": PermissionError("no"),
        "kbd": FakeDevice("kbd", [FakeEvent(1, 4, 1)]),
    })
    keys = []
    asyncio.run(kp.listen_remote(keys.append, ["mouse", "denied", "kbd"]))
    assert keys == ["3"]


def test_listen_remote_warns_when_nothing_usable(fake_evdev, caplog):
    fake_evdev({"x": PermissionError("no")})
    with caplog.at_level("WARNING", logger="svf-kiosk"):
        asyncio.run(kp.listen_remote(lambda k: None, ["x"]))
    assert S.MSG_DAEMON_NO_REMOTE in caplog.text


def test_listen_remote_survives_device_unplug(fake_evdev, caplog):
    fake_evdev({
        "gone": FakeDevice("gone", [FakeEvent(1, 2, 1)], fail=True),
        "ok": FakeDevice("ok", [FakeEvent(1, 3, 1), FakeEvent(1, 4, 1)]),
    })
    keys = []
    with caplog.at_level("WARNING", logger="svf-kiosk"):
        asyncio.run(kp.listen_remote(keys.append, ["gone", "ok"]))
    assert sorted(keys) == ["1", "2", "3"] and "disappeared" in caplog.text


def test_listen_remote_logs_missing_evdev(monkeypatch, caplog):
    import builtins
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__",
                        lambda n, *a, **k: (_ for _ in ()).throw(ImportError()) if n == "evdev" else real(n, *a, **k))
    with caplog.at_level("WARNING", logger="svf-kiosk"):
        asyncio.run(kp.listen_remote(lambda k: None))
    assert S.MSG_DAEMON_NO_EVDEV in caplog.text


def test_run_wires_remote_keys_to_controller(tmp_path, monkeypatch, fake_evdev):
    db = Database(tmp_path)
    ids = []
    for n in "AB":
        f = tmp_path / f"{n}.mp4"
        f.write_bytes(b"x")
        ids.append(db.add_video(str(f), n))
    db.set_playlist([ids[0]])
    db.set_remote_preset(2, ids[1])
    loaded = []
    monkeypatch.setattr(kp.MpvClient, "load_file", lambda self, p, mode="replace": loaded.append(p))
    monkeypatch.setattr(kp.MpvClient, "resume", lambda self: None)
    monkeypatch.setattr(kp.MpvClient, "show_osd", lambda self, *a: None)
    monkeypatch.setattr(kp.MpvClient, "get_property", lambda self, n: False)
    fake_evdev({"k": FakeDevice("k", [FakeEvent(1, 3, 1)])})
    sup, _ = make_supervisor(tmp_path, [FakeProc()])

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(kp.run(db, sup, stop, devices=["k"], tick_seconds=0.05))
        await asyncio.sleep(0.4)
        stop.set()
        await asyncio.wait_for(task, 3)

    asyncio.run(scenario())
    assert loaded[-1].endswith("B.mp4")


def test_supervisor_survives_missing_mpv_binary(tmp_path, caplog):
    def popen(cmd, env=None):
        raise FileNotFoundError("mpv")

    sup = MpvSupervisor(str(tmp_path / "mpv.sock"), popen=popen)
    with caplog.at_level("ERROR", logger="svf-kiosk"):
        sup.start()
    assert sup.proc is None and not sup.is_alive()
    assert S.MSG_DAEMON_MPV_START_FAILED in caplog.text
    assert sup.ensure_running() is False  # retries are rate limited, no tight loop


def test_supervisor_retries_missing_mpv_after_interval(tmp_path):
    attempts = []

    def popen(cmd, env=None):
        attempts.append(1)
        raise FileNotFoundError("mpv")

    sup = MpvSupervisor(str(tmp_path / "mpv.sock"), popen=popen)
    sup.start()
    sup._last_attempt -= kp.RETRY_INTERVAL + 1
    assert sup.ensure_running() is True
    assert len(attempts) == 2


def test_run_in_worker_thread_does_not_crash_on_signal_setup(tmp_path):
    import threading
    db = Database(tmp_path)
    sup, _ = make_supervisor(tmp_path, [FakeProc()])
    errors = []

    def target():
        try:
            async def scenario():
                stop = asyncio.Event()
                task = asyncio.create_task(kp.run(db, sup, stop, devices=[], tick_seconds=0.05))
                await asyncio.sleep(0.2)
                stop.set()
                await asyncio.wait_for(task, 3)
            asyncio.run(scenario())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=target)
    t.start()
    t.join(10)
    assert not errors


def test_module_entry_point_runs_as_script(tmp_path):
    import subprocess
    import sys
    env = {**os.environ, "SVF_ROOT": str(tmp_path), "PATH": "/nonexistent", "SVF_IPC_SOCK": str(tmp_path / "m.sock")}
    proc = subprocess.Popen([sys.executable, "-m", "src.daemon.kiosk_player"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        import time
        time.sleep(2)
        assert proc.poll() is None  # still alive although mpv is missing
    finally:
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=10)
    assert proc.returncode == 0
    assert S.MSG_BOOT_START in out and S.MSG_DAEMON_MPV_START_FAILED in out
