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
    re.compile(r'(\d{1,2})/(\d{1,2})まで'),
    re.compile(r'(\d{1,2})月(\d{1,2})日まで'),
    re.compile(r'(\d{1,2})/(\d{1,2})\s*締'),
    re.compile(r'(\d{1,2})月(\d{1,2})日\s*締'),
    re.compile(r'(\d{1,2})/(\d{1,2})\s*〆'),
    re.compile(r'(\d{1,2})月(\d{1,2})日\s*〆'),
]


def is_survey_message(text: str) -> bool:
    """Check if a message is related to surveys/questionnaires."""
    return any(kw in text for kw in SURVEY_KEYWORDS)


def extract_urls(text: str) -> list[str]:
    """Extract URLs from text."""
    return _URL_PATTERN.findall(text)


def extract_survey_schedule(msg: ChatMessage) -> Optional[ParsedSchedule]:
    """Extract a survey deadline as a reminder event.

    Returns a ParsedSchedule with is_reminder=True if a deadline is found.
    """
    text = msg.text

    if not is_survey_message(text):
        return None

    # Try to extract a deadline date
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
    )
