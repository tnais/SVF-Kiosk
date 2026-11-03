"""svf-usb-sync: copy new videos from a USB stick into the incoming folder."""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from ..core.mpv_client import MpvClient
from ..core.strings import ItalianStrings as S
from ..db.database import Database, default_root
from .guard import operation_allowed

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi")
CHUNK = 1024 * 1024


class UsbError(Exception):
    """Mount or unmount failure."""


def list_partitions(pattern: str = "/dev/sd*") -> list[str]:
    """Return USB partitions such as /dev/sdb1 (whole disks are ignored)."""
    return sorted(p for p in glob.glob(pattern) if re.search(r"\d$", p))


def mount_device(device: str) -> str:
    """Mount with udisksctl (no root needed) and return the mount point."""
    result = subprocess.run(
        ["udisksctl", "mount", "-b", device], capture_output=True, text=True
    )
    output = (result.stdout or "") + (result.stderr or "")
    match = re.search(r" at `?(.+?)'?\.?\s*$", output.strip()) or re.search(
        r"already mounted at `(.+?)'", output
    )
    if result.returncode != 0 and "already mounted" not in output:
        raise UsbError(S.MSG_USB_MOUNT_FAILED.format(device=device))
    if not match:
        raise UsbError(S.MSG_USB_MOUNT_FAILED.format(device=device))
    return match.group(1)


def unmount_device(device: str) -> None:
    result = subprocess.run(
        ["udisksctl", "unmount", "-b", device], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise UsbError(S.MSG_USB_UNMOUNT_FAILED.format(device=device))


def find_videos(mount_point: str | os.PathLike[str]) -> list[Path]:
    found = [
        p
        for p in Path(mount_point).rglob("*")
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTENSIONS
        and not p.name.startswith(".")
    ]
    return sorted(found)


def _already_present(src: Path, folders: list[Path]) -> bool:
    size = src.stat().st_size
    return any(
        (f / src.name).is_file() and (f / src.name).stat().st_size == size
        for f in folders
    )


def copy_new_videos(
    videos: list[Path],
    incoming: Path,
    archive: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    """Copy videos not already in incoming/archive. Returns (copied, skipped)."""
    incoming.mkdir(parents=True, exist_ok=True)
    folders = [incoming] + ([archive] if archive else [])
    todo = [v for v in videos if not _already_present(v, folders)]
    skipped = len(videos) - len(todo)
    for index, src in enumerate(todo, start=1):
        total_size = max(src.stat().st_size, 1)
        done = 0
        tmp = incoming / (src.name + ".part")
        with src.open("rb") as fin, tmp.open("wb") as fout:
            while chunk := fin.read(CHUNK):
                fout.write(chunk)
                done += len(chunk)
                if progress:
                    progress(
                        S.MSG_USB_COPYING.format(
                            index=index,
                            total=len(todo),
                            name=src.name,
                            percent=int(done * 100 / total_size),
                        )
                    )
        os.replace(tmp, incoming / src.name)
    return len(todo), skipped


def _print_progress(message: str) -> None:
    print("\r" + message, end="", flush=True)


def sync_device(device: str, root: Path, out: Callable[[str], None] = print) -> int:
    """Mount, copy and always unmount. Returns the number of copied videos."""
    out(S.MSG_USB_DETECTED.format(device=device))
    mount_point = mount_device(device)
    out(S.MSG_USB_MOUNTED.format(path=mount_point))
    try:
        videos = find_videos(mount_point)
        copied, skipped = copy_new_videos(
            videos,
            root / "media" / "incoming",
            root / "media" / "archive",
            progress=_print_progress,
        )
        if videos and copied:
            print()
    finally:
        unmount_device(device)
    if skipped:
        out(S.MSG_USB_SKIPPED.format(count=skipped))
    if copied:
        out(S.MSG_USB_COPY_SUCCESS.format(count=copied))
    else:
        out(S.MSG_USB_NO_VIDEOS)
    out(S.MSG_USB_UNMOUNTED.format(device=device))
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="svf-usb-sync")
    parser.add_argument("--device", help="partizione da usare, es. /dev/sdb1")
    parser.add_argument("--force", action="store_true", help="ignora il controllo orario di visita")
    args = parser.parse_args(argv)

    root = default_root()
    if args.force:
        print(S.MSG_FORCE_ACTIVE)
    else:
        db = Database(root)
        with db.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='visit_hours'").fetchone()
        if not operation_allowed(MpvClient(), row["value"] if row else None):
            print(S.MSG_VISIT_HOUR_WARNING)
            return 2

    devices = [args.device] if args.device else list_partitions()
    if not devices:
        print(S.MSG_USB_NO_DEVICE)
        return 1
    try:
        sync_device(devices[0], root)
    except UsbError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
