"""svf-presets: assign remote-control keys 1-9 to videos from the command line."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ..core.strings import ItalianStrings as S
from ..db.database import Database


def find_videos(videos: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Exact (case-insensitive) title match first, then unique-or-ambiguous substring match."""
    needle = query.strip().casefold()
    exact = [v for v in videos if v["display_title"].casefold() == needle]
    if exact:
        return exact
    return [v for v in videos if needle and needle in v["display_title"].casefold()]


def parse_key(value: str) -> int | None:
    return int(value) if value.isdigit() and 1 <= int(value) <= 9 else None


def cmd_list(db: Database, out=print) -> int:
    presets = db.get_remote_presets()
    out(S.MSG_PRESETS_HEADER)
    for key in range(1, 10):
        video = presets.get(key)
        if video:
            out(S.MSG_PRESETS_LINE.format(key=key, title=video["display_title"], id=video["id"]))
        else:
            out(S.MSG_PRESETS_FREE.format(key=key))
    return 0


def cmd_set(db: Database, key_text: str, title: str | None, video_id: int | None,
            out=print, err=print) -> int:
    key = parse_key(key_text)
    if key is None:
        err(S.MSG_PRESETS_BAD_KEY)
        return 2
    videos = db.get_available_videos()
    if video_id is not None:
        matches = [v for v in videos if v["id"] == video_id]
        label = str(video_id)
    else:
        matches = find_videos(videos, title or "")
        label = title or ""
    if not matches:
        err(S.MSG_PRESETS_NOT_FOUND.format(title=label))
        return 1
    if len(matches) > 1:
        err(S.MSG_PRESETS_AMBIGUOUS.format(title=label))
        for v in matches:
            err(S.MSG_PRESETS_CANDIDATE.format(id=v["id"], title=v["display_title"]))
        return 1
    video = matches[0]
    db.create_backup("pre_edit")
    db.set_remote_preset(key, video["id"])
    db.create_backup("post_edit")
    db.rotate_backups()
    out(S.MSG_PRESETS_SET.format(key=key, title=video["display_title"]))
    return 0


def cmd_clear(db: Database, key_text: str, out=print, err=print) -> int:
    key = parse_key(key_text)
    if key is None:
        err(S.MSG_PRESETS_BAD_KEY)
        return 2
    db.create_backup("pre_edit")
    existed = db.clear_remote_preset(key)
    db.create_backup("post_edit")
    db.rotate_backups()
    out(S.MSG_PRESETS_CLEARED.format(key=key) if existed else S.MSG_PRESETS_NOT_SET.format(key=key))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="svf-presets")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    p_set = sub.add_parser("set")
    p_set.add_argument("key")
    p_set.add_argument("title", nargs="?")
    p_set.add_argument("--id", type=int, dest="video_id")
    p_clear = sub.add_parser("clear")
    p_clear.add_argument("key")
    args = parser.parse_args(argv)

    db = Database()
    err = lambda text: print(text, file=sys.stderr)  # noqa: E731
    if args.command == "list":
        return cmd_list(db)
    if args.command == "set":
        if args.title is None and args.video_id is None:
            parser.error("set requires a title or --id")
        return cmd_set(db, args.key, args.title, args.video_id, err=err)
    return cmd_clear(db, args.key, err=err)


if __name__ == "__main__":
    sys.exit(main())
