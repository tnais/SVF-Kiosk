"""Pydantic models for video metadata and kiosk playback state."""

from datetime import datetime
from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class VideoMetadata(BaseModel):
    id: int | None = None
    file_path: str
    display_title: str
    description: str | None = ""
    duration_seconds: int = 0
    resolution: str = ""
    date_added: datetime | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        if PurePath(value).suffix.lower() not in {".mp4", ".mkv", ".mov", ".avi"}:
            raise ValueError("file_path must end with .mp4, .mkv, .mov, or .avi")
        return value

    @field_validator("display_title")
    @classmethod
    def validate_display_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_title must not be empty")
        if len(value) > 38:
            raise ValueError("display_title must be at most 38 characters")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 150:
            raise ValueError("description must be at most 150 characters")
        return value


class PlaylistItem(BaseModel):
    position: int = Field(ge=1)
    video: VideoMetadata


class RemotePreset(BaseModel):
    preset_key: int = Field(ge=1, le=9)
    video_id: int


class KioskState(BaseModel):
    is_playing: bool
    current_video: VideoMetadata | None
    elapsed_seconds: float
    total_seconds: float
    mode: Literal["ambient", "on_demand", "preview", "standby"]
