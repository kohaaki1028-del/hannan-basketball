"""Google Calendar API client for creating events and checking duplicates."""

from line_parser.models import ParsedSchedule
from config import TIMEZONE


def create_event(
    service,
    schedule: ParsedSchedule,
    calendar_id: str = 'primary',
) -> dict:
    """Create a Google Calendar event from a ParsedSchedule.

    Args:
        service: Google Calendar API service object.
        schedule: The schedule to create an event for.
        calendar_id: Target calendar ID.

    Returns:
        Created event resource dict.
    """
    if schedule.is_all_day:
        event_body = {
            'summary': schedule.title,
            'description': schedule.description,
            'start': {
                'date': schedule.event_datetime.strftime('%Y-%m-%d'),
                'timeZone': TIMEZONE,
            },
            'end': {
                'date': schedule.event_datetime.strftime('%Y-%m-%d'),
                'timeZone': TIMEZONE,
            },
        }
    else:
        event_body = {
            'summary': schedule.title,
            'description': schedule.description,
            'start': {
                'dateTime': schedule.event_datetime.isoformat(),
                'timeZone': TIMEZONE,
            },
            'end': {
                'dateTime': schedule.end_datetime.isoformat() if schedule.end_datetime else schedule.event_datetime.isoformat(),
                'timeZone': TIMEZONE,
            },
        }

    # Add reminders
    if schedule.is_reminder:
        event_body['reminders'] = {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 1440},  # 1 day before
                {'method': 'popup', 'minutes': 60},     # 1 hour before
            ],
        }
    else:
        event_body['reminders'] = {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 60},
                {'method': 'popup', 'minutes': 10},
            ],
        }

    return service.events().insert(
        calendarId=calendar_id,
        body=event_body,
    ).execute()


def check_duplicate(
    service,
    schedule: ParsedSchedule,
    calendar_id: str = 'primary',
) -> bool:
    """Check if a similar event already exists on the calendar.

    Args:
        service: Google Calendar API service object.
        schedule: The schedule to check for duplicates.
        calendar_id: Target calendar ID.

    Returns:
        True if a duplicate exists, False otherwise.
    """
    dt = schedule.event_datetime
    time_min = dt.strftime('%Y-%m-%dT00:00:00+09:00')
    time_max = dt.strftime('%Y-%m-%dT23:59:59+09:00')

    try:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
        ).execute()

        existing = events_result.get('items', [])
        return any(e.get('summary') == schedule.title for e in existing)
    except Exception:
        return False
