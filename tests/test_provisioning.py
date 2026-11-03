"""Static checks of the provisioning scripts and systemd units (no root needed)."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
KIOSK = SCRIPTS / "systemd" / "svf-kiosk.service"
X11 = SCRIPTS / "systemd" / "svf-x11.service"


def unit(path):
    """Parse a unit file; repeated keys (e.g. Environment=) are joined with newlines."""
    sections: dict[str, dict[str, str]] = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            current = sections.setdefault(line.strip("[]"), {})
            continue
        key, _, value = line.partition("=")
        current[key] = f"{current[key]}\n{value}" if key in current else value
    return sections


@pytest.mark.parametrize("name,shell", [("setup-kiosk.sh", "bash"), ("x11-session.sh", "sh")])
def test_shell_syntax(name, shell):
    assert subprocess.run([shell, "-n", str(SCRIPTS / name)]).returncode == 0


def test_scripts_are_executable():
    for name in ("setup-kiosk.sh", "x11-session.sh"):
        assert (SCRIPTS / name).stat().st_mode & 0o111


def test_setup_script_is_strict_and_checks_debian_12():
    text = (SCRIPTS / "setup-kiosk.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "/etc/debian_version" in text and '"12"' in text
    for pkg in ("xorg", "unclutter", "mpv", "ffmpeg", "sqlite3", "python3-venv", "udisks2", "bluez"):
        assert pkg in text
    assert "it_IT.UTF-8" in text and "50-svf-usb-mount.rules" in text
    assert "media/incoming" in text and "chmod -R 775" in text


def test_setup_script_refuses_non_root():
    r = subprocess.run(["bash", str(SCRIPTS / "setup-kiosk.sh")], capture_output=True, text=True)
    import os
    if os.geteuid() == 0:
        pytest.skip("running as root: would provision the machine")
    assert r.returncode == 1 and "ERRORE" in r.stderr


def test_no_wayland_anywhere_in_provisioning():
    for path in [*SCRIPTS.glob("*.sh"), *SCRIPTS.glob("systemd/*")]:
        text = path.read_text(encoding="utf-8").lower()
        for word in ("cage", "labwc", "weston", "wayland"):
            assert word not in text.replace("seat", ""), (path.name, word)


def test_x11_session_disables_blanking_and_hides_cursor():
    text = (SCRIPTS / "x11-session.sh").read_text(encoding="utf-8")
    assert "xset s off -dpms" in text and "unclutter -idle 0.5 -root" in text


def test_kiosk_unit_matches_spec():
    u = unit(KIOSK)
    env = u["Service"]["Environment"]
    assert "DISPLAY=:0" in env and "PYTHONUNBUFFERED=1" in env
    assert "XAUTHORITY=/home/svf-operatore/.Xauthority" in env
    assert "/tmp/.X11-unix/X0" in u["Service"]["ExecStartPre"]
    assert u["Service"]["ExecStart"] == "/opt/svf-kiosk/venv/bin/svf-kiosk-daemon"
    assert u["Service"]["Restart"] == "always" and u["Service"]["RestartSec"] == "3"
    assert u["Install"]["WantedBy"] == "default.target"  # user unit: svf-restore uses --user


def test_x11_unit_runs_as_operator_on_display_0():
    u = unit(X11)
    assert u["Service"]["User"] == "svf-operatore"
    assert ":0" in u["Service"]["ExecStart"] and "xinit" in u["Service"]["ExecStart"]
    assert "x11-session.sh" in u["Service"]["ExecStart"]
    assert u["Service"]["Restart"] == "always"


def test_wait_for_x_socket_snippet_behaviour(tmp_path):
    cmd = unit(KIOSK)["Service"]["ExecStartPre"].replace("/bin/sh -c ", "", 1).strip("'")
    cmd = cmd.replace("/tmp/.X11-unix/X0", str(tmp_path / "X0")).replace("$$", "$")
    (tmp_path / "X0").touch()  # not a socket: must keep waiting then fail quickly
    cmd = cmd.replace("-gt 60", "-gt 1").replace("sleep 1", "sleep 0.01")
    assert subprocess.run(["/bin/sh", "-c", cmd]).returncode == 1


def test_daemon_entry_point_exists():
    assert 'svf-kiosk-daemon = "src.daemon.kiosk_player:main"' in (ROOT / "pyproject.toml").read_text()


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze missing")
def test_systemd_analyze_accepts_units(tmp_path):
    for src in (KIOSK, X11):
        r = subprocess.run(["systemd-analyze", "verify", "--user" if src == KIOSK else "--system", str(src)],
                           capture_output=True, text=True)
        bad = [l for l in r.stderr.splitlines() if l.startswith(src.name)
               and ("syntax" in l.lower() or "unknown" in l.lower() or "invalid" in l.lower())]
        assert not bad, r.stderr
