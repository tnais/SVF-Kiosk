"""SQLite database, backup engine and playlist business logic."""

import json
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

DEFAULT_ROOT = "/var/lib/svf-kiosk"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_BACKUP_TS_RE = re.compile(r"_(\d{8}_\d{6}_\d{6})\.db$")


def default_root() -> Path:
    """Return the data root: ``$SVF_ROOT`` or ``/var/lib/svf-kiosk``."""
    return Path(os.environ.get("SVF_ROOT", DEFAULT_ROOT))


class Database:
    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()
        self.data_dir = self.root / "data"
        self.backup_dir = self.root / "backups"
        self.db_path = self.data_dir / "svf_kiosk.db"
        self.json_path = self.data_dir / "playlist.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        """Open a connection with the mandatory pragmas applied."""
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        conn = self.connect()
        try:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        finally:
            conn.close()

    # ------------------------------------------------------------------ videos

    def add_video(
        self,
        file_path: str,
        display_title: str,
        description: str = "",
        duration_seconds: int = 0,
        resolution: str = "",
    ) -> int:
        with self._transaction() as conn:
            cur = conn.execute(
                "INSERT INTO videos (file_path, display_title, description,"
                " duration_seconds, resolution) VALUES (?, ?, ?, ?, ?)",
                (file_path, display_title, description, duration_seconds, resolution),
            )
            return int(cur.lastrowid)

    def get_available_videos(self) -> list[dict[str, Any]]:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT * FROM videos WHERE is_deleted = 0"
                " ORDER BY display_title COLLATE NOCASE, id"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def is_video_in_playlist(self, video_id: int) -> bool:
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM playlist WHERE video_id = ? LIMIT 1", (video_id,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def soft_delete_video(self, video_id: int, trash_dir: str | os.PathLike[str]) -> str:
        """Move the file to the trash and flag the video as deleted.

        Raises ``ValueError`` if the video is still in the active playlist.
        Returns the new path of the file in the trash.
        """
        with self._transaction() as conn:
            video = conn.execute(
                "SELECT file_path FROM videos WHERE id = ? AND is_deleted = 0",
                (video_id,),
            ).fetchone()
            if video is None:
                raise ValueError(f"Video {video_id} not found")
            in_playlist = conn.execute(
                "SELECT 1 FROM playlist WHERE video_id = ? LIMIT 1", (video_id,)
            ).fetchone()
            if in_playlist:
                raise ValueError(f"Video {video_id} is in the active playlist")

            source = Path(video["file_path"])
            trash = Path(trash_dir)
            trash.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = trash / f"{timestamp}_{source.name}"

            conn.execute(
                "UPDATE videos SET is_deleted = 1, deleted_at = CURRENT_TIMESTAMP"
                " WHERE id = ?",
                (video_id,),
            )
            conn.execute("DELETE FROM remote_presets WHERE video_id = ?", (video_id,))
            shutil.move(str(source), str(target))
            return str(target)

    # ---------------------------------------------------------------- playlist

    def get_playlist(self) -> list[dict[str, Any]]:
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT p.position, v.* FROM playlist p"
                " JOIN videos v ON v.id = p.video_id ORDER BY p.position"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _playlist_ids(conn: sqlite3.Connection) -> list[int]:
        rows = conn.execute("SELECT video_id FROM playlist ORDER BY position").fetchall()
        return [r["video_id"] for r in rows]

    @staticmethod
    def _rewrite_playlist(conn: sqlite3.Connection, video_ids: list[int]) -> None:
        conn.execute("DELETE FROM playlist")
        conn.executemany(
            "INSERT INTO playlist (position, video_id) VALUES (?, ?)",
            list(enumerate(video_ids, start=1)),
        )

    def add_to_playlist(self, video_id: int) -> int:
        """Append a video to the playlist; returns its new position."""
        with self._transaction() as conn:
            video = conn.execute(
                "SELECT 1 FROM videos WHERE id = ? AND is_deleted = 0", (video_id,)
            ).fetchone()
            if video is None:
                raise ValueError(f"Video {video_id} not found")
            ids = self._playlist_ids(conn)
            ids.append(video_id)
            self._rewrite_playlist(conn, ids)
            return len(ids)

    def set_playlist(self, video_ids: list[int]) -> None:
        """Atomically replace the whole playlist (positions 1..N, no gaps)."""
        if len(set(video_ids)) != len(video_ids):
            raise ValueError("Duplicate video ids in playlist")
        with self._transaction() as conn:
            for video_id in video_ids:
                found = conn.execute(
                    "SELECT 1 FROM videos WHERE id = ? AND is_deleted = 0", (video_id,)
                ).fetchone()
                if found is None:
                    raise ValueError(f"Video {video_id} not found")
            self._rewrite_playlist(conn, list(video_ids))

    def remove_from_playlist(self, position: int) -> None:
        with self._transaction() as conn:
            ids = self._playlist_ids(conn)
            if not 1 <= position <= len(ids):
                raise ValueError(f"Invalid playlist position {position}")
            del ids[position - 1]
            self._rewrite_playlist(conn, ids)

    def reorder_playlist(self, source_pos: int, target_pos: int) -> None:
        """Move the item at ``source_pos`` to ``target_pos`` shifting the others.

        For adjacent positions this is a plain swap.
        """
        with self._transaction() as conn:
            ids = self._playlist_ids(conn)
            for pos in (source_pos, target_pos):
                if not 1 <= pos <= len(ids):
                    raise ValueError(f"Invalid playlist position {pos}")
            ids.insert(target_pos - 1, ids.pop(source_pos - 1))
            self._rewrite_playlist(conn, ids)

    # ---------------------------------------------------------- backup & mirror

    def create_backup(self, prefix: str) -> str:
        """Create an atomic snapshot of the database and return its path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        final = self.backup_dir / f"svf_kiosk_{prefix}_{timestamp}.db"
        partial = final.with_name(final.name + ".tmp")
        src = self.connect()
        dst = sqlite3.connect(partial)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.replace(partial, final)
        return str(final)

    def list_backups(self) -> list[Path]:
        """Return snapshots sorted from oldest to newest."""
        found = []
        for path in self.backup_dir.glob("svf_kiosk_*.db"):
            match = _BACKUP_TS_RE.search(path.name)
            if match:
                found.append((match.group(1), path.name, path))
        return [item[2] for item in sorted(found)]

    def rotate_backups(self, keep_count: int = 20) -> None:
        backups = self.list_backups()
        for old in backups[: max(len(backups) - keep_count, 0)]:
            old.unlink()

    def export_json_mirror(self) -> str:
        """Atomically write the active playlist to ``playlist.json``."""
        payload = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "playlist": self.get_playlist(),
        }
        fd, tmp_name = tempfile.mkstemp(
            dir=self.data_dir, prefix="playlist.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.json_path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return str(self.json_path)
