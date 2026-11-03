"""Tests for svf-restore."""

import subprocess
import time
from types import SimpleNamespace

import pytest

from src.cli import restore
from src.core.strings import ItalianStrings as S
from src.db.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path)
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    vid = d.add_video(str(f), "Alfa")
    d.set_playlist([vid])
    return d


def titles(db):
    return [v["display_title"] for v in db.get_available_videos()]


def ok_runner(cmd, **kw):
    ok_runner.calls.append(cmd)
    return SimpleNamespace(returncode=0)


ok_runner.calls = []


def make_session(db, answers):
    out, err = [], []
    it = iter(answers)
    code = restore.run(db, ask=lambda _p: next(it), out=out.append, err=err.append, runner=ok_runner)
    return code, out, err


def snapshot_then_change(db, tmp_path):
    snap = db.create_backup("manual")
    time.sleep(0.01)
    f = tmp_path / "b.mp4"
    f.write_bytes(b"x")
    db.add_video(str(f), "Bravo")
    return snap


def test_no_backups(db):
    code, _, err = make_session(db, [])
    assert code == 1 and err == [S.MSG_RESTORE_NO_BACKUPS]


def test_listing_is_newest_first(db):
    db.create_backup("a")
    time.sleep(0.01)
    newest = db.create_backup("b")
    _, out, _ = make_session(db, [""])
    assert out[0] == S.MSG_RESTORE_LIST_HEADER
    assert newest.rsplit("/", 1)[1] in out[1]


def test_empty_choice_cancels_without_changes(db, tmp_path):
    snapshot_then_change(db, tmp_path)
    before = len(db.list_backups())
    code, out, _ = make_session(db, [""])
    assert code == 0 and out[-1] == S.MSG_RESTORE_CANCELLED
    assert titles(db) == ["Alfa", "Bravo"] and len(db.list_backups()) == before


@pytest.mark.parametrize("choice", ["x", "0", "99", "-1"])
def test_invalid_choice(db, choice):
    db.create_backup("a")
    code, _, err = make_session(db, [choice])
    assert code == 2 and err == [S.MSG_RESTORE_INVALID]


def test_declined_confirmation_keeps_database(db, tmp_path):
    snapshot_then_change(db, tmp_path)
    code, out, _ = make_session(db, ["1", "n"])
    assert code == 0 and S.MSG_RESTORE_CANCELLED in out and titles(db) == ["Alfa", "Bravo"]


def test_full_restore(db, tmp_path):
    snap = snapshot_then_change(db, tmp_path)
    ok_runner.calls.clear()
    snaps = list(reversed(db.list_backups()))
    idx = [p.name for p in snaps].index(snap.rsplit("/", 1)[1]) + 1
    code, out, err = make_session(db, [str(idx), "s"])
    assert code == 0 and not err and out[-1] == S.MSG_RESTORE_DONE
    assert titles(db) == ["Alfa"]
    assert any("pre_restore" in p.name for p in db.list_backups())
    assert any("pre_restore" in line for line in out)
    assert ok_runner.calls == [restore.RESTART_COMMAND]
    assert "Alfa" in db.json_path.read_text(encoding="utf-8")
    assert "Bravo" not in db.json_path.read_text(encoding="utf-8")


def test_restore_can_undo_itself_via_safety_backup(db, tmp_path):
    snap = snapshot_then_change(db, tmp_path)
    restore.restore_snapshot(db, __import__("pathlib").Path(snap))
    assert titles(db) == ["Alfa"]
    safety = [p for p in db.list_backups() if "pre_restore" in p.name][0]
    restore.restore_snapshot(db, safety)
    assert titles(db) == ["Alfa", "Bravo"]


def test_corrupt_snapshot_refused(db):
    db.create_backup("a")
    bad = db.backup_dir / "svf_kiosk_bad_99991231_235959_000000.db"
    bad.write_bytes(b"not a database" * 100)
    code, _, err = make_session(db, ["1"])
    assert code == 1 and err == [S.MSG_RESTORE_CORRUPT.format(name=bad.name)]
    assert not any("pre_restore" in p.name for p in db.list_backups())


@pytest.mark.parametrize("exc", [None, OSError, subprocess.TimeoutExpired])
def test_restart_failure_reported(db, tmp_path, exc):
    snapshot_then_change(db, tmp_path)

    def runner(cmd, **kw):
        if exc is OSError:
            raise OSError
        if exc:
            raise exc("x", 1)
        return SimpleNamespace(returncode=1)

    out, err = [], []
    answers = iter(["1", "s"])
    code = restore.run(db, ask=lambda _p: next(answers), out=out.append, err=err.append, runner=runner)
    assert code == 1 and err == [S.MSG_RESTORE_RELOAD_FAILED] and S.MSG_RESTORE_DONE not in out


def test_main_wires_database(db, monkeypatch, capsys):
    db.create_backup("a")
    monkeypatch.setenv("SVF_ROOT", str(db.root))
    monkeypatch.setattr("builtins.input", lambda _p="": "")
    assert restore.main([]) == 0


class PlayingClient:
    def is_running(self):
        return True

    def get_property(self, name):
        return False


def test_guard_refuses_while_playing_and_force_bypasses(db, tmp_path):
    snapshot_then_change(db, tmp_path)
    out, err = [], []
    code = restore.run(db, ask=lambda _p: "", out=out.append, err=err.append, client=PlayingClient())
    assert code == 2 and err == [S.MSG_VISIT_HOUR_WARNING] and not out
    code = restore.run(db, ask=lambda _p: "", out=out.append, err=err.append,
                       client=PlayingClient(), force=True)
    assert code == 0 and S.MSG_RESTORE_LIST_HEADER in out


def test_guard_refuses_in_visit_hours(db, monkeypatch):
    db.create_backup("a")
    monkeypatch.setattr(restore, "operation_allowed", lambda *a, **k: False)
    err = []
    assert restore.run(db, ask=lambda _p: "", out=lambda t: None, err=err.append) == 2
    assert err == [S.MSG_VISIT_HOUR_WARNING]


def test_visit_hours_setting_is_read(db):
    assert restore.visit_hours_setting(db) is None
    conn = db.connect()
    conn.execute("INSERT INTO settings (key, value) VALUES ('visit_hours', '09:00-18:00')")
    conn.commit()
    conn.close()
    assert restore.visit_hours_setting(db) == "09:00-18:00"


def test_main_force_prints_warning(db, monkeypatch, capsys):
    monkeypatch.setenv("SVF_ROOT", str(db.root))
    monkeypatch.setattr("builtins.input", lambda _p="": "")
    db.create_backup("a")
    assert restore.main(["--force"]) == 0
    assert S.MSG_FORCE_ACTIVE in capsys.readouterr().out


@pytest.mark.parametrize("exc", [EOFError, KeyboardInterrupt])
def test_main_handles_eof_and_ctrl_c(db, monkeypatch, capsys, exc):
    monkeypatch.setenv("SVF_ROOT", str(db.root))
    db.create_backup("a")

    def boom(_p=""):
        raise exc

    monkeypatch.setattr("builtins.input", boom)
    assert restore.main(["--force"]) == 130
    assert S.MSG_RESTORE_CANCELLED in capsys.readouterr().out


def test_restore_of_older_snapshot_drops_orphan_presets(db, tmp_path):
    snap = db.create_backup("manual")
    f = tmp_path / "b.mp4"
    f.write_bytes(b"x")
    bravo = db.add_video(str(f), "Bravo")
    db.set_remote_preset(4, bravo)
    restore.restore_snapshot(db, __import__("pathlib").Path(snap))
    assert db.get_remote_presets() == {}
    assert db.get_remote_preset_video(4) is None


def test_restore_of_snapshot_missing_newer_tables_columns_is_refused(db, tmp_path):
    import sqlite3
    old = db.backup_dir / "svf_kiosk_old_20000101_000000_000000.db"
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE unrelated (x)")
    conn.commit()
    conn.close()
    assert restore.is_valid_snapshot(old)  # integrity ok, but not an SVF database
    with pytest.raises(Exception):
        restore.restore_snapshot(db, old)
        db.get_available_videos()
