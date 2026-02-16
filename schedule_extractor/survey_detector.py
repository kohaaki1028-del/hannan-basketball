"""Detect survey/questionnaire messages and extract deadlines."""

import re
from datetime import datetime
from typing import Optional

from line_parser.models import ChatMessage, ParsedSchedule
from config import SURVEY_KEYWORDS
from schedule_extractor.date_parser import extract_datetime

# URL patterns (LINE internal and regular URLs)
_URL_PATTERN = re.compile(r'((?:https?://|line://)\S+)')

# Deadline patterns: 〇日までに, 〇日締切, 〇日〆切
_DEADLINE_PATTERNS = [
    re.compile(r'(\d{1,2})/(\d{1,2})\s*まで'),
    re.compile(r'(\d{1,2})月(\d{1,2})日\s*まで'),
    re.compile(r'(\d{1,2})/(\d{1,2})\s*締'),
    re.compile(r'(\d{1,2})月(\d{1,2})日\s*締'),
    re.compile(r'(\d{1,2})/(\d{1,2})\s*〆'),
    re.compile(r'(\d{1,2})月(\d{1,2})日\s*〆'),
]

# General date pattern for extracting event dates (non-deadline dates)
_GENERAL_DATE = re.compile(
    r'(\d{1,2})/(\d{1,2})\([月火水木金土日]\)'
)


def is_survey_message(text: str) -> bool:
    """Check if a message is related to surveys/questionnaires."""
    return any(kw in text for kw in SURVEY_KEYWORDS)


def extract_urls(text: str) -> list[str]:
    """Extract URLs from text."""
    return _URL_PATTERN.findall(text)


def _resolve_year(month: int, day: int, reference: datetime) -> int:
    """Resolve year for MM/DD dates."""
    try:
        candidate = datetime(reference.year, month, day)
    except ValueError:
        return reference.year
    if (reference - candidate).days > 180:
        return reference.year + 1
    return reference.year


def _extract_deadline_date(text: str, reference: datetime) -> Optional[tuple[datetime, float]]:
    """Extract deadline date specifically from text.

    Looks for patterns like '2/9まで', '2/9締切', '2/9〆切' and returns that date.
    Returns (datetime, confidence) or None.
    """
    for pattern in _DEADLINE_PATTERNS:
        m = pattern.search(text)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = _resolve_year(month, day, reference)
            try:
                return datetime(year, month, day), 0.92
            except ValueError:
                continue
    return None


def _extract_event_date_from_survey(text: str, deadline_dt: datetime, reference: datetime) -> Optional[datetime]:
    """From a survey message, extract the event date (different from the deadline).

    E.g., message says "2/9(月)締切  ◉2/14(土)◉ 合同練習..." → deadline=2/9, event=2/14.
    """
    for m in _GENERAL_DATE.finditer(text):
        month, day = int(m.group(1)), int(m.group(2))
        year = _resolve_year(month, day, reference)
        try:
            dt = datetime(year, month, day)
        except ValueError:
            continue
        # Return the first date that is NOT the deadline date
        if dt.date() != deadline_dt.date():
            return dt
    return None


def extract_survey_schedule(msg: ChatMessage) -> Optional[ParsedSchedule]:
    """Extract a survey deadline as a reminder event.

    Returns a ParsedSchedule with is_reminder=True if a deadline is found.
    The deadline date is used as event_datetime.
    The referenced event date (if found) is stored in referenced_event_date.
    """
    text = msg.text

    if not is_survey_message(text):
        return None

    # 1. Try deadline-specific extraction first (looks for 〇/〇締切, 〇/〇まで)
    result = _extract_deadline_date(text, msg.timestamp)
    referenced_event_date = None

    if result is not None:
        event_dt, confidence = result
        # Also find what event date this survey references
        referenced_event_date = _extract_event_date_from_survey(text, event_dt, msg.timestamp)
    else:
        # Fallback: use generic date extraction
        result = extract_datetime(text, msg.timestamp)
        if result is None:
            return None
        event_dt, confidence = result

    urls = extract_urls(text)

    # Build description
    desc_parts = [
        f'LINEアンケート回答期限',
        f'送信者: {msg.username}',
        f'元メッセージ: {msg.text[:200]}',
    ]
    if urls:
        desc_parts.append(f'リンク: {urls[0]}')

    return ParsedSchedule(
        event_datetime=event_dt,
        title='アンケート回答期限',
        description='\n'.join(desc_parts),
        source_message=msg,
        confidence=confidence,
        is_reminder=True,
        is_all_day=event_dt.hour == 0 and event_dt.minute == 0,
        urls=urls,
        referenced_event_date=referenced_event_date,
    )
