"""svf-restore: roll the database back to one of the automatic snapshots."""

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..core.mpv_client import MpvClient
from ..core.strings import ItalianStrings as S
from ..db.database import Database
from .guard import operation_allowed

RESTART_COMMAND = ["systemctl", "--user", "restart", "svf-kiosk.service"]


def is_valid_snapshot(path: Path) -> bool:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def restore_snapshot(db: Database, snapshot: Path) -> str:
    """Safety-backup the live DB, copy ``snapshot`` over it and rebuild the JSON mirror."""
    safety = db.create_backup("pre_restore")
    src = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    dst = db.connect()
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    db.export_json_mirror()
    db.rotate_backups()
    return safety


def restart_service(runner: Callable = subprocess.run) -> bool:
    try:
        return runner(RESTART_COMMAND, capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def visit_hours_setting(db: Database) -> str | None:
    conn = db.connect()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key='visit_hours'").fetchone()
    finally:
        conn.close()
    return row["value"] if row else None


def run(db: Database, ask=None, out=print, err=None, runner: Callable = subprocess.run,
        force: bool = False, client: MpvClient | None = None) -> int:
    ask = ask or input
    err = err or (lambda text: print(text, file=sys.stderr))
    if not force:
        if not operation_allowed(client or MpvClient(), visit_hours_setting(db)):
            err(S.MSG_VISIT_HOUR_WARNING)
            return 2
    snapshots = list(reversed(db.list_backups()))
    if not snapshots:
        err(S.MSG_RESTORE_NO_BACKUPS)
        return 1
    out(S.MSG_RESTORE_LIST_HEADER)
    for index, path in enumerate(snapshots, 1):
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
        out(S.MSG_RESTORE_LIST_LINE.format(index=index, name=path.name, value=stamp))
    choice = ask(S.MSG_RESTORE_CHOOSE).strip()
    if not choice:
        out(S.MSG_RESTORE_CANCELLED)
        return 0
    if not choice.isdigit() or not 1 <= int(choice) <= len(snapshots):
        err(S.MSG_RESTORE_INVALID)
        return 2
    snapshot = snapshots[int(choice) - 1]
    if not is_valid_snapshot(snapshot):
        err(S.MSG_RESTORE_CORRUPT.format(name=snapshot.name))
        return 1
    if ask(S.MSG_RESTORE_CONFIRM.format(name=snapshot.name)).strip().lower() != "s":
        out(S.MSG_RESTORE_CANCELLED)
        return 0
    safety = restore_snapshot(db, snapshot)
    out(S.MSG_RESTORE_SAFETY.format(name=Path(safety).name))
    if not restart_service(runner):
        err(S.MSG_RESTORE_RELOAD_FAILED)
        return 1
    out(S.MSG_RESTORE_DONE)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="svf-restore")
    parser.add_argument("--force", action="store_true", help="ignora il controllo orario di visita")
    args = parser.parse_args(argv)
    if args.force:
        print(S.MSG_FORCE_ACTIVE)
    try:
        return run(Database(), force=args.force)
    except (EOFError, KeyboardInterrupt):
        print()
        print(S.MSG_RESTORE_CANCELLED)
        return 130


if __name__ == "__main__":
    sys.exit(main())
