"""Visit-hour guard: ingestion must never happen while visitors are in the hall."""

from __future__ import annotations

from datetime import datetime, time

from ..core.mpv_client import MpvClient, MpvIpcError


def parse_visit_hours(value: str | None) -> list[tuple[time, time]]:
    """Parse ``"09:30-12:30,14:30-18:00"`` into time ranges; invalid parts are ignored."""
    ranges: list[tuple[time, time]] = []
    for part in (value or "").split(","):
        try:
            start, end = part.strip().split("-")
            ranges.append(
                (
                    datetime.strptime(start.strip(), "%H:%M").time(),
                    datetime.strptime(end.strip(), "%H:%M").time(),
                )
            )
        except ValueError:
            continue
    return ranges


def in_visit_hours(now: datetime, ranges: list[tuple[time, time]]) -> bool:
    current = now.time()
    return any(start <= current <= end for start, end in ranges)


def kiosk_is_playing(client: MpvClient) -> bool:
    """True when mpv answers and is actively playing (not paused or idle)."""
    try:
        if not client.is_running():
            return False
        if client.get_property("idle-active"):
            return False
        return not client.get_property("pause")
    except MpvIpcError:
        return False


def operation_allowed(
    client: MpvClient,
    visit_hours: str | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> bool:
    if force:
        return True
    if in_visit_hours(now or datetime.now(), parse_visit_hours(visit_hours)):
        return False
    return not kiosk_is_playing(client)
