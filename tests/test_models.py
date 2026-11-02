"""Tests for SVF Kiosk Pydantic models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.models.video import KioskState, PlaylistItem, RemotePreset, VideoMetadata


def make_video(**overrides: object) -> VideoMetadata:
    data: dict[str, object] = {
        "file_path": "/media/archive/video.mp4",
        "display_title": "Video del museo",
    }
    data.update(overrides)
    return VideoMetadata(**data)


def test_title_longer_than_38_characters_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_video(display_title="x" * 39)


def test_title_is_trimmed_before_length_validation() -> None:
    video = make_video(display_title="  Titolo valido  ")

    assert video.display_title == "Titolo valido"


@pytest.mark.parametrize("title", ["", "   "])
def test_empty_title_is_rejected(title: str) -> None:
    with pytest.raises(ValidationError):
        make_video(display_title=title)


def test_description_longer_than_150_characters_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_video(description="x" * 151)


@pytest.mark.parametrize("file_path", ["video.wmv", "video", "video.mp4.exe"])
def test_unsupported_video_extension_is_rejected(file_path: str) -> None:
    with pytest.raises(ValidationError):
        make_video(file_path=file_path)


def test_valid_video_and_nested_models_serialize_to_dict_and_json() -> None:
    date_added = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    video = make_video(date_added=date_added, description=None)
    playlist_item = PlaylistItem(position=1, video=video)
    preset = RemotePreset(preset_key=9, video_id=17)
    state = KioskState(
        is_playing=True,
        current_video=video,
        elapsed_seconds=12.5,
        total_seconds=90.0,
        mode="on_demand",
    )

    data = state.model_dump(mode="json")
    assert data["current_video"]["display_title"] == "Video del museo"
    assert data["current_video"]["date_added"] == "2026-11-02T12:00:00Z"
    assert playlist_item.model_dump()["video"]["file_path"] == video.file_path
    assert preset.model_dump() == {"preset_key": 9, "video_id": 17}

    restored = KioskState.model_validate_json(state.model_dump_json())
    assert restored == state


@pytest.mark.parametrize("preset_key", [0, 10])
def test_remote_preset_key_must_be_between_1_and_9(preset_key: int) -> None:
    with pytest.raises(ValidationError):
        RemotePreset(preset_key=preset_key, video_id=1)


def test_kiosk_state_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        KioskState(
            is_playing=False,
            current_video=None,
            elapsed_seconds=0,
            total_seconds=0,
            mode="maintenance",
        )
