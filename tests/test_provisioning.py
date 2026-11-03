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
    text = SETUP.read_text(encoding="utf-8")
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
        text = code_only(path).lower()
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


# ---------------------------------------------------------------------------
# Additional static constraints. They read the scripts and unit files as text
# (never execute them as root) and cross-check them against the Python code, so
# the provisioning cannot silently drift from the application.
# ---------------------------------------------------------------------------
import re
import tomllib

from src.core.mpv_client import DEFAULT_SOCKET
from src.db.database import DEFAULT_ROOT

SETUP = SCRIPTS / "setup-kiosk.sh"


def code_only(path):
    """File content without full-line comments (comments may legitimately name forbidden tools)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lines if not l.lstrip().startswith("#") or l.startswith("#!"))


def setup_text():
    return code_only(SETUP)


def entry_points():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return set(data["project"]["scripts"])


def linked_tools():
    """Tool names listed in the ``for tool in ...; do ln -sf`` loop of the setup script."""
    match = re.search(r"for tool in ([^;]+); do", setup_text())
    assert match, "symlink loop not found"
    return match.group(1).split()


def test_every_linked_tool_is_a_real_entry_point():
    assert set(linked_tools()) <= entry_points()


def test_every_operator_tool_is_linked_into_usr_local_bin():
    """The daemon is run by systemd; all other entry points are operator tools."""
    assert set(linked_tools()) == entry_points() - {"svf-kiosk-daemon"}


def test_files_referenced_by_the_setup_script_exist():
    for name in re.findall(r"scripts/systemd/[\w.-]+", setup_text()):
        assert (ROOT / name).is_file(), name


def test_x11_unit_points_to_an_existing_session_script():
    exec_start = unit(X11)["Service"]["ExecStart"]
    relative = re.search(r"/opt/svf-kiosk/(scripts/[\w.-]+\.sh)", exec_start).group(1)
    assert (ROOT / relative).is_file()


def test_paths_match_application_defaults():
    """Directories and socket created by provisioning must be the ones the code uses."""
    text = setup_text()
    assert f'DATA_DIR="{DEFAULT_ROOT}"' in text
    assert f"SVF_ROOT={DEFAULT_ROOT}" in KIOSK.read_text(encoding="utf-8")
    socket_dir = str(Path(DEFAULT_SOCKET).parent)
    assert f"d {socket_dir} " in text


def test_operator_user_is_consistent_everywhere():
    assert 'OPERATOR="svf-operatore"' in setup_text()
    assert unit(X11)["Service"]["User"] == "svf-operatore"
    assert "/home/svf-operatore/" in unit(KIOSK)["Service"]["Environment"]
    assert "svf-operatore" in setup_text().split("50-svf-usb-mount.rules")[1]


def test_operator_user_is_in_required_groups_and_lingers():
    text = setup_text()
    assert "audio,video,input,render" in text  # input: evdev remote; render/video: VAAPI
    assert 'loginctl enable-linger "${OPERATOR}"' in text


def test_root_and_os_checks_come_before_any_change():
    text = setup_text()
    first_change = min(text.index(m) for m in ("apt-get update", "mkdir -p", "adduser", "cat >"))
    assert text.index("id -u") < first_change
    assert text.index("/etc/debian_version") < first_change


def test_steps_run_in_a_sane_order():
    text = setup_text()
    order = ["apt-get update", "locale-gen", "adduser", "Xwrapper.config", 'mkdir -p "${DATA_DIR}"',
             "rsync -a", "-m venv", "ln -sf", "systemctl daemon-reload", "systemctl restart svf-x11"]
    positions = [text.index(item) for item in order]
    assert positions == sorted(positions)


def test_data_directories_are_complete_and_group_writable():
    text = setup_text()
    assert "{data,media/archive,media/incoming,trash,backups}" in text
    assert 'chown -R "${OPERATOR}:${OPERATOR}" "${DATA_DIR}"' in text
    assert 'chmod -R 775 "${DATA_DIR}"' in text


def test_setup_script_is_idempotent_by_construction():
    text = setup_text()
    assert "mkdir -p" in text and "ln -sf" in text and "rsync -a --delete" in text
    assert "adduser" in text and "if ! id " in text  # user created only when missing
    assert "if ! locale -a" in text


def test_setup_script_avoids_dangerous_patterns():
    text = setup_text()
    assert "curl" not in text and "wget" not in text  # no downloads piped into a shell
    assert not re.search(r"\brm\s+-rf?\s+/(\s|$)", text)
    assert "| sh" not in text and "| bash" not in text
    assert "--exclude '.git'" in text  # never ship the repository history to /opt


def test_setup_script_variables_are_quoted_in_dangerous_commands():
    for line in setup_text().splitlines():
        if line.lstrip().startswith(("chown", "chmod", "rsync", "mkdir")):
            assert not re.search(r"(?<![\"{])\$[A-Za-z_]", line), line  # unquoted $VAR


def test_setup_script_messages_are_italian_utf8():
    text = setup_text()
    assert 'die "' in text and "ERRORE:" in text
    for bad in ("Ã", "â€", "Â"):
        assert bad not in text
    assert "è richiesto Debian 12" in text  # accented vowels are real UTF-8


def test_provisioning_files_have_no_mojibake_or_trailing_spaces():
    files = [SETUP, SCRIPTS / "x11-session.sh", KIOSK, X11]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not any(bad in text for bad in ("Ã", "â€", "Â"))
        assert "\r" not in text, f"{path.name}: CRLF line endings break shebangs"
        assert all(line == line.rstrip() for line in text.splitlines()), path.name


def test_shell_scripts_have_a_shebang():
    assert setup_text().startswith("#!/usr/bin/env bash")
    assert (SCRIPTS / "x11-session.sh").read_text(encoding="utf-8").startswith("#!/bin/sh")


def test_x11_session_keeps_x_alive_and_is_posix_sh():
    text = (SCRIPTS / "x11-session.sh").read_text(encoding="utf-8")
    assert "exec sleep infinity" in text  # when this script exits, X shuts down
    assert "[[" not in text and "bash" not in text.lower().replace("#!/bin/sh", "")


def test_x11_unit_never_starts_the_player_itself():
    """The player is the user unit's job; two owners would double-start mpv."""
    assert "kiosk_player" not in unit(X11)["Service"]["ExecStart"]
    assert "svf-kiosk-daemon" not in (SCRIPTS / "x11-session.sh").read_text(encoding="utf-8")


def test_kiosk_unit_orders_after_x_and_is_not_a_system_target():
    u = unit(KIOSK)
    assert "svf-x11.service" in u["Unit"]["After"]
    assert "multi-user.target" not in u["Install"]["WantedBy"]


def test_kiosk_unit_waits_for_x_socket_with_a_bounded_timeout():
    cmd = unit(KIOSK)["Service"]["ExecStartPre"]
    assert "-S /tmp/.X11-unix/X0" in cmd and re.search(r"-gt \d+", cmd) and "exit 1" in cmd


def test_x11_unit_uses_display_0_on_vt1_without_cursor():
    exec_start = unit(X11)["Service"]["ExecStart"]
    assert " :0 " in exec_start and "vt1" in exec_start and "-nocursor" in exec_start


def test_units_are_documented_with_header_comments():
    for path in (KIOSK, X11):
        assert path.read_text(encoding="utf-8").startswith("#"), path.name


def test_documentation_mentions_the_provisioning_entry_points():
    docs = (ROOT / "Docs" / "DEVELOPMENT_PLAN_AND_INSTALLATION.md").read_text(encoding="utf-8")
    for needle in ("setup-kiosk.sh", "x11-session.sh", "svf-x11.service", "svf-kiosk.service",
                   "enable-linger", "Group G"):
        assert needle in docs, needle
