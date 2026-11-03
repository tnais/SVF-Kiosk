"""svf-status: diagnostic report (player, system telemetry, display, Bluetooth remote)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from ..core.mpv_client import MpvClient, MpvIpcError
from ..core.strings import ItalianStrings as S
from ..db.database import default_root

THERMAL_PATH = "/sys/class/thermal/thermal_zone0/temp"
MEMINFO_PATH = "/proc/meminfo"


def format_clock(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def player_lines(client: MpvClient) -> list[str]:
    try:
        if not client.is_running():
            return [S.MSG_STATUS_PLAYER_DOWN]
        if client.get_property("idle-active"):
            return [S.MSG_STATUS_PLAYER_IDLE]
        info = client.get_playback_status()
    except (MpvIpcError, OSError):
        return [S.MSG_STATUS_PLAYER_DOWN]
    state = S.UI_STATUS_STATE_PAUSED if info["paused"] else S.UI_STATUS_STATE_PLAYING
    return [
        S.MSG_STATUS_PLAYER_FILE.format(path=info["file"]),
        S.MSG_STATUS_PLAYER_TIME.format(
            elapsed=format_clock(info["time_pos"]), duration=format_clock(info["duration"])
        ),
        S.MSG_STATUS_PLAYER_STATE.format(state=state),
    ]


def cpu_temperature_line(path: str = THERMAL_PATH) -> str:
    try:
        millidegrees = int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return S.MSG_STATUS_CPU_TEMP_UNKNOWN
    return S.MSG_STATUS_CPU_TEMP.format(temp=f"{millidegrees / 1000:.1f}")


def ram_line(path: str = MEMINFO_PATH) -> str:
    try:
        fields = {}
        for line in Path(path).read_text().splitlines():
            name, _, rest = line.partition(":")
            fields[name] = int(rest.split()[0])
        total, available = fields["MemTotal"], fields["MemAvailable"]
    except (OSError, ValueError, KeyError, IndexError):
        return S.MSG_STATUS_RAM_UNKNOWN
    return S.MSG_STATUS_RAM.format(used=(total - available) // 1024, total=total // 1024)


def disk_line(root: Path) -> str:
    try:
        usage = shutil.disk_usage(root)
    except OSError:
        return S.MSG_STATUS_DISK_UNKNOWN
    return S.MSG_STATUS_DISK.format(
        path=root, free=f"{usage.free / 1e9:.1f}", total=f"{usage.total / 1e9:.1f}"
    )


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _run(cmd: list[str], runner: Runner, env: dict[str, str] | None = None) -> str | None:
    try:
        result = runner(cmd, capture_output=True, text=True, timeout=5, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def display_line(runner: Runner = subprocess.run) -> str:
    env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
    out = _run(["xrandr", "--query"], runner, env)
    if out is None:
        return S.MSG_STATUS_DISPLAY_UNKNOWN
    outputs = []
    for line in out.splitlines():
        match = re.match(r"^(\S+) connected(?: primary)?(?: (\d+x\d+)\+\d+\+\d+)?", line)
        if match:
            outputs.append(f"{match.group(1)} {match.group(2) or ''}".strip())
    value = ", ".join(outputs) if outputs else S.UI_STATUS_DISPLAY_NONE
    return S.MSG_STATUS_DISPLAY.format(value=value)


def bluetooth_lines(runner: Runner = subprocess.run) -> list[str]:
    listing = _run(["bluetoothctl", "devices", "Connected"], runner)
    if listing is None:
        return [S.MSG_STATUS_BT_UNKNOWN]
    match = re.search(r"Device\s+([0-9A-Fa-f:]{17})", listing)
    if not match:
        return [S.MSG_STATUS_BT_DISCONNECTED]
    address = match.group(1)
    info = _run(["bluetoothctl", "info", address], runner) or ""
    lines = [S.MSG_STATUS_BT_CONNECTED.format(address=address)]
    battery = re.search(r"Battery Percentage:\s*0x[0-9a-fA-F]+\s*\((\d+)\)", info)
    lines.append(
        S.MSG_STATUS_BT_BATTERY.format(battery=battery.group(1))
        if battery
        else S.MSG_STATUS_BT_BATTERY_UNKNOWN
    )
    return lines


def build_report(client: MpvClient, root: Path, runner: Runner = subprocess.run) -> list[str]:
    return [
        S.MSG_STATUS_HEADER,
        *player_lines(client),
        cpu_temperature_line(),
        ram_line(),
        disk_line(root),
        display_line(runner),
        *bluetooth_lines(runner),
    ]


def main(argv: list[str] | None = None) -> int:
    for line in build_report(MpvClient(), default_root()):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
