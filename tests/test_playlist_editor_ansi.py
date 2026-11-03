"""Raw-output checks of the editor on ECMA-48 (ANSI) terminals, run in a real pty."""
import fcntl
import os
import pty
import re
import select
import struct
import sys
import termios
import time

import pytest

from src.db.database import Database

pytestmark = pytest.mark.filterwarnings("ignore:.*fork.*:DeprecationWarning")

CSI = re.compile(rb"\x1b\[([0-9;:?<=>]*)([ -/]*)([@-~])")
ALLOWED_SGR = set(range(0, 10)) | {22, 23, 24, 25, 27, 28, 29, 39, 49} | set(range(30, 38)) | set(
    range(40, 48)) | set(range(90, 98)) | set(range(100, 108))


@pytest.fixture
def root(tmp_path):
    db = Database(tmp_path)
    for name in ("Delta", "Alfa", "Charlie", "Bravo"):
        f = tmp_path / f"{name}.mp4"
        f.write_bytes(b"x")
        db.add_video(str(f), name, f"Descrizione di {name}", 125, "1920x1080")
    return tmp_path


def run_editor(root, term, keys=(b"\r", b"\t", b"\r"), colorterm=None):
    env = {k: v for k, v in os.environ.items() if k not in ("COLORTERM", "NO_COLOR", "FORCE_COLOR")}
    env.update(TERM=term, SVF_ROOT=str(root), LANG="it_IT.UTF-8", PYTHONIOENCODING="utf-8")
    if colorterm:
        env["COLORTERM"] = colorterm
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(sys.executable, [sys.executable, "-m", "src.tui.playlist_editor"], env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))

    def read(seconds):
        out, end = b"", time.time() + seconds
        while time.time() < end:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    break
                out += chunk
        return out

    out = read(1.5)
    for key in keys:
        os.write(fd, key)
        out += read(0.3)
    os.write(fd, b"q")
    out += read(0.8)
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        pass
    os.waitpid(pid, 0)
    return out


def sgr_params(raw):
    params = []
    for m in CSI.finditer(raw):
        if m.group(3) == b"m" and not m.group(1).startswith((b"?", b"<", b"=", b">")):
            params.extend(int(p) for p in re.split(rb"[;:]", m.group(1)) if p)
    return params


@pytest.mark.parametrize("term", ["linux", "vt100", "xterm"])
def test_only_basic_ecma48_sgr_without_colorterm(root, term):
    raw = run_editor(root, term)
    assert b"Archivio Video" in raw
    bad = sorted(set(sgr_params(raw)) - ALLOWED_SGR)
    assert not bad, f"non-ECMA-48 16-colour SGR parameters on TERM={term}: {bad}"
    assert b"38;2" not in raw and b"48;2" not in raw
    assert b"38;5" not in raw and b"48;5" not in raw


def test_no_8bit_c1_controls_and_valid_utf8(root):
    raw = run_editor(root, "vt100")
    text = raw.decode("utf-8")
    assert not any("\x80" <= ch <= "\x9f" for ch in text)
    assert "\ufffd" not in text


def test_every_escape_is_well_formed_csi_or_known(root):
    raw = run_editor(root, "linux")
    stripped = CSI.sub(b"", raw)
    leftovers = re.findall(rb"\x1b[^\x07\x1b]{0,3}", stripped)
    # remaining escapes must be two-byte ESC sequences (ESC 7/8/=/>/M), OSC or charset selection
    for esc in leftovers:
        assert re.match(rb"\x1b([78=>M\]\\()#c]|\([0B])", esc), esc


def test_blue_and_green_use_standard_colour_codes_on_ansi(root):
    raw = run_editor(root, "linux")
    params = set(sgr_params(raw))
    assert params & set(range(40, 48)) or params & set(range(30, 38)), "no colours emitted at all"
    assert b"38;2" not in raw


def test_truecolor_terminal_still_gets_rgb(root):
    raw = run_editor(root, "xterm-256color", colorterm="truecolor")
    assert b"38;2" in raw or b"48;2" in raw
