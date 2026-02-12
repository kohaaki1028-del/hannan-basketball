"""Main extraction pipeline: combines date detection, parsing, and survey detection."""

from datetime import timedelta
from typing import Optional

from line_parser.models import ChatMessage, ParsedSchedule
from config import DEFAULT_EVENT_DURATION_HOURS, EVENT_TYPE_KEYWORDS
from schedule_extractor.date_detector import filter_schedule_messages, has_time_info
from schedule_extractor.date_parser import extract_datetime, extract_all_datetimes
from schedule_extractor.survey_detector import extract_survey_schedule, is_survey_message


def _extract_event_title(text: str) -> str:
    """Extract a concise event title from message text."""
    for keyword, label in sorted(EVENT_TYPE_KEYWORDS.items(), key=lambda x: -len(x[0])):
        if keyword in text:
            return label
    if '集合' in text and ('配車' in text or '号' in text):
        return '集合'
    return '予定'


# Title priority: higher number = more specific, preferred as main title
_TITLE_PRIORITY = {
    '予定': 0,
    '集合': 1,
    '練習': 2,
    '体育館練習': 2,
    '練習試合': 3,
    '試合': 4,
    '公式戦': 5,
    '大会': 5,
    'トーナメント': 5,
    '打ち上げ': 3,
    'アンケート回答期限': 0,
}


def _same_day(dt1, dt2) -> bool:
    return dt1.date() == dt2.date()


# Title groups: titles considered the same activity
_TITLE_GROUPS = [
    {'試合', '練習試合', '公式戦', '大会', 'トーナメント'},
    {'練習', '体育館練習'},
]


def _titles_related(t1: str, t2: str) -> bool:
    """Check if two titles refer to the same kind of event."""
    if t1 == t2:
        return True
    for group in _TITLE_GROUPS:
        if t1 in group and t2 in group:
            return True
    # 集合 is always related to any sports event on the same day
    if '集合' in (t1, t2):
        other = t2 if t1 == '集合' else t1
        if other in {'試合', '練習試合', '公式戦', '大会', '練習', '体育館練習', 'トーナメント'}:
            return True
    # 「予定」(generic) is absorbed by any specific title on the same day
    if '予定' in (t1, t2):
        other = t2 if t1 == '予定' else t1
        if other != '予定':
            return True
    return False


def _classify_message(text: str) -> str:
    """Classify message content for description sections."""
    if '配車' in text or '号' in text:
        return '配車'
    if '弁当' in text or 'お昼' in text or '注文' in text:
        return 'お弁当'
    if '集合' in text and ('時間' in text or '場所' in text):
        return '集合・会場'
    if '服装' in text or 'ユニフォーム' in text:
        return '服装'
    if any(k in text for k in ('試合', '練習試合', '公式戦', '大会', 'トーナメント', '練習')):
        return '詳細'
    return '連絡'


def _merge_descriptions(existing: ParsedSchedule, candidate: ParsedSchedule) -> str:
    """Merge two event descriptions into organized sections."""
    # Extract source message texts
    existing_text = existing.source_message.text if existing.source_message else ''
    candidate_text = candidate.source_message.text if candidate.source_message else ''

    # Classify each
    existing_label = _classify_message(existing_text)
    candidate_label = _classify_message(candidate_text)

    # If existing description already has sections (was previously merged), append
    if '━━━' in existing.description:
        new_section = f'\n\n━━━ {candidate_label} ━━━\n'
        new_section += f'{candidate.source_message.username}: {candidate_text[:300]}'
        return existing.description + new_section

    # Build fresh merged description
    parts = []
    parts.append(f'━━━ {existing_label} ━━━')
    parts.append(f'{existing.source_message.username}: {existing_text[:300]}')
    parts.append(f'\n━━━ {candidate_label} ━━━')
    parts.append(f'{candidate.source_message.username}: {candidate_text[:300]}')
    return '\n'.join(parts)


def _merge_events(existing: ParsedSchedule, candidate: ParsedSchedule) -> ParsedSchedule:
    """Merge candidate into existing, combining descriptions and picking best metadata."""
    # Pick the best title (highest priority)
    e_pri = _TITLE_PRIORITY.get(existing.title, 0)
    c_pri = _TITLE_PRIORITY.get(candidate.title, 0)
    title = candidate.title if c_pri > e_pri else existing.title

    # Pick best datetime: timed > all-day
    if existing.is_all_day and not candidate.is_all_day:
        event_dt = candidate.event_datetime
        end_dt = candidate.end_datetime
        is_all_day = False
    elif not existing.is_all_day and candidate.is_all_day:
        event_dt = existing.event_datetime
        end_dt = existing.end_datetime
        is_all_day = False
    else:
        # Both timed or both all-day: keep higher confidence
        if candidate.confidence > existing.confidence:
            event_dt = candidate.event_datetime
            end_dt = candidate.end_datetime
        else:
            event_dt = existing.event_datetime
            end_dt = existing.end_datetime
        is_all_day = existing.is_all_day

    # Merge descriptions
    description = _merge_descriptions(existing, candidate)

    # Merge URLs
    urls = list(set(existing.urls + candidate.urls))

    # Keep highest confidence
    confidence = max(existing.confidence, candidate.confidence)

    return ParsedSchedule(
        event_datetime=event_dt,
        end_datetime=end_dt,
        title=title,
        description=description,
        source_message=existing.source_message,  # keep first as primary
        confidence=confidence,
        is_reminder=existing.is_reminder,
        is_all_day=is_all_day,
        urls=urls,
    )


def _deduplicate(schedules: list[ParsedSchedule]) -> list[ParsedSchedule]:
    """Merge related events on the same day into single combined events."""
    if not schedules:
        return []

    schedules.sort(key=lambda s: s.event_datetime)

    deduped: list[ParsedSchedule] = []
    for sched in schedules:
        merged = False
        for i, existing in enumerate(deduped):
            # Don't merge reminders with non-reminders
            if sched.is_reminder != existing.is_reminder:
                continue

            # Reminders: same day = merge
            if sched.is_reminder and existing.is_reminder:
                if _same_day(sched.event_datetime, existing.event_datetime):
                    deduped[i] = _merge_events(existing, sched)
                    merged = True
                    break
                continue

            if not _same_day(sched.event_datetime, existing.event_datetime):
                continue

            # Same day + related title → merge
            if _titles_related(sched.title, existing.title):
                deduped[i] = _merge_events(existing, sched)
                merged = True
                break

        if not merged:
            deduped.append(sched)

    return deduped


def extract_schedules(messages: list[ChatMessage]) -> list[ParsedSchedule]:
    """Main pipeline: extract all schedule events from chat messages."""
    schedules: list[ParsedSchedule] = []

    date_messages = filter_schedule_messages(messages)

    for msg in date_messages:
        # Try survey detection (but don't skip regular extraction)
        if is_survey_message(msg.text):
            survey = extract_survey_schedule(msg)
            if survey:
                schedules.append(survey)

        # Regular schedule extraction (supports multiple dates in one message)
        all_results = extract_all_datetimes(msg.text, msg.timestamp)
        if not all_results:
            continue

        for event_dt, confidence, block_text in all_results:
            title = _extract_event_title(block_text)

            end_dt = event_dt + timedelta(hours=DEFAULT_EVENT_DURATION_HOURS)

            is_all_day = not has_time_info(block_text) and event_dt.hour == 0 and event_dt.minute == 0

            desc = f'{msg.username}: {block_text[:300]}'

            schedules.append(ParsedSchedule(
                event_datetime=event_dt,
                end_datetime=end_dt,
                title=title,
                description=desc,
                source_message=msg,
                confidence=confidence,
                is_all_day=is_all_day,
            ))

    return _deduplicate(schedules)
