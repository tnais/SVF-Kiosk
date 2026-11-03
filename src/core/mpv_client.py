"""JSON-IPC client for mpv over an AF_UNIX socket."""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import socket
import time
from pathlib import Path
from typing import Any

from .strings import ItalianStrings

DEFAULT_SOCKET = "/run/svf-kiosk/mpv.sock"


class MpvIpcError(Exception):
    """Raised when mpv cannot be reached or rejects a command."""


def default_socket_path() -> str:
    return os.environ.get("SVF_IPC_SOCK", DEFAULT_SOCKET)


class MpvClient:
    def __init__(self, socket_path: str | None = None, timeout: float = 3.0) -> None:
        self.socket_path = socket_path or default_socket_path()
        self.timeout = timeout
        self._ids = itertools.count(1)

    # ---- low level -------------------------------------------------
    def command(self, *args: Any) -> Any:
        """Send one command and return its ``data`` payload."""
        request_id = next(self._ids)
        payload = json.dumps({"command": list(args), "request_id": request_id}) + "\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                sock.sendall(payload.encode("utf-8"))
                buffer = b""
                while True:
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            reply = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if reply.get("request_id") != request_id:
                            continue  # asynchronous mpv event
                        if reply.get("error", "success") != "success":
                            raise MpvIpcError(
                                f"{ItalianStrings.MSG_MPV_UNAVAILABLE}: {reply['error']}"
                            )
                        return reply.get("data")
                    chunk = sock.recv(65536)
                    if not chunk:
                        raise MpvIpcError(ItalianStrings.MSG_MPV_UNAVAILABLE)
                    buffer += chunk
        except (OSError, socket.timeout) as exc:
            raise MpvIpcError(f"{ItalianStrings.MSG_MPV_UNAVAILABLE}: {exc}") from exc

    async def acommand(self, *args: Any) -> Any:
        """Asynchronous variant of :meth:`command`."""
        return await asyncio.to_thread(self.command, *args)

    def get_property(self, name: str) -> Any:
        return self.command("get_property", name)

    def set_property(self, name: str, value: Any) -> None:
        self.command("set_property", name, value)

    # ---- high level ------------------------------------------------
    def is_running(self) -> bool:
        if not Path(self.socket_path).exists():
            return False
        try:
            self.get_property("idle-active")
            return True
        except MpvIpcError:
            return False

    def load_file(self, path: str, mode: str = "replace") -> None:
        self.command("loadfile", path, mode)

    def load_playlist(self, file_paths: list[str]) -> None:
        self.command("playlist-clear")
        if not file_paths:
            self.command("stop")
            return
        self.command("loadfile", file_paths[0], "replace")
        for path in file_paths[1:]:
            self.command("loadfile", path, "append")

    def pause(self) -> None:
        self.set_property("pause", True)

    def resume(self) -> None:
        self.set_property("pause", False)

    def stop(self) -> None:
        self.command("stop")

    def get_playback_status(self) -> dict:
        def safe(name: str, default: Any) -> Any:
            try:
                value = self.get_property(name)
            except MpvIpcError as exc:
                if not self.is_running():
                    raise
                return default
            return default if value is None else value

        return {
            "file": safe("path", ""),
            "time_pos": float(safe("time-pos", 0.0)),
            "duration": float(safe("duration", 0.0)),
            "paused": bool(safe("pause", False)),
        }

    def show_osd(self, text: str, duration_ms: int = 3000) -> None:
        self.command("show-text", text, str(duration_ms))

    def play_preview(self, path: str, duration_sec: int = 15) -> None:
        """Pause ambient playback, preview a file, then restore the prior state."""
        previous = self.get_playback_status()
        self.pause()
        try:
            self.load_file(path)
            self.resume()
            self.show_osd(ItalianStrings.MSG_OSD_PREVIEW, duration_sec * 1000)
            time.sleep(duration_sec)
        finally:
            self._restore(previous)

    def _restore(self, previous: dict) -> None:
        if previous["file"]:
            options = f"start={previous['time_pos']:.2f}"
            self.command("loadfile", previous["file"], "replace", 0, options)
            self.set_property("pause", previous["paused"])
        else:
            self.stop()
