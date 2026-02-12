"""Configuration for LINE Chat to Google Calendar tool."""

# Timezone
TIMEZONE = 'Asia/Tokyo'

# Default event duration in hours
DEFAULT_EVENT_DURATION_HOURS = 2

# Google Calendar
CALENDAR_ID = 'primary'
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.json'

# Cancel keywords - messages containing these are skipped
CANCEL_KEYWORDS = ['中止', 'キャンセル', '延期', 'なくなり', '無くなり']

# Survey/questionnaire keywords
SURVEY_KEYWORDS = ['アンケート', '回答', '締切', '締め切り', '〆切', '期限']

# Event type keywords for title extraction
EVENT_TYPE_KEYWORDS = {
    '練習試合': '練習試合',
    '練習': '練習',
    '試合': '試合',
    'ミーティング': 'ミーティング',
    '大会': '大会',
    'トーナメント': 'トーナメント',
    '集合': '集合',
    '自主練': '自主練',
    '合宿': '合宿',
    '遠征': '遠征',
    '飲み会': '飲み会',
    '打ち上げ': '打ち上げ',
}

# Tesseract OCR path (Windows default)
TESSERACT_CMD = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
