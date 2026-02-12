"""2026年2月スケジュール表 → Googleカレンダー登録スクリプト

当番表画像から目視で読み取ったデータを直接登録する。
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from calendar_client.auth import get_calendar_service
from calendar_client.gcal_client import create_event
from line_parser.models import ParsedSchedule

CALENDAR_ID = 'af0fea42115464ed5620091edcbcbfe2cf3132b79d37f5e997ed923f12fe2fe8@group.calendar.google.com'

# ===== 2026年2月スケジュール表データ =====

# 備考欄のイベント（試合・大会等）
EVENTS = [
    {
        'date': '2026-02-01', 'title': '丸山ファイナルカップ',
        'all_day': True, 'note': '丸山ファイナルカップ',
    },
    {
        'date': '2026-02-04', 'title': '体育館使用不可',
        'all_day': True, 'note': '体育館使用不可 (~2/23)',
    },
    {
        'date': '2026-02-15', 'title': '[公式戦]フレッシュ交歓大会@友渕',
        'all_day': True, 'note': '[公式戦]フレッシュ交歓大会@友渕',
    },
    {
        'date': '2026-02-21', 'title': 'あべのカップ@金塚',
        'all_day': True, 'note': 'あべのカップ@金塚',
    },
    {
        'date': '2026-02-22', 'title': 'フレッシュ交歓大会決勝トーナメント@某佳都',
        'all_day': True, 'note': 'フレッシュ交歓大会決勝トーナメント@某佳都',
    },
    {
        'date': '2026-02-28', 'title': 'U11練習試合@長居(午前のみ)',
        'all_day': True, 'note': 'U11練習試合@長居(午前のみ)',
    },
    {
        'date': '2026-02-28', 'title': '令和7年度 卒団式',
        'time': '13:00', 'end_time': '17:00',
        'note': '令和7年度 卒団式 13:00~17:00',
    },
]

# 当番（練習日）
# 全体 = 17:00~19:30通し当番、試合メンバー = 19:00~合流
DUTY_ROSTER = [
    {
        'date': '2026-02-25', 'time': '17:00', 'end_time': '19:30',
        'duty_all': '森',
        'duty_match': '小原(19~)・和田(19~)',
    },
    {
        'date': '2026-02-26', 'time': '17:00', 'end_time': '19:30',
        'duty_all': '森',
        'duty_match': '原(19~)・大城(19~)',
    },
    {
        'date': '2026-02-27', 'time': '17:00', 'end_time': '19:30',
        'duty_all': '森',
        'duty_match': '兼髙(19~)・岡本(19~)',
        'note': '体育館使用不可 (~12:30)',
    },
]


def main():
    dry_run = '--dry-run' in sys.argv

    print('=== 2026年2月 当番表 → カレンダー登録 ===\n')

    all_items = []

    # 備考欄イベント
    for evt in EVENTS:
        dt = datetime.strptime(evt['date'], '%Y-%m-%d')
        if 'time' in evt:
            h, m = map(int, evt['time'].split(':'))
            dt = dt.replace(hour=h, minute=m)
            eh, em = map(int, evt['end_time'].split(':'))
            end_dt = dt.replace(hour=eh, minute=em)
            is_all_day = False
        else:
            end_dt = dt + timedelta(hours=2)
            is_all_day = True

        all_items.append(ParsedSchedule(
            event_datetime=dt,
            end_datetime=end_dt,
            title=evt['title'],
            description=f'📋 当番表より\n{evt["note"]}',
            confidence=1.0,
            is_all_day=is_all_day,
        ))

    # 当番（練習日）
    for duty in DUTY_ROSTER:
        dt = datetime.strptime(duty['date'], '%Y-%m-%d')
        h, m = map(int, duty['time'].split(':'))
        dt = dt.replace(hour=h, minute=m)
        eh, em = map(int, duty['end_time'].split(':'))
        end_dt = dt.replace(hour=eh, minute=em)

        # 全当番名をタイトルに含める
        all_names = duty['duty_all']
        if duty.get('duty_match'):
            # 「小原(19~)・和田(19~)」から名前だけ抽出
            import re
            match_names = re.findall(r'([^\(・]+)\(', duty['duty_match'])
            if match_names:
                all_names += '・' + '・'.join(match_names)

        desc_parts = [
            '📋 当番表より',
            f"活動時間: {duty['time']}~{duty['end_time']}",
            f"【当番(全体)】{duty['duty_all']}  ※17:00~19:30",
            f"【当番(試合メンバー)】{duty['duty_match']}",
        ]
        if 'note' in duty:
            desc_parts.append(f"⚠️ {duty['note']}")

        all_items.append(ParsedSchedule(
            event_datetime=dt,
            end_datetime=end_dt,
            title=f"練習 当番:{all_names}",
            description='\n'.join(desc_parts),
            confidence=1.0,
            is_all_day=False,
        ))

    # 表示
    for i, item in enumerate(all_items, 1):
        if item.is_all_day:
            dt_str = item.event_datetime.strftime('%Y/%m/%d (終日)')
        else:
            dt_str = f"{item.event_datetime.strftime('%Y/%m/%d %H:%M')}~{item.end_datetime.strftime('%H:%M')}"
        print(f'  [{i}] {dt_str} - {item.title}')

    print(f'\n合計: {len(all_items)} 件')

    if dry_run:
        print('\n[Dry run] カレンダーへの追加はスキップしました。')
        return

    # カレンダー登録
    print('\nGoogleカレンダーに登録中...')
    service = get_calendar_service()
    added = 0
    errors = 0

    for item in all_items:
        try:
            event = create_event(service, item, CALENDAR_ID)
            dt_str = item.event_datetime.strftime('%Y/%m/%d')
            print(f'  ADDED: {item.title} @ {dt_str}')
            added += 1
        except Exception as e:
            print(f'  ERROR: {item.title} - {e}')
            errors += 1

    print(f'\n完了! 追加: {added}件, エラー: {errors}件')


if __name__ == '__main__':
    main()
