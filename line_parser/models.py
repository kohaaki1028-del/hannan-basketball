"""Data models for LINE chat parsing and schedule extraction."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ChatMessage:
    """A single message parsed from a LINE chat export file."""
    timestamp: datetime
    username: str
    text: str
    raw_line: str = ''
    has_photo: bool = False
    photo_filename: Optional[str] = None


@dataclass
class ParsedSchedule:
    """A schedule event extracted from a chat message or image."""
    event_datetime: datetime
    end_datetime: Optional[datetime] = None
    title: str = ''
    description: str = ''
    source_message: Optional[ChatMessage] = None
    confidence: float = 1.0
    is_reminder: bool = False
    is_all_day: bool = False
    urls: list[str] = field(default_factory=list)
