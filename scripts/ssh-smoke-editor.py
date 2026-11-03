#!/usr/bin/env python3
"""Smoke test: run svf-playlist-editor in a real SSH pseudo-terminal (80x24).

Requires passwordless SSH to the target host (default: localhost).
Uses a throw-away SVF_ROOT, so the real database is never touched.

Usage: scripts/ssh-smoke-editor.py [host] [TERM]
"""
import fcntl
import os
import pty
import select
import shutil
import shlex
import struct
import sys
import tempfile
import termios
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.db.database import Database  # noqa: E402


def seed(root: Path) -> None:
    db = Database(root)
    for name in ("Delta", "Alfa", "Charlie", "Bravo"):
        f = root / f"{name}.mp4"
        f.write_bytes(b"x")
        db.add_video(str(f), name, f"Descrizione di {name}", 125, "1920x1080")


def read_for(fd: int, seconds: float) -> bytes:
    out, end = b"", time.time() + seconds
    while time.time() < end:
        if select.select([fd], [], [], 0.1)[0]:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
    return out


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    term = sys.argv[2] if len(sys.argv) > 2 else "xterm-256color"
    root = Path(tempfile.mkdtemp(prefix="svf-smoke-"))
    seed(root)
    remote = (f"export TERM={term} SVF_ROOT={shlex.quote(str(root))} LANG=it_IT.UTF-8; "
              f"stty cols 80 rows 24; exec {shlex.quote(str(REPO / '.venv/bin/svf-playlist-editor'))}")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("ssh", ["ssh", "-tt", "-o", "BatchMode=yes", host, remote])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))

    seen = read_for(fd, 4)
    checks = {"Archivio Video": b"Archivio Video" in seen, "Scaletta Attiva": b"Scaletta Attiva" in seen,
              "Alfa listed": b"Alfa" in seen}
    for key in (b"\r", b"\t", b"\r", b"s"):  # add video, switch panel, reorder toggle, save
        os.write(fd, key)
        seen += read_for(fd, 1)
    checks["saved"] = b"salvata" in seen
    os.write(fd, b"q")
    seen += read_for(fd, 2)
    _, status = os.waitpid(pid, 0)
    checks["clean exit"] = os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
    checks["playlist persisted"] = len(Database(root).get_playlist()) == 1

    shutil.rmtree(root, ignore_errors=True)
    for name, ok in checks.items():
        print(f"{'OK  ' if ok else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
