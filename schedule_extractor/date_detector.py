"""Detect messages that contain date/time information."""

import re

from line_parser.models import ChatMessage
from config import CANCEL_KEYWORDS

# Date patterns that indicate a message contains schedule info
_DATE_PATTERNS = [
    # MM/DD or M/D (with optional time)
    re.compile(r'\d{1,2}/\d{1,2}'),
    # M月D日
    re.compile(r'\d{1,2}月\d{1,2}日'),
    # YYYY/MM/DD or YYYY-MM-DD
    re.compile(r'\d{4}[/\-]\d{1,2}[/\-]\d{1,2}'),
    # Relative date expressions
    re.compile(r'明日|明後日|今日'),
    re.compile(r'来週|今週|再来週'),
    re.compile(r'来月|今月'),
    re.compile(r'今度の[月火水木金土日]'),
    re.compile(r'次の[月火水木金土日]'),
    re.compile(r'次回'),
    # Day of week with time
    re.compile(r'[月火水木金土日]曜'),
]

# Time patterns
_TIME_PATTERNS = [
    re.compile(r'\d{1,2}:\d{2}'),
    re.compile(r'\d{1,2}時'),
    re.compile(r'午前|午後'),
]

# Exclude patterns (not schedule-related)
_EXCLUDE_PATTERNS = [
    re.compile(r'^\[スタンプ\]$'),
    re.compile(r'^\[写真\]$'),
    re.compile(r'^画像$'),
    re.compile(r'^\[動画\]$'),
    re.compile(r'^動画$'),
    re.compile(r'^\[ボイスメッセージ\]$'),
    re.compile(r'^PDF書類'),
    re.compile(r'^スタンプ$'),
]


def has_date_info(text: str) -> bool:
    """Check if text contains any date/time patterns."""
    return any(p.search(text) for p in _DATE_PATTERNS)


def has_time_info(text: str) -> bool:
    """Check if text contains time patterns."""
    return any(p.search(text) for p in _TIME_PATTERNS)


def is_cancelled(text: str) -> bool:
    """Check if the message indicates cancellation."""
    return any(kw in text for kw in CANCEL_KEYWORDS)


def is_excluded(text: str) -> bool:
    """Check if the message should be excluded (stickers, photos, etc.)."""
    stripped = text.strip()
    return any(p.match(stripped) for p in _EXCLUDE_PATTERNS)


def filter_schedule_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Filter messages that contain date/time information.

    Returns messages that have date info and are not cancelled/excluded.
    """
    results = []
    for msg in messages:
        text = msg.text.strip()
        if is_excluded(text):
            continue
        if is_cancelled(text):
            continue
        if has_date_info(text):
            results.append(msg)
    return results
