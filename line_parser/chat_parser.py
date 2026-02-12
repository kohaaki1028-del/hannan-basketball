"""Parser for LINE chat export text files.

Supports multiple LINE export formats:
- iOS/Android space-separated: "HH:MM ユーザー名 メッセージ"
- Desktop tab-separated: "HH:MM\\tユーザー名\\tメッセージ"
- Date headers: "2025.02.12 水曜日" or "2024/02/15(木)"
"""

import re
from datetime import datetime
from pathlib import Path

from line_parser.models import ChatMessage

# === Date header patterns ===
# Format 1: 2025.02.12 水曜日
_DATE_HEADER_DOT = re.compile(
    r'^(\d{4})\.(\d{1,2})\.(\d{1,2})\s+[月火水木金土日]曜日$'
)
# Format 2: 2024/02/15(木) or 2024/02/15(Thu)
_DATE_HEADER_SLASH_JA = re.compile(r'^(\d{4})/(\d{1,2})/(\d{1,2})\([月火水木金土日]\)')
_DATE_HEADER_SLASH_EN = re.compile(r'^(\d{4})/(\d{1,2})/(\d{1,2})\(\w{3}\)')

# === Message patterns ===
# Format 1 (space-separated, iOS/Android): "HH:MM ユーザー名 メッセージ"
# Username can contain spaces (e.g. "兼髙 綾子"), so we match known patterns
_MSG_PATTERN_SPACE = re.compile(r'^(\d{1,2}:\d{2})\s+(.+?)\s+(.+)$')
# Format 2 (tab-separated, desktop): "HH:MM\tユーザー名\tメッセージ"
_MSG_PATTERN_TAB = re.compile(r'^(\d{1,2}:\d{2})\t(.+?)\t(.+)$')
# AM/PM tab format
_MSG_PATTERN_AMPM_TAB = re.compile(r'^(午前|午後)(\d{1,2}:\d{2})\t(.+?)\t(.+)$')

# System message patterns (space-separated)
_SYSTEM_MSG_PATTERNS = [
    re.compile(r'がグループに追加しました'),
    re.compile(r'がメッセージの送信を取り消しました'),
    re.compile(r'が「.*」アルバムの名前を'),
    re.compile(r'アルバムを作成しました'),
    re.compile(r'アルバムに\d+件のコンテンツを追加しました'),
    re.compile(r'のプロフィール画像を変更しました'),
    re.compile(r'グループのプロフィール画像を変更しました'),
    re.compile(r'新しいノートを作成しました'),
]

# Attachment patterns
_PHOTO_KEYWORDS = ['画像', '[写真]']
_VIDEO_KEYWORDS = ['動画', '[動画]']
_STICKER_KEYWORDS = ['スタンプ', '[スタンプ]']
_FILE_KEYWORDS = ['[ファイル]']


def _parse_date_header(line: str) -> datetime | None:
    """Try to parse a date header line. Returns date or None."""
    # Try dot format first (most common in real exports)
    m = _DATE_HEADER_DOT.match(line)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # Try slash formats
    for pattern in [_DATE_HEADER_SLASH_JA, _DATE_HEADER_SLASH_EN]:
        m = pattern.match(line)
        if m:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _parse_time(time_str: str, ampm: str | None = None) -> tuple[int, int]:
    """Parse time string to (hour, minute)."""
    parts = time_str.split(':')
    hour, minute = int(parts[0]), int(parts[1])
    if ampm == '午後' and hour < 12:
        hour += 12
    elif ampm == '午前' and hour == 12:
        hour = 0
    return hour, minute


def _is_system_message(text: str) -> bool:
    """Check if text is a LINE system message."""
    return any(p.search(text) for p in _SYSTEM_MSG_PATTERNS)


def _is_attachment(text: str) -> tuple[bool, str]:
    """Check if text is an attachment. Returns (is_attachment, type)."""
    stripped = text.strip()
    for kw in _PHOTO_KEYWORDS:
        if stripped == kw:
            return True, 'photo'
    for kw in _VIDEO_KEYWORDS:
        if stripped == kw:
            return True, 'video'
    for kw in _STICKER_KEYWORDS:
        if stripped == kw:
            return True, 'sticker'
    for kw in _FILE_KEYWORDS:
        if stripped.startswith(kw):
            return True, 'file'
    return False, ''


def _try_parse_message(line: str, current_date: datetime) -> ChatMessage | None:
    """Try to parse a message line in various formats."""

    # Try tab-separated AM/PM first
    m = _MSG_PATTERN_AMPM_TAB.match(line)
    if m:
        ampm, time_str, username, text = m.group(1), m.group(2), m.group(3), m.group(4)
        hour, minute = _parse_time(time_str, ampm)
        timestamp = current_date.replace(hour=hour, minute=minute)
        is_attach, attach_type = _is_attachment(text)
        return ChatMessage(
            timestamp=timestamp,
            username=username,
            text=text,
            raw_line=line,
            has_photo=(attach_type == 'photo'),
        )

    # Try tab-separated
    m = _MSG_PATTERN_TAB.match(line)
    if m:
        time_str, username, text = m.group(1), m.group(2), m.group(3)
        hour, minute = _parse_time(time_str)
        timestamp = current_date.replace(hour=hour, minute=minute)
        is_attach, attach_type = _is_attachment(text)
        return ChatMessage(
            timestamp=timestamp,
            username=username,
            text=text,
            raw_line=line,
            has_photo=(attach_type == 'photo'),
        )

    # Try space-separated (iOS/Android export)
    m = _MSG_PATTERN_SPACE.match(line)
    if m:
        time_str = m.group(1)
        # The tricky part: username can contain spaces
        # We need to split "ユーザー名 メッセージ" correctly
        rest = line[len(time_str):].lstrip()
        username, text = _split_username_message(rest)
        if username and text:
            hour, minute = _parse_time(time_str)
            timestamp = current_date.replace(hour=hour, minute=minute)
            is_attach, attach_type = _is_attachment(text)
            return ChatMessage(
                timestamp=timestamp,
                username=username,
                text=text,
                raw_line=line,
                has_photo=(attach_type == 'photo'),
            )

    return None


def _split_username_message(rest: str) -> tuple[str, str]:
    """Split 'ユーザー名 メッセージ' where username may contain spaces.

    Strategy: Try splitting at each space from left to right.
    The first split that leaves a non-empty message wins.
    We prefer shorter usernames (split at first space).
    """
    parts = rest.split(' ', 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    return '', ''


def parse_line_chat(filepath: str | Path) -> list[ChatMessage]:
    """Parse a LINE chat export file and return a list of ChatMessage objects.

    Supports both space-separated (iOS/Android) and tab-separated (desktop) formats.

    Args:
        filepath: Path to the LINE .txt export file.

    Returns:
        List of parsed ChatMessage objects.
    """
    filepath = Path(filepath)
    messages: list[ChatMessage] = []
    current_date: datetime | None = None

    # Try various encodings
    for encoding in ['utf-8-sig', 'utf-8', 'shift_jis']:
        try:
            text = filepath.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise ValueError(f'Cannot decode file: {filepath}')

    lines = text.splitlines()

    for line in lines:
        line = line.rstrip()

        if not line:
            continue

        # Try date header
        date = _parse_date_header(line)
        if date is not None:
            current_date = date
            continue

        # Skip if no date context yet (header lines)
        if current_date is None:
            continue

        # Try message line
        msg = _try_parse_message(line, current_date)
        if msg:
            # Skip system messages but still add photo/attachment messages
            if _is_system_message(msg.text) and not msg.has_photo:
                continue
            # Skip pure sticker/video messages
            is_attach, attach_type = _is_attachment(msg.text.strip())
            if is_attach and attach_type in ('sticker', 'video'):
                continue
            messages.append(msg)
        elif messages:
            # Multi-line message continuation
            stripped = line.strip()
            if stripped and not any(kw in stripped for kw in _STICKER_KEYWORDS):
                messages[-1].text += '\n' + line

    return messages
