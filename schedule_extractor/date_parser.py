"""Japanese date/time parser with 3-tier strategy: regex → ja-timex → dateparser."""

import re
from datetime import datetime, timedelta
from typing import Optional

# ============================================================
# Tier 1: Regex patterns for explicit date/time formats
# ============================================================

# MM/DD HH:MM  e.g. "2/15 19:00"
_P_SLASH_DATE_TIME = re.compile(
    r'(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})'
)

# MM/DD(曜日) with optional time range  e.g. "2/16(日)" "2/22(土)9:00〜13:00"
_P_SLASH_DATE_DOW = re.compile(
    r'(\d{1,2})/(\d{1,2})\([月火水木金土日]\)(?:\s*(\d{1,2}):(\d{2}))?'
)

# MM/DD only  e.g. "2/15"
_P_SLASH_DATE = re.compile(
    r'(?<!\d)(\d{1,2})/(\d{1,2})(?!\d|/)'
)

# M月D日 H時M分  e.g. "3月1日 10時30分" or "3月1日 10時"
_P_KANJI_DATE_TIME = re.compile(
    r'(\d{1,2})月(\d{1,2})日\s*(\d{1,2})時(?:(\d{1,2})分)?'
)

# M月D日 only  e.g. "3月1日"
_P_KANJI_DATE = re.compile(
    r'(\d{1,2})月(\d{1,2})日'
)

# YYYY/MM/DD HH:MM  e.g. "2024/3/1 10:00"
_P_FULL_DATE_TIME = re.compile(
    r'(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})\s+(\d{1,2}):(\d{2})'
)

# YYYY/MM/DD only
_P_FULL_DATE = re.compile(
    r'(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})'
)

# Standalone time: H時M分, H時, HH:MM (with optional 午前/午後)
_P_TIME_AMPM = re.compile(
    r'(午前|午後)\s*(\d{1,2})(?:時|:)(\d{1,2})?(?:分)?'
)

_P_TIME_KANJI = re.compile(
    r'(?:朝|夜|昼)?\s*(\d{1,2})時(?:(\d{1,2})分)?'
)

_P_TIME_COLON = re.compile(
    r'(?<!\d)(\d{1,2}):(\d{2})(?!\d)'
)


def _resolve_year(month: int, day: int, reference: datetime) -> int:
    """Resolve year for MM/DD dates. Uses reference year, or next year if >6 months in past."""
    try:
        candidate = datetime(reference.year, month, day)
    except ValueError:
        return reference.year
    if (reference - candidate).days > 180:
        return reference.year + 1
    return reference.year


def _parse_time_from_text(text: str) -> Optional[tuple[int, int]]:
    """Extract time (hour, minute) from text using various patterns."""
    # 午前/午後 + time
    m = _P_TIME_AMPM.search(text)
    if m:
        ampm, hour = m.group(1), int(m.group(2))
        minute = int(m.group(3)) if m.group(3) else 0
        if ampm == '午後' and hour < 12:
            hour += 12
        elif ampm == '午前' and hour == 12:
            hour = 0
        return hour, minute

    # H時M分
    m = _P_TIME_KANJI.search(text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        return hour, minute

    # HH:MM (only if not part of a date pattern already matched)
    m = _P_TIME_COLON.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))

    return None


def _try_regex(text: str, reference: datetime) -> Optional[tuple[datetime, float]]:
    """Tier 1: Try regex patterns. Returns (datetime, confidence) or None."""

    # YYYY/MM/DD HH:MM (highest specificity)
    m = _P_FULL_DATE_TIME.search(text)
    if m:
        try:
            dt = datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5))
            )
            return dt, 0.98
        except ValueError:
            pass

    # YYYY/MM/DD only
    m = _P_FULL_DATE.search(text)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            time_info = _parse_time_from_text(text)
            if time_info:
                dt = dt.replace(hour=time_info[0], minute=time_info[1])
            return dt, 0.95
        except ValueError:
            pass

    # M月D日 H時M分
    m = _P_KANJI_DATE_TIME.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        hour, minute = int(m.group(3)), int(m.group(4)) if m.group(4) else 0
        year = _resolve_year(month, day, reference)
        try:
            return datetime(year, month, day, hour, minute), 0.95
        except ValueError:
            pass

    # M月D日 only
    m = _P_KANJI_DATE.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = _resolve_year(month, day, reference)
        try:
            dt = datetime(year, month, day)
            time_info = _parse_time_from_text(text)
            if time_info:
                dt = dt.replace(hour=time_info[0], minute=time_info[1])
            return dt, 0.90
        except ValueError:
            pass

    # MM/DD(曜日) with optional time  e.g. "2/16(日)" "2/22(土)9:00〜13:00"
    m = _P_SLASH_DATE_DOW.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            year = _resolve_year(month, day, reference)
            try:
                dt = datetime(year, month, day)
                if m.group(3) and m.group(4):
                    dt = dt.replace(hour=int(m.group(3)), minute=int(m.group(4)))
                else:
                    time_info = _parse_time_from_text(text)
                    if time_info:
                        dt = dt.replace(hour=time_info[0], minute=time_info[1])
                return dt, 0.92
            except ValueError:
                pass

    # MM/DD HH:MM
    m = _P_SLASH_DATE_TIME.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        hour, minute = int(m.group(3)), int(m.group(4))
        year = _resolve_year(month, day, reference)
        try:
            return datetime(year, month, day, hour, minute), 0.90
        except ValueError:
            pass

    # MM/DD only
    m = _P_SLASH_DATE.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            year = _resolve_year(month, day, reference)
            try:
                dt = datetime(year, month, day)
                time_info = _parse_time_from_text(text)
                if time_info:
                    dt = dt.replace(hour=time_info[0], minute=time_info[1])
                return dt, 0.85
            except ValueError:
                pass

    # Time-only: use reference date with extracted time
    time_info = _parse_time_from_text(text)
    if time_info:
        dt = reference.replace(hour=time_info[0], minute=time_info[1], second=0, microsecond=0)
        return dt, 0.60

    return None


def _try_ja_timex(text: str, reference: datetime) -> Optional[tuple[datetime, float]]:
    """Tier 2: Try ja-timex for relative expressions."""
    try:
        from ja_timex import TimexParser
        import pendulum
    except ImportError:
        return None

    try:
        tz = pendulum.timezone('Asia/Tokyo')
        ref = pendulum.instance(reference, tz=tz)
        parser = TimexParser(reference=ref)
        timexes = parser.parse(text)

        if not timexes:
            return None

        result_date = None
        result_time = None

        for timex in timexes:
            if timex.type == 'DATE':
                result_date = timex.to_datetime()
            elif timex.type == 'TIME':
                result_time = timex.to_datetime()

        if result_date:
            dt = result_date
            if result_time:
                dt = dt.replace(hour=result_time.hour, minute=result_time.minute)
            else:
                # Try extracting time with regex if ja-timex didn't find it
                time_info = _parse_time_from_text(text)
                if time_info:
                    dt = dt.replace(hour=time_info[0], minute=time_info[1])
            return dt, 0.80

    except Exception:
        pass

    return None


def _try_dateparser(text: str, reference: datetime) -> Optional[tuple[datetime, float]]:
    """Tier 3: Fallback to dateparser library."""
    try:
        import dateparser
    except ImportError:
        return None

    try:
        result = dateparser.parse(
            text,
            languages=['ja'],
            settings={
                'RELATIVE_BASE': reference,
                'TIMEZONE': 'Asia/Tokyo',
                'RETURN_AS_TIMEZONE_AWARE': False,
                'PREFER_DATES_FROM': 'future',
            }
        )
        if result:
            return result, 0.60
    except Exception:
        pass

    return None


def _make_naive(dt: datetime) -> datetime:
    """Strip timezone info to ensure all datetimes are naive (for consistency)."""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def extract_datetime(text: str, reference: datetime) -> Optional[tuple[datetime, float]]:
    """Extract datetime from Japanese text using a 3-tier strategy.

    Args:
        text: The message text to parse.
        reference: Reference datetime for resolving relative dates
                   (usually the message's timestamp).

    Returns:
        Tuple of (datetime, confidence) or None if no date found.
        Confidence: 0.0-1.0 (higher = more reliable).
    """
    # Tier 1: Regex (fast, high confidence for explicit formats)
    result = _try_regex(text, reference)
    if result:
        return _make_naive(result[0]), result[1]

    # Tier 2: ja-timex (relative expressions like 来週の土曜, 明日)
    result = _try_ja_timex(text, reference)
    if result:
        return _make_naive(result[0]), result[1]

    # Tier 3: dateparser (general fallback)
    result = _try_dateparser(text, reference)
    if result:
        return _make_naive(result[0]), result[1]

    return None


# Pattern to split multi-date messages into blocks
# Splits on ◉M/DD(曜日)◉ or ◉M月D日◉ or similar date markers
_BLOCK_SPLITTER = re.compile(
    r'(?=◉\s*\d{1,2}/\d{1,2}\([月火水木金土日]\)\s*◉)'
    r'|(?=◉\s*\d{1,2}月\d{1,2}日\s*◉)'
)


def extract_all_datetimes(text: str, reference: datetime) -> list[tuple[datetime, float, str]]:
    """Extract ALL datetimes from a message that may contain multiple date blocks.

    Messages like:
        ◉2/12(木)◉
        @田辺 16:30〜19:00
        ◉2/13(金)◉
        @常盤 16:30〜18:45

    Returns:
        List of (datetime, confidence, block_text) tuples.
    """
    # Try splitting by date block markers
    blocks = _BLOCK_SPLITTER.split(text)
    blocks = [b.strip() for b in blocks if b.strip()]

    # If only one block, fall back to single extraction
    if len(blocks) <= 1:
        result = extract_datetime(text, reference)
        if result:
            return [(result[0], result[1], text)]
        return []

    results = []
    for block in blocks:
        result = extract_datetime(block, reference)
        if result:
            dt, conf = _make_naive(result[0]), result[1]
            results.append((dt, conf, block))

    return results
