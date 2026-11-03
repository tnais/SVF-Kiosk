import subprocess
from pathlib import Path
from unittest import mock

import pytest

from src.cli import usb_sync
from src.core.strings import ItalianStrings as S


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_list_partitions_ignores_whole_disks(tmp_path):
    for n in ("sda", "sda1", "sdb", "sdb1", "sdb2"):
        (tmp_path / n).touch()
    assert [Path(p).name for p in usb_sync.list_partitions(str(tmp_path / "sd*"))] == [
        "sda1", "sdb1", "sdb2"]


def test_mount_parses_mount_point():
    out = "Mounted /dev/sdb1 at /media/svf-operatore/CHIAVETTA."
    with mock.patch("subprocess.run", return_value=completed(out)) as run:
        assert usb_sync.mount_device("/dev/sdb1") == "/media/svf-operatore/CHIAVETTA"
    assert run.call_args.args[0] == ["udisksctl", "mount", "-b", "/dev/sdb1"]


def test_mount_already_mounted():
    err = "Error mounting /dev/sdb1: GDBus.Error:org.freedesktop.UDisks2.Error.AlreadyMounted: Device /dev/sdb1 is already mounted at `/media/x'."
    with mock.patch("subprocess.run", return_value=completed("", 1, err)):
        assert usb_sync.mount_device("/dev/sdb1") == "/media/x"


def test_mount_failure_raises_italian_error():
    with mock.patch("subprocess.run", return_value=completed("", 1, "boom")):
        with pytest.raises(usb_sync.UsbError, match="Impossibile montare"):
            usb_sync.mount_device("/dev/sdb1")


def test_unmount_command_and_failure():
    with mock.patch("subprocess.run", return_value=completed()) as run:
        usb_sync.unmount_device("/dev/sdb1")
    assert run.call_args.args[0] == ["udisksctl", "unmount", "-b", "/dev/sdb1"]
    with mock.patch("subprocess.run", return_value=completed("", 1)):
        with pytest.raises(usb_sync.UsbError, match="espellere"):
            usb_sync.unmount_device("/dev/sdb1")


def test_find_and_copy_new_videos(tmp_path):
    usb = tmp_path / "usb"
    (usb / "sub").mkdir(parents=True)
    (usb / "a.mp4").write_bytes(b"a" * 100)
    (usb / "sub" / "b.MKV").write_bytes(b"b" * 50)
    (usb / "doc.txt").write_text("x")
    (usb / ".hidden.mp4").write_bytes(b"h")
    videos = usb_sync.find_videos(usb)
    assert [v.name for v in videos] == ["a.mp4", "b.MKV"]

    incoming, archive = tmp_path / "in", tmp_path / "arch"
    archive.mkdir()
    (archive / "a.mp4").write_bytes(b"a" * 100)  # same name+size: skipped
    msgs = []
    copied, skipped = usb_sync.copy_new_videos(videos, incoming, archive, msgs.append)
    assert (copied, skipped) == (1, 1)
    assert (incoming / "b.MKV").read_bytes() == b"b" * 50
    assert not list(incoming.glob("*.part"))
    assert msgs and msgs[-1].endswith("100%")


def test_sync_device_unmounts_even_on_error(tmp_path):
    with mock.patch.object(usb_sync, "mount_device", return_value=str(tmp_path)), \
         mock.patch.object(usb_sync, "find_videos", side_effect=RuntimeError("x")), \
         mock.patch.object(usb_sync, "unmount_device") as um:
        with pytest.raises(RuntimeError):
            usb_sync.sync_device("/dev/sdb1", tmp_path, lambda m: None)
    um.assert_called_once_with("/dev/sdb1")


def test_sync_device_summary_messages(tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    (usb / "a.mp4").write_bytes(b"x" * 10)
    out = []
    root = tmp_path / "root"
    with mock.patch.object(usb_sync, "mount_device", return_value=str(usb)), \
         mock.patch.object(usb_sync, "unmount_device"):
        assert usb_sync.sync_device("/dev/sdb1", root, out.append) == 1
    assert S.MSG_USB_DETECTED.format(device="/dev/sdb1") in out
    assert S.MSG_USB_COPY_SUCCESS.format(count=1) in out




# ------------------------------------------------------------ main() / edge cases

@pytest.fixture
def root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SVF_ROOT", str(tmp_path))
    return tmp_path


def test_main_refused_during_visits(root_env, capsys):
    with mock.patch.object(usb_sync, "operation_allowed", return_value=False), \
         mock.patch.object(usb_sync, "sync_device") as sync:
        assert usb_sync.main([]) == 2
    sync.assert_not_called()
    assert S.MSG_VISIT_HOUR_WARNING in capsys.readouterr().out


def test_main_no_device(root_env, capsys):
    with mock.patch.object(usb_sync, "list_partitions", return_value=[]):
        assert usb_sync.main(["--force"]) == 1
    out = capsys.readouterr().out
    assert S.MSG_FORCE_ACTIVE in out and S.MSG_USB_NO_DEVICE in out


def test_main_uses_first_detected_partition(root_env):
    with mock.patch.object(usb_sync, "list_partitions", return_value=["/dev/sdb1", "/dev/sdc1"]), \
         mock.patch.object(usb_sync, "sync_device", return_value=0) as sync:
        assert usb_sync.main(["--force"]) == 0
    assert sync.call_args.args[0] == "/dev/sdb1"


def test_main_explicit_device_overrides_scan(root_env):
    with mock.patch.object(usb_sync, "list_partitions") as scan, \
         mock.patch.object(usb_sync, "sync_device", return_value=0) as sync:
        assert usb_sync.main(["--force", "--device", "/dev/sdd1"]) == 0
    scan.assert_not_called()
    assert sync.call_args.args[0] == "/dev/sdd1"


def test_main_reports_mount_error(root_env, capsys):
    with mock.patch.object(usb_sync, "mount_device",
                           side_effect=usb_sync.UsbError(S.MSG_USB_MOUNT_FAILED.format(device="/dev/sdb1"))):
        assert usb_sync.main(["--force", "--device", "/dev/sdb1"]) == 1
    assert "Impossibile montare" in capsys.readouterr().err


def test_main_reads_visit_hours_setting_from_db(root_env):
    from src.db.database import Database
    db = Database(root_env)
    with db.connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('visit_hours', '09:00-12:00')")
    with mock.patch.object(usb_sync, "operation_allowed", return_value=False) as allowed:
        usb_sync.main([])
    assert allowed.call_args.args[1] == "09:00-12:00"


def test_mount_output_without_mount_point_fails():
    with mock.patch("subprocess.run", return_value=completed("strange output")):
        with pytest.raises(usb_sync.UsbError):
            usb_sync.mount_device("/dev/sdb1")


def test_copy_handles_zero_byte_file(tmp_path):
    src = tmp_path / "empty.mp4"
    src.write_bytes(b"")
    copied, skipped = usb_sync.copy_new_videos([src], tmp_path / "in")
    assert (copied, skipped) == (1, 0)
    assert (tmp_path / "in" / "empty.mp4").exists()


def test_copy_creates_missing_incoming_and_ignores_missing_archive(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    incoming = tmp_path / "deep" / "incoming"
    assert usb_sync.copy_new_videos([src], incoming, tmp_path / "no_archive") == (1, 0)
    assert (incoming / "a.mp4").exists()


def test_failed_copy_leaves_no_final_file(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x" * 10)
    incoming = tmp_path / "in"

    def boom(msg):
        raise OSError("disk full")

    with pytest.raises(OSError):
        usb_sync.copy_new_videos([src], incoming, progress=boom)
    assert not (incoming / "a.mp4").exists()


def test_different_size_same_name_is_copied(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"new content")
    incoming = tmp_path / "in"
    incoming.mkdir()
    (incoming / "a.mp4").write_bytes(b"old")
    # same name but different size: treated as new and overwrites the stale file
    assert usb_sync.copy_new_videos([src], incoming) == (1, 0)
    assert (incoming / "a.mp4").read_bytes() == b"new content"
