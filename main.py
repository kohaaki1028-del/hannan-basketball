"""LINE Chat to Google Calendar - メインCLIスクリプト

Usage:
    python main.py chat_export.txt                          # フル実行
    python main.py chat_export.txt --dry-run                # カレンダー追加なし
    python main.py chat_export.txt --images-dir ./images    # 当番表画像も処理
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from line_parser.chat_parser import parse_line_chat
from line_parser.models import ParsedSchedule
from schedule_extractor.extractor import extract_schedules


def _print_schedules(schedules: list[ParsedSchedule], min_confidence: float) -> None:
    """Display extracted events."""
    print('\n--- 抽出されたイベント ---')
    for i, sched in enumerate(schedules, 1):
        # Format datetime
        if sched.is_all_day:
            dt_str = sched.event_datetime.strftime('%Y/%m/%d (終日)')
        else:
            dt_str = sched.event_datetime.strftime('%Y/%m/%d %H:%M')

        # Type indicator
        type_str = '[リマインダー]' if sched.is_reminder else '[イベント]'

        # Confidence indicator
        conf_str = f'{sched.confidence:.0%}'

        print(f'  [{i}] {type_str} {dt_str} - {sched.title}')
        print(f'      信頼度: {conf_str}', end='')

        if sched.confidence < min_confidence:
            print(f'  (スキップ: 最低信頼度 {min_confidence:.0%} 未満)')
        else:
            print()

        # Show merged description summary or single source
        if '━━━' in sched.description:
            # Merged event: count sections
            sections = sched.description.count('━━━') // 2
            print(f'      統合メッセージ: {sections}件')
        elif sched.source_message:
            src = sched.source_message
            print(f'      送信者: {src.username}: {src.text[:60]}')

        if sched.urls:
            print(f'      URL: {sched.urls[0]}')

        print()


def main():
    parser = argparse.ArgumentParser(
        description='LINEチャット履歴からスケジュールを抽出してGoogleカレンダーに追加',
    )
    parser.add_argument(
        'chat_file',
        help='LINEチャットエクスポート .txt ファイルパス',
    )
    parser.add_argument(
        '--images-dir',
        help='当番表画像のフォルダパス',
        default=None,
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='カレンダーに追加せず抽出結果のみ表示',
    )
    parser.add_argument(
        '--calendar-id',
        default='primary',
        help='Google Calendar ID (デフォルト: primary)',
    )
    parser.add_argument(
        '--min-confidence',
        type=float,
        default=0.5,
        help='最低信頼度スコア 0.0-1.0 (デフォルト: 0.5)',
    )
    parser.add_argument(
        '--no-dedup',
        action='store_true',
        help='Googleカレンダーでの重複チェックをスキップ',
    )

    args = parser.parse_args()

    # Validate chat file
    chat_path = Path(args.chat_file)
    if not chat_path.exists():
        print(f'Error: ファイルが見つかりません: {args.chat_file}')
        sys.exit(1)

    # Step 1: Parse LINE chat
    print(f'LINEチャットファイルを読み込み中: {args.chat_file}')
    messages = parse_line_chat(chat_path)
    print(f'  {len(messages)} 件のメッセージを検出')

    # Step 2: Extract schedules from text
    print('スケジュールを抽出中...')
    schedules = extract_schedules(messages)
    print(f'  テキストから {len(schedules)} 件のイベントを抽出')

    # Step 3: Process images if directory provided
    if args.images_dir:
        images_path = Path(args.images_dir)
        if images_path.is_dir():
            from image_reader.ocr_parser import check_tesseract, process_images

            if not check_tesseract():
                print('  Warning: Tesseract OCRが見つかりません。画像処理をスキップします。')
                print('  Tesseractをインストールしてください: https://github.com/tesseract-ocr/tesseract')
            else:
                print(f'当番表画像を処理中: {args.images_dir}')
                image_schedules = process_images(images_path)
                schedules.extend(image_schedules)
                print(f'  画像から {len(image_schedules)} 件のイベントを抽出')
        else:
            print(f'  Warning: 画像フォルダが見つかりません: {args.images_dir}')

    if not schedules:
        print('\nスケジュールイベントが見つかりませんでした。')
        return

    # Step 4: Display results
    _print_schedules(schedules, args.min_confidence)

    # Filter by confidence
    schedules = [s for s in schedules if s.confidence >= args.min_confidence]

    if not schedules:
        print('最低信頼度を超えるイベントがありません。')
        return

    if args.dry_run:
        print(f'[Dry run] {len(schedules)} 件のイベントをGoogleカレンダーに追加予定。')
        return

    # Step 5: Confirm with user
    response = input(f'\n{len(schedules)} 件のイベントをGoogleカレンダーに追加しますか？ (y/N): ')
    if response.lower() not in ('y', 'yes', 'はい'):
        print('キャンセルしました。')
        return

    # Step 6: Add to Google Calendar
    print('\nGoogleカレンダーに接続中...')
    from calendar_client.auth import get_calendar_service
    from calendar_client.gcal_client import create_event, check_duplicate

    try:
        service = get_calendar_service()
    except FileNotFoundError as e:
        print(f'Error: {e}')
        sys.exit(1)

    added = 0
    skipped = 0
    errors = 0

    for sched in schedules:
        try:
            if not args.no_dedup and check_duplicate(service, sched, args.calendar_id):
                dt_str = sched.event_datetime.strftime('%Y/%m/%d %H:%M')
                print(f'  SKIP (重複): {sched.title} @ {dt_str}')
                skipped += 1
                continue

            event = create_event(service, sched, args.calendar_id)
            dt_str = sched.event_datetime.strftime('%Y/%m/%d %H:%M')
            print(f'  ADDED: {sched.title} @ {dt_str}')
            link = event.get('htmlLink', '')
            if link:
                print(f'         URL: {link}')
            added += 1

        except Exception as e:
            print(f'  ERROR: {sched.title} - {e}')
            errors += 1

    print(f'\n完了! 追加: {added}件, スキップ: {skipped}件, エラー: {errors}件')


if __name__ == '__main__':
    main()
