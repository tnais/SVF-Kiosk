import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from src.cli import ingest
from src.core.mpv_client import MpvIpcError
from src.core.strings import ItalianStrings as S
from src.db.database import Database

FFPROBE_OK = json.dumps({
    "format": {"duration": "61.6"},
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
        {"codec_type": "audio", "channels": 2},
    ],
})


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def scripted(answers):
    it = iter(answers)
    prompts = []

    def fn(prompt):
        prompts.append(prompt)
        return next(it)

    fn.prompts = prompts
    return fn


# ------------------------------------------------------------------- ingest

def test_probe_video_parses_ffprobe_json():
    with mock.patch("subprocess.run", return_value=completed(FFPROBE_OK)) as run:
        info = ingest.probe_video("/x/a.mp4")
    assert info == {"duration_seconds": 62, "resolution": "1920x1080",
                    "video_codec": "h264", "audio_channels": 2}
    assert "json" in run.call_args.args[0]


def test_probe_video_errors():
    with mock.patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(ingest.ProbeError, match="ffprobe"):
            ingest.probe_video("a.mp4")
    with mock.patch("subprocess.run", return_value=completed("", 1)):
        with pytest.raises(ingest.ProbeError):
            ingest.probe_video("a.mp4")
    with mock.patch("subprocess.run", return_value=completed(json.dumps({"streams": []}))):
        with pytest.raises(ingest.ProbeError):
            ingest.probe_video("a.mp4")


def test_sanitize_filename():
    assert ingest.sanitize_filename("Locomotiva è già così.MP4") == "Locomotiva_e_gia_cosi.mp4"
    assert ingest.sanitize_filename("../../x y.mkv") == "x_y.mkv"
    assert ingest.sanitize_filename("???.mp4") == "video.mp4"


def test_unique_destination(tmp_path):
    (tmp_path / "a.mp4").touch()
    assert ingest.unique_destination(tmp_path, "a.mp4").name == "a__1.mp4"
    (tmp_path / "a__1.mp4").touch()
    assert ingest.unique_destination(tmp_path, "a.mp4").name == "a__2.mp4"


def test_title_and_description_validation_loops():
    out = []
    title = ingest.ask_title(scripted(["", "x" * 39, "  Titolo  "]), out.append)
    assert title == "Titolo"
    assert out[0] == S.MSG_INGEST_TITLE_EMPTY
    assert "39" in out[1] and "38" in out[1]
    out.clear()
    assert ingest.ask_description(scripted(["y" * 151, "ok"]), out.append) == "ok"
    assert "151" in out[0]
    assert ingest.ask_title(scripted(["x" * 38]), print) == "x" * 38


def make_incoming(tmp_path, *names):
    incoming = tmp_path / "media" / "incoming"
    incoming.mkdir(parents=True)
    for n in names:
        (incoming / n).write_bytes(b"data")
    return incoming


def test_run_ingest_full_flow(tmp_path):
    incoming = make_incoming(tmp_path, "Mio Film.mp4", "note.txt")
    out = []
    answers = scripted(["Il mio film", "Una descrizione"])
    with mock.patch("subprocess.run", return_value=completed(FFPROBE_OK)):
        done, skipped = ingest.run_ingest(tmp_path, answers, out.append)
    assert (done, skipped) == (1, 0)
    archived = tmp_path / "media" / "archive" / "Mio_Film.mp4"
    assert archived.exists() and (incoming / "note.txt").exists()
    assert not (incoming / "Mio Film.mp4").exists()
    videos = Database(tmp_path).get_available_videos()
    assert videos[0]["display_title"] == "Il mio film"
    assert videos[0]["file_path"] == str(archived)
    assert videos[0]["resolution"] == "1920x1080"
    names = [p.name for p in Database(tmp_path).list_backups()]
    assert any("pre_ingest" in n for n in names) and any("post_ingest" in n for n in names)
    assert (tmp_path / "data" / "playlist.json").exists()
    assert out[-1] == S.MSG_INGEST_SUMMARY.format(done=1, skipped=0)


def test_run_ingest_nothing_to_do(tmp_path):
    out = []
    assert ingest.run_ingest(tmp_path, scripted([]), out.append) == (0, 0)
    assert "Nessun filmato" in out[0]


def test_run_ingest_skips_unprobeable_file(tmp_path):
    incoming = make_incoming(tmp_path, "bad.mp4")
    with mock.patch("subprocess.run", return_value=completed("", 1)):
        assert ingest.run_ingest(tmp_path, scripted([]), lambda m: None) == (0, 1)
    assert (incoming / "bad.mp4").exists()


def test_preview_accepted_calls_play_preview(tmp_path):
    make_incoming(tmp_path, "a.mp4")
    client = mock.Mock()
    answers = scripted(["S", "Titolo", ""])
    with mock.patch("subprocess.run", return_value=completed(FFPROBE_OK)):
        ingest.run_ingest(tmp_path, answers, lambda m: None, client)
    client.play_preview.assert_called_once()
    assert answers.prompts[0] == S.MSG_PREVIEW_PROMPT


def test_preview_declined_and_failure_do_not_block(tmp_path):
    make_incoming(tmp_path, "a.mp4", "b.mp4")
    client = mock.Mock()
    client.play_preview.side_effect = MpvIpcError("down")
    answers = scripted(["", "A", "", "s", "B", ""])
    out = []
    with mock.patch("subprocess.run", return_value=completed(FFPROBE_OK)):
        done, _ = ingest.run_ingest(tmp_path, answers, out.append, client)
    assert done == 2
    assert client.play_preview.call_count == 1
    assert any("Anteprima non disponibile" in m for m in out)


def test_db_failure_restores_file_and_still_runs_post_backup(tmp_path):
    incoming = make_incoming(tmp_path, "a.mp4")
    with mock.patch("subprocess.run", return_value=completed(FFPROBE_OK)), \
         mock.patch.object(Database, "add_video", side_effect=RuntimeError("db")):
        with pytest.raises(RuntimeError):
            ingest.run_ingest(tmp_path, scripted(["T", ""]), lambda m: None)
    assert (incoming / "a.mp4").exists()
    assert any("post_ingest" in p.name for p in Database(tmp_path).list_backups())


# ------------------------------------------------------------ gaps: main() and edges

def test_main_force_runs_wizard_without_client_when_mpv_down(monkeypatch, tmp_path):
    monkeypatch.setenv("SVF_ROOT", str(tmp_path))
    with mock.patch.object(ingest.MpvClient, "is_running", return_value=False), \
         mock.patch.object(ingest, "run_ingest") as run:
        assert ingest.main(["--force"]) == 0
    assert run.call_args.kwargs["client"] is None


def test_main_passes_client_when_mpv_running(monkeypatch, tmp_path):
    monkeypatch.setenv("SVF_ROOT", str(tmp_path))
    with mock.patch.object(ingest.MpvClient, "is_running", return_value=True), \
         mock.patch.object(ingest, "run_ingest") as run:
        ingest.main(["--force"])
    assert run.call_args.kwargs["client"] is not None


def test_main_reads_visit_hours_setting(monkeypatch, tmp_path):
    monkeypatch.setenv("SVF_ROOT", str(tmp_path))
    db = Database(tmp_path)
    with db.connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('visit_hours', '10:00-11:00')")
    with mock.patch.object(ingest, "operation_allowed", return_value=False) as allowed:
        assert ingest.main([]) == 2
    assert allowed.call_args.args[1] == "10:00-11:00"


def test_find_unindexed_missing_dir_and_case_insensitive(tmp_path):
    assert ingest.find_unindexed(tmp_path / "nope") == []
    inc = make_incoming(tmp_path, "A.MP4", "b.Mkv", "c.txt", "d.avi", "e.mov")
    assert [p.name for p in ingest.find_unindexed(inc)] == ["A.MP4", "b.Mkv", "d.avi", "e.mov"]


def test_probe_duration_falls_back_to_stream():
    data = json.dumps({"format": {}, "streams": [
        {"codec_type": "video", "codec_name": "hevc", "width": 1280, "height": 720,
         "duration": "10.2"}]})
    with mock.patch("subprocess.run", return_value=completed(data)):
        info = ingest.probe_video("a.mp4")
    assert info["duration_seconds"] == 10
    assert info["audio_channels"] == 0


def test_probe_invalid_json_raises():
    with mock.patch("subprocess.run", return_value=completed("not json")):
        with pytest.raises(ingest.ProbeError):
            ingest.probe_video("a.mp4")


@pytest.mark.parametrize("answer", ["si", "sì", "S", " s "])
def test_preview_accepts_italian_yes_variants(tmp_path, answer):
    make_incoming(tmp_path, "a.mp4")
    client = mock.Mock()
    with mock.patch("subprocess.run", return_value=completed(FFPROBE_OK)):
        ingest.run_ingest(tmp_path, scripted([answer, "T", ""]), lambda m: None, client)
    client.play_preview.assert_called_once()


@pytest.mark.parametrize("answer", ["n", "no", "", "x"])
def test_preview_rejects_other_answers(tmp_path, answer):
    make_incoming(tmp_path, "a.mp4")
    client = mock.Mock()
    with mock.patch("subprocess.run", return_value=completed(FFPROBE_OK)):
        ingest.run_ingest(tmp_path, scripted([answer, "T", ""]), lambda m: None, client)
    client.play_preview.assert_not_called()


def test_title_length_counts_characters_not_bytes():
    assert ingest.ask_title(scripted(["à" * 38]), print) == "à" * 38
    out = []
    assert ingest.ask_title(scripted(["à" * 39, "ok"]), out.append) == "ok"
    assert "39" in out[0]


def test_description_may_be_empty():
    assert ingest.ask_description(scripted([""]), print) == ""


def test_name_collision_in_archive_keeps_both_files(tmp_path):
    archive = tmp_path / "media" / "archive"
    archive.mkdir(parents=True)
    (archive / "a.mp4").write_bytes(b"old")
    make_incoming(tmp_path, "a.mp4")
    with mock.patch("subprocess.run", return_value=completed(FFPROBE_OK)):
        ingest.run_ingest(tmp_path, scripted(["T", ""]), lambda m: None)
    assert (archive / "a.mp4").read_bytes() == b"old"
    assert (archive / "a__1.mp4").exists()
