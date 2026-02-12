"""OCR parser for duty roster images (当番表) using Tesseract."""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from line_parser.models import ParsedSchedule
from config import TESSERACT_CMD

try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

# Date patterns in OCR text
_DATE_PATTERN_SLASH = re.compile(r'(\d{1,2})/(\d{1,2})')
_DATE_PATTERN_KANJI = re.compile(r'(\d{1,2})月(\d{1,2})日')

# Row pattern: date followed by name(s)
# e.g. "2/15 田中 佐藤" or "3月1日 鈴木"
_ROW_PATTERN = re.compile(
    r'(\d{1,2}[/月]\d{1,2}日?)\s+(.+)'
)


def check_tesseract() -> bool:
    """Check if Tesseract OCR is available."""
    if not HAS_OCR:
        return False
    try:
        import shutil
        if shutil.which('tesseract'):
            return True
        # Try Windows default path
        path = Path(TESSERACT_CMD)
        if path.exists():
            pytesseract.pytesseract.tesseract_cmd = str(path)
            return True
    except Exception:
        pass
    return False


def ocr_image(image_path: str | Path) -> str:
    """Run OCR on an image and return extracted text."""
    if not HAS_OCR:
        raise RuntimeError(
            'pytesseract/Pillow not installed. Run: pip install pytesseract Pillow'
        )

    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f'Image not found: {image_path}')

    img = Image.open(image_path)
    # Use Japanese + English language data
    text = pytesseract.image_to_string(img, lang='jpn+eng')
    return text


def _resolve_year(month: int, day: int, reference_year: int) -> int:
    """Resolve year for MM/DD format."""
    try:
        candidate = datetime(reference_year, month, day)
        return reference_year
    except ValueError:
        return reference_year


def parse_duty_roster(
    image_path: str | Path,
    reference_date: Optional[datetime] = None,
) -> list[ParsedSchedule]:
    """Parse a duty roster image and extract schedule events.

    Args:
        image_path: Path to the roster image file.
        reference_date: Reference date for year resolution. Defaults to now.

    Returns:
        List of ParsedSchedule objects for each duty entry.
    """
    if reference_date is None:
        reference_date = datetime.now()

    text = ocr_image(image_path)
    schedules: list[ParsedSchedule] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Try to find date + names pattern
        m = _ROW_PATTERN.match(line)
        if not m:
            continue

        date_str = m.group(1)
        names_str = m.group(2).strip()

        # Parse date
        event_dt = None

        dm = _DATE_PATTERN_KANJI.search(date_str)
        if dm:
            month, day = int(dm.group(1)), int(dm.group(2))
            year = _resolve_year(month, day, reference_date.year)
            try:
                event_dt = datetime(year, month, day)
            except ValueError:
                continue

        if event_dt is None:
            dm = _DATE_PATTERN_SLASH.search(date_str)
            if dm:
                month, day = int(dm.group(1)), int(dm.group(2))
                year = _resolve_year(month, day, reference_date.year)
                try:
                    event_dt = datetime(year, month, day)
                except ValueError:
                    continue

        if event_dt is None:
            continue

        # Clean up names
        names = re.split(r'[,、\s]+', names_str)
        names = [n.strip() for n in names if n.strip()]
        names_display = '・'.join(names)

        schedules.append(ParsedSchedule(
            event_datetime=event_dt,
            title=f'当番: {names_display}',
            description=f'当番表から自動抽出\n担当: {names_display}\n画像: {image_path}',
            confidence=0.70,
            is_all_day=True,
        ))

    return schedules


def process_images(
    images_dir: str | Path,
    reference_date: Optional[datetime] = None,
) -> list[ParsedSchedule]:
    """Process all images in a directory for duty roster data.

    Args:
        images_dir: Directory containing roster images.
        reference_date: Reference date for year resolution.

    Returns:
        Combined list of ParsedSchedule objects from all images.
    """
    images_dir = Path(images_dir)
    if not images_dir.is_dir():
        return []

    all_schedules: list[ParsedSchedule] = []
    image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.gif'}

    for img_path in sorted(images_dir.iterdir()):
        if img_path.suffix.lower() in image_extensions:
            try:
                schedules = parse_duty_roster(img_path, reference_date)
                all_schedules.extend(schedules)
            except Exception as e:
                print(f'  Warning: Failed to process {img_path.name}: {e}')

    return all_schedules
