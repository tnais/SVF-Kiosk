"""Python implementation for test guard."""

from datetime import datetime
from unittest import mock

from src.cli import guard, ingest
from src.core.mpv_client import MpvIpcError
from src.core.strings import ItalianStrings as S

# -------------------------------------------------------------------- guard

def test_parse_visit_hours_and_check():
    """Verify parse visit hours and check."""
    ranges = guard.parse_visit_hours("09:30-12:30, 14:30-18:00, junk")
    assert len(ranges) == 2
    assert guard.in_visit_hours(datetime(2026, 1, 1, 10, 0), ranges)
    assert not guard.in_visit_hours(datetime(2026, 1, 1, 13, 0), ranges)


def fake_client(running=True, idle=False, paused=False):
    """Handle fake client operations."""
    c = mock.Mock()
    c.is_running.return_value = running
    c.get_property.side_effect = lambda n: {"idle-active": idle, "pause": paused}[n]
    return c


def test_operation_blocked_when_kiosk_playing():
    """Verify operation blocked when kiosk playing."""
    assert not guard.operation_allowed(fake_client())


def test_operation_allowed_when_paused_idle_or_down():
    """Verify operation allowed when paused idle or down."""
    assert guard.operation_allowed(fake_client(paused=True))
    assert guard.operation_allowed(fake_client(idle=True))
    assert guard.operation_allowed(fake_client(running=False))


def test_operation_blocked_in_visit_hours_and_force_overrides():
    """Verify operation blocked in visit hours and force overrides."""
    now = datetime(2026, 1, 1, 10, 0)
    down = fake_client(running=False)
    assert not guard.operation_allowed(down, "09:00-12:00", now)
    assert guard.operation_allowed(down, "09:00-12:00", now, force=True)


def test_main_refuses_during_visits(monkeypatch, tmp_path, capsys):
    """Verify main refuses during visits."""
    monkeypatch.setenv("SVF_ROOT", str(tmp_path))
    with mock.patch.object(ingest, "operation_allowed", return_value=False):
        assert ingest.main([]) == 2
    assert S.MSG_VISIT_HOUR_WARNING in capsys.readouterr().out




def test_kiosk_is_playing_false_on_ipc_error():
    """Verify kiosk is playing false on ipc error."""
    c = mock.Mock()
    c.is_running.return_value = True
    c.get_property.side_effect = MpvIpcError("gone")
    assert guard.kiosk_is_playing(c) is False


def test_parse_visit_hours_empty_and_none():
    """Verify parse visit hours empty and none."""
    assert guard.parse_visit_hours(None) == []
    assert guard.parse_visit_hours("") == []
    assert guard.parse_visit_hours("25:00-26:00") == []


def test_visit_range_boundaries_are_inclusive():
    """Verify visit range boundaries are inclusive."""
    ranges = guard.parse_visit_hours("09:00-12:00")
    assert guard.in_visit_hours(datetime(2026, 1, 1, 9, 0), ranges)
    assert guard.in_visit_hours(datetime(2026, 1, 1, 12, 0), ranges)
    assert not guard.in_visit_hours(datetime(2026, 1, 1, 12, 1), ranges)
