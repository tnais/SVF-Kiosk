"""Run the installed console scripts as real subprocesses."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.core.strings import ItalianStrings as S
from src.db.database import Database

BIN = Path(sys.executable).parent


def script(name):
    path = BIN / name
    if not path.exists():
        pytest.skip(f"{name} is not installed")
    return str(path)


@pytest.fixture
def root(tmp_path):
    db = Database(tmp_path)
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    db.add_video(str(f), "Stazione")
    return tmp_path


def call(name, root, *args, stdin=""):
    env = {"SVF_ROOT": str(root), "PATH": "/usr/bin:/bin", "HOME": str(root), "LANG": "C.UTF-8",
           "XDG_RUNTIME_DIR": str(root)}
    return subprocess.run([script(name), *args], capture_output=True, text=True, input=stdin,
                          env=env, timeout=30)


def test_svf_presets_round_trip(root):
    assert call("svf-presets", root, "set", "2", "stazione").returncode == 0
    out = call("svf-presets", root, "list")
    assert out.returncode == 0 and "Stazione" in out.stdout
    assert call("svf-presets", root, "clear", "2").returncode == 0
    assert call("svf-presets", root, "set", "11", "x").returncode == 2


def test_svf_status_runs_without_services(root):
    r = call("svf-status", root)
    assert r.returncode == 0 and S.MSG_STATUS_PLAYER_DOWN in r.stdout


def test_svf_restore_without_backups_and_with_eof(root):
    for p in (root / "backups").glob("*.db"):
        p.unlink()
    r = call("svf-restore", root)
    assert r.returncode == 1 and S.MSG_RESTORE_NO_BACKUPS in r.stderr
    Database(root).create_backup("a")
    r = call("svf-restore", root)  # EOF on stdin
    assert r.returncode == 130 and S.MSG_RESTORE_CANCELLED in r.stdout
