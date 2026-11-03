"""SVF Kiosk playback daemon: ambient loop, Bluetooth remote, mpv supervision (X11 only)."""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable

from ..core.mpv_client import MpvClient, MpvIpcError, default_socket_path
from ..core.strings import ItalianStrings as S
from ..db.database import Database

log = logging.getLogger("svf-kiosk")

AMBIENT, ONDEMAND, EMPTY = "ambient", "ondemand", "empty"
OSD_MS = 3000
START_GRACE = 1.5
RELOAD_INTERVAL = 5.0
STANDBY_INTERVAL = 5.0
MENU_TIMEOUT = 10.0
WATCHDOG_DEADLINE = 3.0
RETRY_INTERVAL = 3.0

# Linux input event codes -> logical remote keys.
KEY_CODES: dict[int, str] = {
    1: "esc", 158: "esc", 223: "esc",              # ESC, BACK, CANCEL
    28: "ok", 96: "ok", 352: "ok", 353: "ok",      # ENTER, KPENTER, OK, SELECT
    139: "menu", 103: "up", 108: "down",           # MENU, UP, DOWN
    **{code: str(n) for n, code in enumerate(range(2, 11), 1)},            # 1..9
    **{code: str(n) for n, code in zip((7, 8, 9), (71, 72, 73))},          # keypad 7..9
    **{code: str(n) for n, code in zip((4, 5, 6), (75, 76, 77))},          # keypad 4..6
    **{code: str(n) for n, code in zip((1, 2, 3), (79, 80, 81))},          # keypad 1..3
}


def next_index(interrupted_index: int, total: int) -> int:
    """Resumption policy: the NEXT scheduled video after the interrupted one."""
    if total <= 0:
        return 0
    return (interrupted_index + 1) % total


def mpv_command_line(socket_path: str) -> list[str]:
    return [
        "mpv", "--idle=yes", "--force-window=yes", "--vo=gpu", "--hwdec=auto-safe", "--fullscreen",
        "--no-terminal", "--cursor-autohide=always", "--cursor-autohide-fs-only",
        f"--input-ipc-server={socket_path}", "--loop-playlist=inf",
        "--osd-font=DejaVu Sans", "--osd-font-size=32",
    ]


def osd_escape(text: str) -> str:
    """Make a title safe for mpv ``show-text`` (property expansion and ASS tags)."""
    return text.replace("$", "$$").replace("{", "(").replace("}", ")").replace("\\", "/")


class PlaybackController:
    """All playback decisions; talks to mpv only through the injected client."""

    def __init__(self, db: Database, mpv: MpvClient, clock: Callable[[], float] = time.monotonic,
                 exists: Callable[[str], bool] = os.path.exists) -> None:
        self.db, self.mpv, self.clock, self.exists = db, mpv, clock, exists
        self.playlist: list[dict] = []
        self.mode = EMPTY
        self.index = 0                      # current (ambient) or interrupted index
        self.current: dict | None = None    # video being played right now
        self.menu_open = False
        self.menu_cursor = 0
        self._menu_videos: list[dict] = []
        self._menu_deadline = 0.0
        self._grace_until = 0.0
        self._next_reload = 0.0
        self._next_standby = 0.0

    # ---- playlist ---------------------------------------------------
    def reload_playlist(self) -> None:
        new = self.db.get_playlist()
        if [v["id"] for v in new] == [v["id"] for v in self.playlist]:
            self.playlist = new
            return
        current_id = self.current["id"] if self.current else None
        self.playlist = new
        if self.mode == AMBIENT and current_id is not None:
            ids = [v["id"] for v in new]
            if current_id in ids:
                self.index = ids.index(current_id)
            elif new:
                self.index = min(self.index, len(new) - 1)
        elif new:
            self.index = min(self.index, len(new) - 1)

    def start(self) -> None:
        self.reload_playlist()
        self._enter_ambient(0)

    def _enter_ambient(self, index: int) -> None:
        total = len(self.playlist)
        for offset in range(total):
            candidate = (index + offset) % total
            video = self.playlist[candidate]
            if self.exists(video["file_path"]):
                self.mode, self.index, self.current = AMBIENT, candidate, video
                self._load(video["file_path"])
                return
            log.warning("Missing media file: %s", video["file_path"])
        self.mode, self.current = EMPTY, None
        self._show_standby()

    def _load(self, path: str) -> None:
        self.mpv.load_file(path)
        self.mpv.resume()
        self._grace_until = self.clock() + START_GRACE

    def _show_standby(self) -> None:
        self.mpv.stop()
        self.mpv.show_osd(S.MSG_BOOT_EMPTY, int(STANDBY_INTERVAL * 1000) + 1000)
        self._next_standby = self.clock() + STANDBY_INTERVAL

    # ---- remote keys --------------------------------------------------
    def handle_key(self, key: str) -> None:
        if key.isdigit():
            self._trigger_preset(int(key))
        elif key == "menu":
            self._toggle_menu()
        elif key == "ok":
            if self.menu_open:
                self._select_menu_item()
            else:
                self._open_menu()
        elif key == "esc":
            if self.menu_open:
                self._close_menu()
            elif self.mode == ONDEMAND:
                self._resume_after_ondemand()
        elif key in ("up", "down") and self.menu_open:
            step = -1 if key == "up" else 1
            self.menu_cursor = (self.menu_cursor + step) % len(self._menu_videos)
            self._render_menu()

    def _trigger_preset(self, key: int) -> None:
        video = self.db.get_remote_preset_video(key)
        if video is None:
            self.mpv.show_osd(S.MSG_DAEMON_PRESET_EMPTY.format(key=key), OSD_MS)
            return
        self._play_on_demand(video)

    def _play_on_demand(self, video: dict) -> None:
        if not self.exists(video["file_path"]):
            self.mpv.show_osd(osd_escape(S.MSG_DAEMON_FILE_MISSING.format(title=video["display_title"])), OSD_MS)
            return
        self._close_menu(redraw=False)
        # a second request keeps the original interrupted index
        self.mode, self.current = ONDEMAND, video
        self._load(video["file_path"])
        self.mpv.show_osd(osd_escape(S.MSG_OSD_TRIGGER.format(title=video["display_title"])), OSD_MS)

    def _resume_after_ondemand(self) -> None:
        self.reload_playlist()
        if not self.playlist:
            self.mode, self.current = EMPTY, None
            self._show_standby()
            return
        self._enter_ambient(next_index(self.index, len(self.playlist)))
        if self.mode == AMBIENT:
            self.mpv.show_osd(S.MSG_OSD_RESUME_NEXT, OSD_MS)

    # ---- carousel menu --------------------------------------------------
    def _open_menu(self) -> None:
        self._menu_videos = self.db.get_available_videos()
        if not self._menu_videos:
            return
        self.menu_open, self.menu_cursor = True, 0
        if self.current:
            for i, v in enumerate(self._menu_videos):
                if v["id"] == self.current["id"]:
                    self.menu_cursor = i
        self._render_menu()

    def _toggle_menu(self) -> None:
        if self.menu_open:
            self._close_menu()
        else:
            self._open_menu()

    def _close_menu(self, redraw: bool = True) -> None:
        was_open, self.menu_open = self.menu_open, False
        if was_open and redraw:
            self.mpv.show_osd("", 1)

    def _render_menu(self) -> None:
        videos, cur = self._menu_videos, self.menu_cursor
        n = len(videos)
        title = lambda i: osd_escape(videos[i % n]["display_title"])  # noqa: E731
        left = f"◀ {title(cur - 1)}   " if n > 2 else ""
        right = f"   {title(cur + 1)} ▶" if n > 1 else ""
        text = (f"{left}▶ {title(cur)} ◀{right}\\N{osd_escape(S.UI_MENU_HINT)}")
        self._menu_deadline = self.clock() + MENU_TIMEOUT
        self.mpv.show_osd("${osd-ass-cc/0}{\\an2}" + text + "${osd-ass-cc/1}",
                          int(MENU_TIMEOUT * 1000))

    def _select_menu_item(self) -> None:
        video = self._menu_videos[self.menu_cursor]
        self._play_on_demand(video)

    # ---- periodic work --------------------------------------------------
    def tick(self) -> None:
        now = self.clock()
        if self.menu_open and now >= self._menu_deadline:
            self.menu_open = False
        if self.mode != ONDEMAND and now >= self._next_reload:
            self._next_reload = now + RELOAD_INTERVAL
            self.reload_playlist()
        if self.mode == EMPTY:
            if self.playlist:
                self._enter_ambient(0)
            elif now >= self._next_standby:
                self._show_standby()
            return
        if now < self._grace_until:
            return
        if self.mpv.get_property("idle-active"):
            self._on_file_finished()

    def _on_file_finished(self) -> None:
        if self.mode == ONDEMAND:
            self._resume_after_ondemand()
        else:
            self.reload_playlist()
            if not self.playlist:
                self.mode, self.current = EMPTY, None
                self._show_standby()
            else:
                self._enter_ambient(next_index(self.index, len(self.playlist)))

    def recover(self) -> None:
        """Called after mpv was restarted: replay the current video, keep all state."""
        if self.current and self.mode in (AMBIENT, ONDEMAND) and self.exists(self.current["file_path"]):
            self._load(self.current["file_path"])
        elif self.mode == EMPTY:
            self._show_standby()
        else:
            self.start()


class MpvSupervisor:
    """Spawns mpv and restarts it within WATCHDOG_DEADLINE seconds when it dies."""

    def __init__(self, socket_path: str | None = None, popen=subprocess.Popen) -> None:
        self.socket_path = socket_path or default_socket_path()
        self._popen = popen
        self.proc = None
        self.restarts = 0
        self._last_attempt = 0.0

    def start(self) -> None:
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)
        self._remove_socket()
        env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
        env.pop("WAYLAND_DISPLAY", None)
        self._last_attempt = time.monotonic()
        try:
            self.proc = self._popen(mpv_command_line(self.socket_path), env=env)
        except OSError as exc:
            log.error("%s (%s)", S.MSG_DAEMON_MPV_START_FAILED, exc)
            self.proc = None

    def wait_for_socket(self, timeout: float = WATCHDOG_DEADLINE) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if Path(self.socket_path).exists():
                return True
            if self.proc is not None and self.proc.poll() is not None:
                return False
            time.sleep(0.05)
        return Path(self.socket_path).exists()

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure_running(self) -> bool:
        """Return True if mpv had to be restarted."""
        if self.is_alive():
            return False
        if self.proc is None and time.monotonic() - self._last_attempt < RETRY_INTERVAL:
            return False  # last spawn failed: do not retry in a tight loop
        log.warning(S.MSG_MPV_RESTARTING)
        self.restarts += 1
        self.start()
        return True

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self._remove_socket()

    def _remove_socket(self) -> None:
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass


def key_from_event(code: int, value: int) -> str | None:
    """Translate an evdev key event; only presses (and repeats of up/down) count."""
    name = KEY_CODES.get(code)
    if name is None or value == 0:
        return None
    if value == 2 and name not in ("up", "down"):
        return None
    return name


def find_input_devices(pattern: str = "/dev/input/event*") -> list[str]:
    return sorted(glob.glob(pattern))


async def listen_remote(on_key: Callable[[str], None], devices: list[str] | None = None) -> None:
    """Read key events from every /dev/input/event* device (needs group ``input``)."""
    try:
        import evdev
    except ImportError:
        log.warning(S.MSG_DAEMON_NO_EVDEV)
        return
    opened = []
    for path in (find_input_devices() if devices is None else devices):
        try:
            dev = evdev.InputDevice(path)
            if evdev.ecodes.EV_KEY in dev.capabilities():
                opened.append(dev)
        except OSError:
            continue
    if not opened:
        log.warning(S.MSG_DAEMON_NO_REMOTE)
        return

    async def read(dev) -> None:
        try:
            async for event in dev.async_read_loop():
                if event.type == evdev.ecodes.EV_KEY:
                    key = key_from_event(event.code, event.value)
                    if key:
                        on_key(key)
        except OSError:
            log.warning("Input device disappeared: %s", dev.path)

    await asyncio.gather(*(read(d) for d in opened))


async def run(db: Database | None = None, supervisor: MpvSupervisor | None = None,
              stop: asyncio.Event | None = None, devices: list[str] | None = None,
              tick_seconds: float = 0.5) -> None:
    db = db or Database()
    supervisor = supervisor or MpvSupervisor()
    mpv = MpvClient(supervisor.socket_path)
    controller = PlaybackController(db, mpv)
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass

    def safe(action: Callable[[], None]) -> None:
        try:
            action()
        except MpvIpcError as exc:
            log.warning("mpv error: %s", exc)

    supervisor.start()
    if not supervisor.wait_for_socket():
        log.error(S.MSG_DAEMON_MPV_START_FAILED)
    safe(controller.start)
    remote = asyncio.create_task(listen_remote(lambda k: safe(lambda: controller.handle_key(k)), devices))
    try:
        while not stop.is_set():
            if supervisor.ensure_running():
                supervisor.wait_for_socket()
                safe(controller.recover)
            else:
                safe(controller.tick)
            try:
                await asyncio.wait_for(stop.wait(), tick_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        remote.cancel()
        supervisor.stop()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        log.warning("Wayland session detected: SVF Kiosk supports X11 only.")
    os.environ.setdefault("DISPLAY", ":0")
    log.info(S.MSG_BOOT_START)
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
