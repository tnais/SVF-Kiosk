import json
import os
import socket
import shutil
import subprocess
import threading
import time

import pytest

from src.core.mpv_client import MpvClient, MpvIpcError


class MockMpv:
    def __init__(self, path, props=None):
        self.path = path
        self.props = props or {}
        self.commands = []
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(5)
        self.stop = False
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop:
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
                conn.sendall(b'{"event":"idle"}\n')
                reply = {"request_id": req["request_id"], "error": "success", "data": None}
                if cmd[0] == "get_property":
                    if cmd[1] in self.props:
                        reply["data"] = self.props[cmd[1]]
                    else:
                        reply["error"] = "property unavailable"
                conn.sendall((json.dumps(reply) + "\n").encode())

    def close(self):
        self.stop = True
        self.srv.close()


@pytest.fixture
def mock(tmp_path):
    m = MockMpv(str(tmp_path / "mpv.sock"))
    yield m
    m.close()


def test_missing_socket_raises(tmp_path):
    client = MpvClient(str(tmp_path / "none.sock"))
    assert client.is_running() is False
    with pytest.raises(MpvIpcError):
        client.pause()


def test_env_socket(monkeypatch, tmp_path):
    monkeypatch.setenv("SVF_IPC_SOCK", str(tmp_path / "x.sock"))
    assert MpvClient().socket_path.endswith("x.sock")


def test_is_running_and_commands(mock):
    client = MpvClient(mock.path)
    mock.props["idle-active"] = False
    assert client.is_running()
    client.load_file("/a.mp4")
    client.pause()
    client.resume()
    client.stop()
    client.show_osd("ciao", 1000)
    assert ["loadfile", "/a.mp4", "replace"] in mock.commands
    assert ["set_property", "pause", True] in mock.commands
    assert ["set_property", "pause", False] in mock.commands
    assert ["show-text", "ciao", "1000"] in mock.commands


def test_load_playlist(mock):
    MpvClient(mock.path).load_playlist(["/a.mp4", "/b.mp4", "/c.mp4"])
    assert mock.commands == [
        ["playlist-clear"],
        ["loadfile", "/a.mp4", "replace"],
        ["loadfile", "/b.mp4", "append"],
        ["loadfile", "/c.mp4", "append"],
    ]


def test_status(mock):
    mock.props.update({"path": "/a.mp4", "time-pos": 4.5, "duration": 60.0, "pause": True,
                       "idle-active": False})
    assert MpvClient(mock.path).get_playback_status() == {
        "file": "/a.mp4", "time_pos": 4.5, "duration": 60.0, "paused": True}


def test_error_reply(mock):
    with pytest.raises(MpvIpcError):
        MpvClient(mock.path).get_property("nope")


def test_play_preview_restores(mock, monkeypatch):
    mock.props.update({"path": "/amb.mp4", "time-pos": 10.0, "duration": 60.0,
                       "pause": False, "idle-active": False})
    monkeypatch.setattr("src.core.mpv_client.time.sleep", lambda s: None)
    MpvClient(mock.path).play_preview("/prev.mp4", 15)
    assert ["loadfile", "/prev.mp4", "replace"] in mock.commands
    assert ["loadfile", "/amb.mp4", "replace", 0, "start=10.00"] in mock.commands
    assert any(c[0] == "show-text" and c[2] == "15000" for c in mock.commands)


def test_async(mock):
    import asyncio
    mock.props["idle-active"] = False
    assert asyncio.run(MpvClient(mock.path).acommand("get_property", "idle-active")) is False


def test_timeout_raises(tmp_path):
    path = str(tmp_path / "slow.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(1)
    try:
        with pytest.raises(MpvIpcError):
            MpvClient(path, timeout=0.2).pause()
    finally:
        srv.close()


def test_connection_closed_mid_reply(tmp_path):
    path = str(tmp_path / "close.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        conn.recv(1024)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    try:
        with pytest.raises(MpvIpcError):
            MpvClient(path, timeout=1).stop()
    finally:
        srv.close()


def test_load_empty_playlist(mock):
    MpvClient(mock.path).load_playlist([])
    assert mock.commands == [["playlist-clear"], ["stop"]]


def test_status_raises_when_down(tmp_path):
    with pytest.raises(MpvIpcError):
        MpvClient(str(tmp_path / "x.sock")).get_playback_status()


def test_preview_restores_when_load_fails(mock, monkeypatch):
    mock.props.update({"path": "/amb.mp4", "time-pos": 2.0, "duration": 9.0,
                       "pause": False, "idle-active": False})
    client = MpvClient(mock.path)
    real = client.load_file

    def boom(path, mode="replace"):
        raise MpvIpcError("fail")

    monkeypatch.setattr(client, "load_file", boom)
    with pytest.raises(MpvIpcError):
        client.play_preview("/prev.mp4", 1)
    assert ["loadfile", "/amb.mp4", "replace", 0, "start=2.00"] in mock.commands


@pytest.mark.skipif(shutil.which("mpv") is None, reason="mpv not installed")
def test_real_mpv_loadfile_with_options(tmp_path):
    sock = str(tmp_path / "real.sock")
    proc = subprocess.Popen(
        ["mpv", "--idle=yes", "--vo=null", "--ao=null", "--no-config",
         f"--input-ipc-server={sock}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        client = MpvClient(sock)
        for _ in range(50):
            if client.is_running():
                break
            time.sleep(0.1)
        assert client.is_running()
        with pytest.raises(MpvIpcError):
            client.command("loadfile", "/nonexistent.mp4", "replace", 0, "start=1.00")
            client.command("bogus-command")
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def _serve_raw(tmp_path, raw_chunks):
    """One-shot server that answers with raw bytes (request_id is injected via {rid})."""
    path = str(tmp_path / "raw.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(1)
    seen = {}

    def serve():
        conn, _ = srv.accept()
        with conn:
            req = json.loads(conn.recv(65536).decode())
            seen["req"] = req
            for chunk in raw_chunks:
                conn.sendall(chunk.replace(b"{rid}", str(req["request_id"]).encode()))

    threading.Thread(target=serve, daemon=True).start()
    return path, srv, seen


def test_skips_events_malformed_lines_and_foreign_ids(tmp_path):
    path, srv, _ = _serve_raw(tmp_path, [
        b'{"event":"file-loaded"}\n',
        b'not json at all\n',
        b'\n',
        b'{"request_id":99999,"error":"success","data":"wrong"}\n',
        b'{"request_id":{rid},"error":"success","data":42}\n',
    ])
    try:
        assert MpvClient(path, timeout=1).command("get_property", "x") == 42
    finally:
        srv.close()


def test_reply_split_across_chunks(tmp_path):
    path, srv, _ = _serve_raw(tmp_path, [b'{"request_id":{rid},"er', b'ror":"success","data":7}\n'])
    try:
        assert MpvClient(path, timeout=1).command("get_property", "x") == 7
    finally:
        srv.close()


def test_osd_text_is_utf8_encoded(tmp_path):
    path, srv, seen = _serve_raw(tmp_path, [b'{"request_id":{rid},"error":"success"}\n'])
    try:
        MpvClient(path, timeout=1).show_osd("▶ Riproduzione richiesta: Locomotiva è già", 2500)
    finally:
        srv.close()
    assert seen["req"]["command"] == ["show-text", "▶ Riproduzione richiesta: Locomotiva è già", "2500"]


def test_request_ids_increment(mock):
    client = MpvClient(mock.path)
    mock.props["idle-active"] = False
    client.get_property("idle-active")
    client.get_property("idle-active")
    assert next(client._ids) == 3


def test_default_socket_path(monkeypatch):
    monkeypatch.delenv("SVF_IPC_SOCK", raising=False)
    assert MpvClient().socket_path == "/run/svf-kiosk/mpv.sock"


def test_preview_keeps_paused_state_of_ambient(mock, monkeypatch):
    mock.props.update({"path": "/amb.mp4", "time-pos": 5.0, "duration": 30.0,
                       "pause": True, "idle-active": False})
    monkeypatch.setattr("src.core.mpv_client.time.sleep", lambda s: None)
    MpvClient(mock.path).play_preview("/prev.mp4", 1)
    # the last pause command must restore the paused state
    pauses = [c for c in mock.commands if c[:2] == ["set_property", "pause"]]
    assert pauses[-1] == ["set_property", "pause", True]


def test_preview_with_idle_player_stops_afterwards(mock, monkeypatch):
    mock.props.update({"idle-active": True})
    monkeypatch.setattr("src.core.mpv_client.time.sleep", lambda s: None)
    MpvClient(mock.path).play_preview("/prev.mp4", 1)
    assert mock.commands[-1] == ["stop"]


def test_preview_sleeps_requested_duration(mock, monkeypatch):
    mock.props.update({"path": "/a.mp4", "time-pos": 1.0, "duration": 9.0,
                       "pause": False, "idle-active": False})
    sleeps = []
    monkeypatch.setattr("src.core.mpv_client.time.sleep", sleeps.append)
    MpvClient(mock.path).play_preview("/prev.mp4", 7)
    assert sleeps == [7]
