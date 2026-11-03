"""Tests for the SQLite persistence layer."""

import json
import sqlite3

import pytest

from src.db.database import Database, default_root


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "root")


def add_videos(db, tmp_path, count=3):
    ids = []
    for i in range(count):
        media = tmp_path / f"video{i}.mp4"
        media.write_bytes(b"x")
        ids.append(db.add_video(str(media), f"Video {chr(ord('C') - i)}"))
    return ids


def playlist_ids(db):
    return [row["id"] for row in db.get_playlist()]


def test_default_root_uses_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("SVF_ROOT", str(tmp_path))
    assert default_root() == tmp_path
    assert Database().db_path == tmp_path / "data" / "svf_kiosk.db"


def test_pragmas_applied_on_every_connection(db):
    for _ in range(2):
        conn = db.connect()
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
        finally:
            conn.close()


def test_foreign_keys_enforced(db, tmp_path):
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO playlist (position, video_id) VALUES (1, 999)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO remote_presets (preset_key, video_id) VALUES (1, 999)")
    finally:
        conn.close()


def test_playlist_restricts_video_deletion_and_presets_cascade(db, tmp_path):
    first, second, _ = add_videos(db, tmp_path)
    db.add_to_playlist(first)
    conn = db.connect()
    try:
        conn.execute("INSERT INTO remote_presets (preset_key, video_id) VALUES (1, ?)", (second,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM videos WHERE id = ?", (first,))
        conn.execute("DELETE FROM videos WHERE id = ?", (second,))
        assert conn.execute("SELECT COUNT(*) FROM remote_presets").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO remote_presets (preset_key, video_id) VALUES (10, ?)", (first,))
    finally:
        conn.close()


def test_available_videos_sorted_by_title(db, tmp_path):
    add_videos(db, tmp_path)
    titles = [v["display_title"] for v in db.get_available_videos()]
    assert titles == ["Video A", "Video B", "Video C"]


def test_add_and_remove_reindexes_positions(db, tmp_path):
    a, b, c = add_videos(db, tmp_path)
    for vid in (a, b, c):
        db.add_to_playlist(vid)
    db.remove_from_playlist(2)
    playlist = db.get_playlist()
    assert [p["position"] for p in playlist] == [1, 2]
    assert [p["id"] for p in playlist] == [a, c]


def test_remove_invalid_position_rejected(db, tmp_path):
    with pytest.raises(ValueError):
        db.remove_from_playlist(1)


def test_reorder_swap_and_shift(db, tmp_path):
    a, b, c = add_videos(db, tmp_path)
    for vid in (a, b, c):
        db.add_to_playlist(vid)
    db.reorder_playlist(1, 2)
    assert playlist_ids(db) == [b, a, c]
    db.reorder_playlist(3, 1)
    assert playlist_ids(db) == [c, b, a]
    assert [p["position"] for p in db.get_playlist()] == [1, 2, 3]


def test_reorder_invalid_position_leaves_playlist_unchanged(db, tmp_path):
    a, b, _ = add_videos(db, tmp_path)
    db.add_to_playlist(a)
    db.add_to_playlist(b)
    with pytest.raises(ValueError):
        db.reorder_playlist(1, 5)
    assert playlist_ids(db) == [a, b]


def test_soft_delete_rejected_when_in_playlist(db, tmp_path):
    a, _, _ = add_videos(db, tmp_path)
    db.add_to_playlist(a)
    with pytest.raises(ValueError):
        db.soft_delete_video(a, str(tmp_path / "trash"))
    assert len(db.get_available_videos()) == 3


def test_soft_delete_moves_file_and_flags_video(db, tmp_path):
    a, _, _ = add_videos(db, tmp_path)
    source = tmp_path / "video0.mp4"
    conn = db.connect()
    conn.execute("INSERT INTO remote_presets (preset_key, video_id) VALUES (1, ?)", (a,))
    conn.close()

    trashed = db.soft_delete_video(a, str(tmp_path / "trash"))

    assert not source.exists()
    assert (tmp_path / "trash").joinpath(trashed.rsplit("/", 1)[1]).exists()
    assert trashed.endswith("_video0.mp4")
    assert a not in [v["id"] for v in db.get_available_videos()]
    conn = db.connect()
    try:
        row = conn.execute("SELECT is_deleted, deleted_at FROM videos WHERE id = ?", (a,)).fetchone()
        assert row["is_deleted"] == 1 and row["deleted_at"] is not None
        assert conn.execute("SELECT COUNT(*) FROM remote_presets").fetchone()[0] == 0
    finally:
        conn.close()


def test_soft_delete_rolls_back_when_file_missing(db, tmp_path):
    a, _, _ = add_videos(db, tmp_path)
    (tmp_path / "video0.mp4").unlink()
    with pytest.raises(FileNotFoundError):
        db.soft_delete_video(a, str(tmp_path / "trash"))
    assert a in [v["id"] for v in db.get_available_videos()]


def test_create_backup_is_valid_snapshot(db, tmp_path):
    add_videos(db, tmp_path)
    path = db.create_backup("pre_edit")
    assert "svf_kiosk_pre_edit_" in path
    assert path.startswith(str(db.backup_dir))
    snapshot = sqlite3.connect(path)
    try:
        assert snapshot.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 3
    finally:
        snapshot.close()
    assert not list(db.backup_dir.glob("*.tmp"))


def test_backup_rotation_keeps_20_most_recent(db):
    created = [db.create_backup("auto") for _ in range(25)]
    db.rotate_backups()
    remaining = [str(p) for p in db.list_backups()]
    assert len(remaining) == 20
    assert remaining == created[-20:]


def test_rotation_with_custom_keep_count(db):
    for _ in range(5):
        db.create_backup("auto")
    db.rotate_backups(keep_count=2)
    assert len(db.list_backups()) == 2


def test_json_mirror_is_written_atomically(db, tmp_path):
    a, b, _ = add_videos(db, tmp_path)
    db.add_to_playlist(b)
    db.add_to_playlist(a)
    path = db.export_json_mirror()
    assert path == str(db.data_dir / "playlist.json")
    data = json.loads((db.data_dir / "playlist.json").read_text(encoding="utf-8"))
    assert [i["position"] for i in data["playlist"]] == [1, 2]
    assert [i["id"] for i in data["playlist"]] == [b, a]
    assert not list(db.data_dir.glob("*.tmp"))


def test_set_playlist_replaces_atomically(db, tmp_path):
    ids = [db.add_video(str(tmp_path / f"{n}.mp4"), n) for n in "abc"]
    db.set_playlist([ids[2], ids[0]])
    assert [r["video_id"] if "video_id" in r else r["id"] for r in db.get_playlist()] == [ids[2], ids[0]]
    assert [r["position"] for r in db.get_playlist()] == [1, 2]
    db.set_playlist([])
    assert db.get_playlist() == []


def test_set_playlist_rejects_unknown_and_duplicates_without_changes(db, tmp_path):
    a = db.add_video(str(tmp_path / "a.mp4"), "a")
    db.set_playlist([a])
    with pytest.raises(ValueError):
        db.set_playlist([a, 999])
    with pytest.raises(ValueError):
        db.set_playlist([a, a])
    assert [r["id"] for r in db.get_playlist()] == [a]
