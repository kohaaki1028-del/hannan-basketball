"""Extract events and launch review web app for owner approval.

Usage:
    python review_events.py                    # Extract + open review page
    python review_events.py --register         # Register approved events to calendar
    python review_events.py --incremental      # Incremental: compare new data vs existing calendar
"""

import argparse
import json
import sys
import io
import time
import webbrowser
import http.server
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding (only if not already wrapped)
if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent))

from line_parser.chat_parser import parse_line_chat
from schedule_extractor.extractor import extract_schedules

CAL_ID = 'af0fea42115464ed5620091edcbcbfe2cf3132b79d37f5e997ed923f12fe2fe8@group.calendar.google.com'
CHAT_FILE = Path(r'C:\Users\sanea\Downloads\[LINE]阪南ミニバス2025メンバー.txt')
REVIEW_DIR = Path(__file__).parent / 'review'
PENDING_FILE = REVIEW_DIR / 'pending_events.json'
APPROVED_FILE = REVIEW_DIR / 'approved_events.json'
EDIT_HISTORY_FILE = REVIEW_DIR / 'edit_history.json'
MIN_CONFIDENCE = 0.5


def _schedule_to_item(s, idx, day_event_count):
    """Convert a ParsedSchedule to a JSON-serializable review item."""
    date_key = s.event_datetime.strftime('%Y-%m-%d')
    return {
        'id': f'{date_key}_{idx}',
        'date': date_key,
        'title': s.title,
        'time_start': s.event_datetime.strftime('%H:%M') if not s.is_all_day else None,
        'time_end': s.end_datetime.strftime('%H:%M') if s.end_datetime and not s.is_all_day else None,
        'is_all_day': s.is_all_day,
        'is_reminder': s.is_reminder,
        'description': s.description,
        'confidence': s.confidence,
        'day_event_count': day_event_count,
        'needs_review': day_event_count > 1,
        'status': 'auto_approved' if day_event_count == 1 else 'pending',
    }


def extract_to_json():
    """Extract events from LINE chat and save as JSON for review."""
    print(f'LINEチャットを解析中: {CHAT_FILE.name}')
    messages = parse_line_chat(CHAT_FILE)
    print(f'  {len(messages)}件のメッセージを検出')

    schedules = extract_schedules(messages)
    schedules = [s for s in schedules if s.confidence >= MIN_CONFIDENCE]
    print(f'  {len(schedules)}件のイベントを抽出')

    # Group by date
    events_by_date = {}
    for s in schedules:
        date_key = s.event_datetime.strftime('%Y-%m-%d')
        if date_key not in events_by_date:
            events_by_date[date_key] = []
        events_by_date[date_key].append(s)

    # Convert to review items
    review_items = []
    auto_count = 0
    review_count = 0
    for date_key in sorted(events_by_date.keys()):
        day_events = events_by_date[date_key]
        day_count = len(day_events)
        for s in day_events:
            item = _schedule_to_item(s, len(review_items), day_count)
            review_items.append(item)
            if item['status'] == 'auto_approved':
                auto_count += 1
            else:
                review_count += 1

    # Save
    REVIEW_DIR.mkdir(exist_ok=True)
    with open(PENDING_FILE, 'w', encoding='utf-8') as f:
        json.dump(review_items, f, ensure_ascii=False, indent=2)

    multi_day_count = sum(1 for d in events_by_date.values() if len(d) > 1)
    print(f'  自動承認: {auto_count}件 (1件/日のもの)')
    print(f'  要確認: {review_count}件 ({multi_day_count}日分、同日に複数イベント)')
    print(f'  JSON保存: {PENDING_FILE}')
    return review_items


def get_existing_calendar_events():
    """Fetch existing events from Google Calendar for incremental comparison."""
    from calendar_client.auth import get_calendar_service
    from cleanup_and_reregister import list_all_events

    service = get_calendar_service()
    existing = list_all_events(service, CAL_ID)

    # Group by date
    by_date = {}
    for event in existing:
        start = event.get('start', {})
        date_str = start.get('date') or (start.get('dateTime', '')[:10])
        if date_str:
            if date_str not in by_date:
                by_date[date_str] = []
            by_date[date_str].append({
                'id': event.get('id'),
                'title': event.get('summary', ''),
                'description': event.get('description', ''),
            })
    return by_date


def extract_incremental():
    """Incremental extraction: compare new LINE data against existing calendar.

    - Days with 1 new event and no existing event → auto_approved
    - Days with 1 new event and already in calendar → skip (already registered)
    - Days with 2+ new events → pending (needs review)
    - Days that were 1 event but now have 2+ → pending (needs review)
    """
    print(f'LINEチャットを解析中 (増分モード): {CHAT_FILE.name}')
    messages = parse_line_chat(CHAT_FILE)
    print(f'  {len(messages)}件のメッセージを検出')

    schedules = extract_schedules(messages)
    schedules = [s for s in schedules if s.confidence >= MIN_CONFIDENCE]
    print(f'  {len(schedules)}件のイベントを抽出')

    # Get existing calendar events
    print('  既存カレンダーイベントを取得中...')
    existing_by_date = get_existing_calendar_events()
    print(f'  既存イベント: {sum(len(v) for v in existing_by_date.values())}件')

    # Group new events by date
    new_by_date = {}
    for s in schedules:
        date_key = s.event_datetime.strftime('%Y-%m-%d')
        if date_key not in new_by_date:
            new_by_date[date_key] = []
        new_by_date[date_key].append(s)

    # Build review items
    review_items = []
    auto_count = 0
    review_count = 0
    skip_count = 0

    for date_key in sorted(new_by_date.keys()):
        new_events = new_by_date[date_key]
        existing_events = existing_by_date.get(date_key, [])
        total_count = len(new_events) + len(existing_events)

        if len(new_events) == 1 and len(existing_events) == 0:
            # Single new event, no existing → auto approve
            item = _schedule_to_item(new_events[0], len(review_items), 1)
            item['status'] = 'auto_approved'
            review_items.append(item)
            auto_count += 1

        elif len(new_events) == 1 and len(existing_events) >= 1:
            # Check if new event already exists in calendar
            new_title = new_events[0].title
            already_exists = any(
                new_title.lower() in ex['title'].lower() or ex['title'].lower() in new_title.lower()
                for ex in existing_events
            )
            if already_exists:
                skip_count += 1
                continue  # Already in calendar, skip

            # New event + existing events → this day now has multiple → needs review
            for s in new_events:
                item = _schedule_to_item(s, len(review_items), total_count)
                item['status'] = 'pending'
                item['needs_review'] = True
                item['incremental_note'] = f'既存{len(existing_events)}件 + 新規1件 = 要確認'
                review_items.append(item)
                review_count += 1

        else:
            # Multiple new events → needs review
            for s in new_events:
                item = _schedule_to_item(s, len(review_items), total_count)
                item['status'] = 'pending'
                item['needs_review'] = True
                review_items.append(item)
                review_count += 1

    # Save
    REVIEW_DIR.mkdir(exist_ok=True)
    with open(PENDING_FILE, 'w', encoding='utf-8') as f:
        json.dump(review_items, f, ensure_ascii=False, indent=2)

    print(f'  自動承認: {auto_count}件')
    print(f'  要確認: {review_count}件')
    print(f'  スキップ (既存): {skip_count}件')
    print(f'  JSON保存: {PENDING_FILE}')
    return review_items


def register_approved():
    """Register approved events to Google Calendar."""
    if not APPROVED_FILE.exists():
        print(f'承認ファイルが見つかりません: {APPROVED_FILE}')
        print('先にreview_events.pyを実行してブラウザで確認・承認してください。')
        return

    with open(APPROVED_FILE, 'r', encoding='utf-8') as f:
        approved = json.load(f)

    if not approved:
        print('承認されたイベントがありません。')
        return

    # Merge edit_history.json if downloaded alongside approved_events.json
    _merge_edit_history()

    print(f'{len(approved)}件の承認済みイベントを登録します...')

    from calendar_client.auth import get_calendar_service
    from calendar_client.gcal_client import create_event
    from line_parser.models import ParsedSchedule

    service = get_calendar_service()

    # First, delete existing auto-generated events
    print('既存の自動生成イベントを削除中...')
    from cleanup_and_reregister import list_all_events
    existing = list_all_events(service, CAL_ID)
    deleted = 0
    for event in existing:
        desc = event.get('description', '')
        summary = event.get('summary', '')
        if '当番表より' in desc or '当番' in summary:
            continue
        try:
            service.events().delete(calendarId=CAL_ID, eventId=event['id']).execute()
            deleted += 1
            if deleted % 50 == 0:
                print(f'  ...{deleted}件削除済み')
                time.sleep(1)
        except Exception as e:
            pass
    print(f'  {deleted}件削除完了')

    # Register approved events
    added = 0
    errors = 0
    for item in approved:
        try:
            if item['is_all_day']:
                dt = datetime.strptime(item['date'], '%Y-%m-%d')
                end_dt = None
            else:
                time_str = item.get('time_start', '00:00')
                dt = datetime.strptime(f"{item['date']} {time_str}", '%Y-%m-%d %H:%M')
                if item.get('time_end'):
                    end_dt = datetime.strptime(f"{item['date']} {item['time_end']}", '%Y-%m-%d %H:%M')
                else:
                    end_dt = dt

            sched = ParsedSchedule(
                event_datetime=dt,
                end_datetime=end_dt,
                title=item['title'],
                description=item.get('description', ''),
                is_reminder=item.get('is_reminder', False),
                is_all_day=item.get('is_all_day', False),
                urls=item.get('urls', []),
            )
            create_event(service, sched, CAL_ID)
            added += 1
            if added % 50 == 0:
                print(f'  ...{added}件登録済み')
                time.sleep(1)
        except Exception as e:
            print(f'  ERROR: {item["title"]} @ {item["date"]} - {e}')
            errors += 1

    print(f'\n登録完了! 追加: {added}件, エラー: {errors}件')


def _merge_edit_history():
    """Merge newly downloaded edit_history.json with existing one."""
    if not EDIT_HISTORY_FILE.exists():
        return

    try:
        with open(EDIT_HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
        if history:
            print(f'  編集履歴: {len(history)}件の修正記録を保存済み')
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description='イベント確認・承認ツール')
    parser.add_argument('--register', action='store_true', help='承認済みイベントをカレンダーに登録')
    parser.add_argument('--incremental', action='store_true', help='増分モード: 既存カレンダーと比較')
    args = parser.parse_args()

    if args.register:
        register_approved()
        return

    # Extract events
    if args.incremental:
        review_items = extract_incremental()
    else:
        review_items = extract_to_json()

    # Start local server and open browser
    print(f'\nブラウザで確認ページを開きます...')
    print(f'http://localhost:8090/review.html')
    print(f'(Ctrl+Cで終了)')

    # Serve from review directory
    import functools
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(REVIEW_DIR))
    server = http.server.HTTPServer(('localhost', 8090), handler)

    # Open browser
    webbrowser.open('http://localhost:8090/review.html')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nサーバー停止')
        server.server_close()


if __name__ == '__main__':
    main()
