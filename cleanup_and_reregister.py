"""Cleanup existing calendar events and re-register with improved extraction logic.

Usage:
    python cleanup_and_reregister.py --dry-run              # Preview only
    python cleanup_and_reregister.py                         # Delete + re-register
    python cleanup_and_reregister.py --cleanup-only          # Delete only, no re-register
"""

import argparse
import sys
import time
import io
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent))

from calendar_client.auth import get_calendar_service
from calendar_client.gcal_client import create_event, check_duplicate
from line_parser.chat_parser import parse_line_chat
from schedule_extractor.extractor import extract_schedules

CAL_ID = 'af0fea42115464ed5620091edcbcbfe2cf3132b79d37f5e997ed923f12fe2fe8@group.calendar.google.com'
CHAT_FILE = Path(r'C:\Users\sanea\Downloads\[LINE]阪南ミニバス2025メンバー.txt')
MIN_CONFIDENCE = 0.5


def list_all_events(service, calendar_id):
    """Fetch all events from calendar."""
    all_events = []
    page_token = None
    while True:
        result = service.events().list(
            calendarId=calendar_id,
            pageToken=page_token,
            maxResults=250,
            singleEvents=True,
            orderBy='startTime',
        ).execute()
        all_events.extend(result.get('items', []))
        page_token = result.get('nextPageToken')
        if not page_token:
            break
    return all_events


def cleanup_calendar(service, calendar_id, dry_run=True):
    """Delete auto-generated events, keep duty roster events."""
    events = list_all_events(service, calendar_id)
    print(f'\n現在のイベント数: {len(events)}件')

    to_delete = []
    to_keep = []

    for event in events:
        summary = event.get('summary', '')
        desc = event.get('description', '')

        # Preserve duty roster events
        if '当番表より' in desc or '当番' in summary:
            to_keep.append(event)
            continue

        to_delete.append(event)

    print(f'  削除対象: {len(to_delete)}件')
    print(f'  保持 (当番表): {len(to_keep)}件')

    if dry_run:
        print('\n[Dry run] 削除はスキップ')
        return len(to_delete)

    print(f'\n{len(to_delete)}件のイベントを削除中...')
    deleted = 0
    errors = 0
    for event in to_delete:
        try:
            service.events().delete(
                calendarId=calendar_id,
                eventId=event['id'],
            ).execute()
            deleted += 1
            if deleted % 50 == 0:
                print(f'  ...{deleted}/{len(to_delete)}件削除済み')
                time.sleep(1)  # Rate limit
        except Exception as e:
            print(f'  ERROR deleting {event.get("summary", "?")}: {e}')
            errors += 1

    print(f'  削除完了: {deleted}件, エラー: {errors}件')
    return deleted


def reregister_events(service, calendar_id, dry_run=True):
    """Re-extract and register events from LINE chat."""
    if not CHAT_FILE.exists():
        print(f'Error: チャットファイルが見つかりません: {CHAT_FILE}')
        return 0

    print(f'\nLINEチャットを再解析中: {CHAT_FILE.name}')
    messages = parse_line_chat(CHAT_FILE)
    print(f'  {len(messages)}件のメッセージを検出')

    schedules = extract_schedules(messages)
    schedules = [s for s in schedules if s.confidence >= MIN_CONFIDENCE]
    print(f'  {len(schedules)}件のイベントを抽出（改善ロジック適用済み）')

    # Show summary by type
    reminders = [s for s in schedules if s.is_reminder]
    events = [s for s in schedules if not s.is_reminder]
    all_day = [s for s in events if s.is_all_day]
    timed = [s for s in events if not s.is_all_day]
    print(f'    通常イベント: {len(events)}件 (時間指定: {len(timed)}, 終日: {len(all_day)})')
    print(f'    リマインダー: {len(reminders)}件')

    # Show specific date check (2/14)
    print('\n--- 2/14(土) のイベント ---')
    feb14 = [s for s in schedules if s.event_datetime.month == 2 and s.event_datetime.day == 14]
    if not feb14:
        print('  (なし)')
    for s in feb14:
        dt_str = s.event_datetime.strftime('%H:%M') if not s.is_all_day else '終日'
        rem_str = ' [リマインダー]' if s.is_reminder else ''
        print(f'  {dt_str} {s.title}{rem_str}')
        # Show first 100 chars of description
        desc_preview = s.description[:100].replace('\n', ' ')
        print(f'    {desc_preview}')

    # Show 2/9 check (should have survey reminder)
    print('\n--- 2/9(日) のイベント ---')
    feb9 = [s for s in schedules if s.event_datetime.month == 2 and s.event_datetime.day == 9]
    if not feb9:
        print('  (なし)')
    for s in feb9:
        dt_str = s.event_datetime.strftime('%H:%M') if not s.is_all_day else '終日'
        rem_str = ' [リマインダー]' if s.is_reminder else ''
        print(f'  {dt_str} {s.title}{rem_str}')

    if dry_run:
        print(f'\n[Dry run] {len(schedules)}件の登録はスキップ')
        return len(schedules)

    # Register events
    print(f'\n{len(schedules)}件のイベントを登録中...')
    added = 0
    errors = 0

    for sched in schedules:
        try:
            create_event(service, sched, calendar_id)
            added += 1
            if added % 50 == 0:
                print(f'  ...{added}/{len(schedules)}件登録済み')
                time.sleep(1)
        except Exception as e:
            dt_str = sched.event_datetime.strftime('%Y/%m/%d')
            print(f'  ERROR: {sched.title} @ {dt_str} - {e}')
            errors += 1

    print(f'  登録完了: {added}件, エラー: {errors}件')
    return added


def main():
    parser = argparse.ArgumentParser(description='カレンダー整理＆再登録')
    parser.add_argument('--dry-run', action='store_true', help='プレビューのみ')
    parser.add_argument('--cleanup-only', action='store_true', help='削除のみ')
    args = parser.parse_args()

    print('Googleカレンダーに接続中...')
    service = get_calendar_service()

    # Step 1: Cleanup
    cleanup_calendar(service, CAL_ID, dry_run=args.dry_run)

    # Step 2: Re-register (unless cleanup-only)
    if not args.cleanup_only:
        reregister_events(service, CAL_ID, dry_run=args.dry_run)

    print('\n全て完了！')


if __name__ == '__main__':
    main()
