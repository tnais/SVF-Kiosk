"""svf-ingest: interactive wizard that archives incoming videos into the database."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.mpv_client import MpvClient, MpvIpcError
from ..core.strings import ItalianStrings as S
from ..db.database import Database, default_root
from .guard import operation_allowed
from .usb_sync import VIDEO_EXTENSIONS

MAX_TITLE = 38
MAX_DESCRIPTION = 150


class ProbeError(Exception):
    """ffprobe missing or unable to read the file."""


def probe_video(path: str | Path) -> dict[str, Any]:
    """Return duration, resolution, video codec and audio channels via ffprobe JSON."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True,
        )
    except FileNotFoundError as exc:
        raise ProbeError(S.MSG_INGEST_FFPROBE_MISSING) from exc
    if result.returncode != 0:
        raise ProbeError(S.MSG_INGEST_PROBE_FAILED.format(name=Path(path).name))
    try:
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        video = next(s for s in streams if s.get("codec_type") == "video")
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    except (ValueError, StopIteration, TypeError) as exc:
        raise ProbeError(S.MSG_INGEST_PROBE_FAILED.format(name=Path(path).name)) from exc
    return {
        "duration_seconds": int(round(duration)),
        "resolution": f"{video.get('width', 0)}x{video.get('height', 0)}",
        "video_codec": video.get("codec_name", ""),
        "audio_channels": int(audio.get("channels", 0)),
    }


def sanitize_filename(name: str) -> str:
    """ASCII-safe file name: accents stripped, spaces to underscores."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "video"
    return f"{stem}.{ext.lower()}" if ext else stem


def unique_destination(archive: Path, name: str) -> Path:
    candidate = archive / name
    counter = 1
    while candidate.exists():
        candidate = archive / f"{candidate.stem.rsplit('__', 1)[0]}__{counter}{candidate.suffix}"
        counter += 1
    return candidate


def find_unindexed(incoming: Path) -> list[Path]:
    if not incoming.is_dir():
        return []
    return sorted(
        p for p in incoming.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )


def ask_title(input_fn: Callable[[str], str], out: Callable[[str], None]) -> str:
    while True:
        title = input_fn(S.MSG_INGEST_TITLE_PROMPT.format(max=MAX_TITLE)).strip()
        if not title:
            out(S.MSG_INGEST_TITLE_EMPTY)
        elif len(title) > MAX_TITLE:
            out(S.MSG_INGEST_TITLE_TOO_LONG.format(length=len(title), max=MAX_TITLE))
        else:
            return title


def ask_description(input_fn: Callable[[str], str], out: Callable[[str], None]) -> str:
    while True:
        text = input_fn(S.MSG_INGEST_DESC_PROMPT.format(max=MAX_DESCRIPTION)).strip()
        if len(text) > MAX_DESCRIPTION:
            out(S.MSG_INGEST_DESC_TOO_LONG.format(length=len(text), max=MAX_DESCRIPTION))
        else:
            return text


def ingest_file(
    path: Path,
    db: Database,
    archive: Path,
    client: MpvClient | None,
    input_fn: Callable[[str], str],
    out: Callable[[str], None],
) -> bool:
    """Process one file; returns False if it had to be skipped."""
    try:
        info = probe_video(path)
    except ProbeError as exc:
        out(str(exc))
        return False
    out(S.MSG_INGEST_PROBE_INFO.format(
        duration=info["duration_seconds"], resolution=info["resolution"],
        codec=info["video_codec"], channels=info["audio_channels"]))

    if client is not None and input_fn(S.MSG_PREVIEW_PROMPT).strip().lower() in ("s", "si", "sì"):
        try:
            client.play_preview(str(path))
        except MpvIpcError as exc:
            out(S.MSG_INGEST_PREVIEW_FAILED.format(error=exc))

    title = ask_title(input_fn, out)
    description = ask_description(input_fn, out)

    archive.mkdir(parents=True, exist_ok=True)
    destination = unique_destination(archive, sanitize_filename(path.name))
    shutil.move(str(path), destination)
    try:
        db.add_video(str(destination), title, description,
                     info["duration_seconds"], info["resolution"])
    except Exception:
        shutil.move(str(destination), path)
        raise
    out(S.MSG_INGEST_ARCHIVED.format(title=title))
    return True


def run_ingest(
    root: Path,
    input_fn: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
    client: MpvClient | None = None,
) -> tuple[int, int]:
    incoming = root / "media" / "incoming"
    archive = root / "media" / "archive"
    files = find_unindexed(incoming)
    if not files:
        out(S.MSG_INGEST_NO_FILES.format(path=incoming))
        return 0, 0
    out(S.MSG_INGEST_FOUND.format(count=len(files)))

    db = Database(root)
    db.create_backup("pre_ingest")
    done = skipped = 0
    try:
        for index, path in enumerate(files, start=1):
            out(S.MSG_INGEST_FILE_HEADER.format(index=index, total=len(files), name=path.name))
            if ingest_file(path, db, archive, client, input_fn, out):
                done += 1
            else:
                skipped += 1
    finally:
        db.create_backup("post_ingest")
        db.rotate_backups()
        db.export_json_mirror()
    out(S.MSG_INGEST_SUMMARY.format(done=done, skipped=skipped))
    return done, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="svf-ingest")
    parser.add_argument("--force", action="store_true", help="ignora il controllo orario di visita")
    args = parser.parse_args(argv)

    root = default_root()
    client = MpvClient()
    if args.force:
        print(S.MSG_FORCE_ACTIVE)
    else:
        db = Database(root)
        with db.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key='visit_hours'").fetchone()
        if not operation_allowed(client, row["value"] if row else None):
            print(S.MSG_VISIT_HOUR_WARNING)
            return 2

    run_ingest(root, client=client if client.is_running() else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
