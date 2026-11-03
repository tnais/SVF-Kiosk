"""Tests for the svf-presets CLI."""

import pytest

from src.cli import presets
from src.core.strings import ItalianStrings as S
from src.db.database import Database


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SVF_ROOT", str(tmp_path))
    db = Database(tmp_path)
    ids = {}
    for title in ["Locomotiva 740", "Locomotiva 625", "Stazione"]:
        f = tmp_path / f"{title}.mp4"
        f.write_bytes(b"x")
        ids[title] = db.add_video(str(f), title, "", 10, "1920x1080")
    return db, ids


def run(argv, capsys):
    code = presets.main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_find_videos_exact_beats_substring():
    vids = [{"display_title": "Stazione"}, {"display_title": "Stazione Nord"}]
    assert presets.find_videos(vids, "stazione") == [vids[0]]
    assert len(presets.find_videos(vids, "staz")) == 2
    assert presets.find_videos(vids, "") == []


@pytest.mark.parametrize("v,exp", [("1", 1), ("9", 9), ("0", None), ("10", None), ("x", None), ("-1", None)])
def test_parse_key(v, exp):
    assert presets.parse_key(v) == exp


def test_list_empty_shows_nine_free_keys(env, capsys):
    code, out, _ = run(["list"], capsys)
    assert code == 0 and out.count(S.MSG_PRESETS_FREE.format(key=1)) == 1
    assert len(out.strip().splitlines()) == 10


def test_set_by_title_then_list(env, capsys):
    db, ids = env
    code, out, _ = run(["set", "3", "stazione"], capsys)
    assert code == 0 and S.MSG_PRESETS_SET.format(key=3, title="Stazione") in out
    assert db.get_remote_presets()[3]["id"] == ids["Stazione"]
    _, out, _ = run(["list"], capsys)
    assert "Stazione" in out


def test_set_by_id(env, capsys):
    db, ids = env
    code, _, _ = run(["set", "1", "--id", str(ids["Stazione"])], capsys)
    assert code == 0 and db.get_remote_presets()[1]["id"] == ids["Stazione"]


def test_set_ambiguous_lists_candidates_and_changes_nothing(env, capsys):
    db, ids = env
    code, _, err = run(["set", "2", "locomotiva"], capsys)
    assert code == 1 and S.MSG_PRESETS_AMBIGUOUS.format(title="locomotiva") in err
    assert S.MSG_PRESETS_CANDIDATE.format(id=ids["Locomotiva 740"], title="Locomotiva 740") in err
    assert db.get_remote_presets() == {}


def test_set_not_found(env, capsys):
    code, _, err = run(["set", "2", "zzz"], capsys)
    assert code == 1 and S.MSG_PRESETS_NOT_FOUND.format(title="zzz") in err
    code, _, err = run(["set", "2", "--id", "9999"], capsys)
    assert code == 1


@pytest.mark.parametrize("cmd", [["set", "0", "Stazione"], ["set", "10", "Stazione"], ["clear", "x"]])
def test_bad_key(env, capsys, cmd):
    code, _, err = run(cmd, capsys)
    assert code == 2 and S.MSG_PRESETS_BAD_KEY in err


def test_set_requires_title_or_id(env, capsys):
    with pytest.raises(SystemExit):
        presets.main(["set", "1"])


def test_clear_existing_and_missing(env, capsys):
    db, ids = env
    run(["set", "4", "Stazione"], capsys)
    code, out, _ = run(["clear", "4"], capsys)
    assert code == 0 and S.MSG_PRESETS_CLEARED.format(key=4) in out
    assert db.get_remote_presets() == {}
    code, out, _ = run(["clear", "4"], capsys)
    assert code == 0 and S.MSG_PRESETS_NOT_SET.format(key=4) in out


def test_changes_create_pre_and_post_backups(env, capsys):
    db, _ = env
    before = len(db.list_backups())
    run(["set", "1", "Stazione"], capsys)
    assert len(db.list_backups()) >= before + 1


def test_accented_and_long_titles(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SVF_ROOT", str(tmp_path))
    db = Database(tmp_path)
    f = tmp_path / "a.mp4"
    f.write_bytes(b"x")
    title = "Locomotività è più ù—" + "x" * 17
    assert len(title) <= 38
    db.add_video(str(f), title)
    code, out, _ = run(["set", "1", "LOCOMOTIVITÀ"], capsys)
    assert code == 0 and title in out
    assert run(["list"], capsys)[1].count(title) == 1


def test_set_by_id_of_soft_deleted_video_is_rejected(env, capsys):
    db, ids = env
    db.soft_delete_video(ids["Stazione"], str(db.root / "trash"))
    code, _, err = run(["set", "1", "--id", str(ids["Stazione"])], capsys)
    assert code == 1 and db.get_remote_presets() == {}


def test_soft_deleted_video_is_not_matched_by_title(env, capsys):
    db, ids = env
    db.soft_delete_video(ids["Stazione"], str(db.root / "trash"))
    assert run(["set", "1", "Stazione"], capsys)[0] == 1
