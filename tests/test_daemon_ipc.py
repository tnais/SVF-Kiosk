"""Controller + real MpvClient against a fake mpv JSON-IPC server on a UNIX socket."""
import json
import socket
import threading

import pytest

from src.core.mpv_client import MpvClient
from src.core.strings import ItalianStrings as S
from src.daemon.kiosk_player import AMBIENT, ONDEMAND, PlaybackController
from src.db.database import Database


class FakeMpvServer:
    def __init__(self, path):
        self.props = {"idle-active": False, "pause": False}
        self.commands = []
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(5)
        self.closed = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self.closed:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            with conn:
                data = conn.recv(65536)
                if not data:
                    continue
                req = json.loads(data.decode())
                cmd = req["command"]
                self.commands.append(cmd)
                reply = {"request_id": req["request_id"], "error": "success", "data": None}
                if cmd[0] == "get_property":
                    reply["data"] = self.props.get(cmd[1])
                if cmd[0] == "loadfile":
                    self.props["idle-active"] = False
                conn.sendall((json.dumps(reply) + "\n").encode())

    def close(self):
        self.closed = True
        self.srv.close()


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def stack(tmp_path):
    db = Database(tmp_path)
    ids = []
    for n in "ABC":
        f = tmp_path / f"{n}.mp4"
        f.write_bytes(b"x")
        ids.append(db.add_video(str(f), f"Video {n}"))
    db.set_playlist(ids[:2])
    db.set_remote_preset(3, ids[2])
    server = FakeMpvServer(str(tmp_path / "mpv.sock"))
    clock = Clock()
    ctl = PlaybackController(db, MpvClient(str(tmp_path / "mpv.sock")), clock)
    yield ctl, server, clock, tmp_path
    server.close()


def test_wire_commands_for_a_full_guide_cycle(stack):
    ctl, server, clock, root = stack
    ctl.start()
    assert ["loadfile", str(root / "A.mp4"), "replace"] in server.commands
    assert ["set_property", "pause", False] in server.commands

    ctl.handle_key("3")
    assert ctl.mode == ONDEMAND
    shown = [c for c in server.commands if c[0] == "show-text"]
    assert shown[-1] == ["show-text", S.MSG_OSD_TRIGGER.format(title="Video C"), "3000"]

    clock.t += 5
    server.props["idle-active"] = True
    ctl.tick()
    assert ctl.mode == AMBIENT
    loads = [c for c in server.commands if c[0] == "loadfile"]
    assert loads[-1] == ["loadfile", str(root / "B.mp4"), "replace"]
    assert [c for c in server.commands if c[0] == "show-text"][-1][1] == S.MSG_OSD_RESUME_NEXT


def test_standby_uses_stop_and_show_text(stack):
    ctl, server, clock, root = stack
    ctl.db.set_playlist([])
    ctl.start()
    assert ["stop"] in server.commands
    assert ["show-text", S.MSG_BOOT_EMPTY, "6000"] in server.commands


def test_end_of_file_detected_via_idle_active_property(stack):
    ctl, server, clock, root = stack
    ctl.start()
    clock.t += 5
    ctl.tick()  # not idle -> stays on A
    assert ctl.current["display_title"] == "Video A"
    server.props["idle-active"] = True
    ctl.tick()
    assert ctl.current["display_title"] == "Video B"
