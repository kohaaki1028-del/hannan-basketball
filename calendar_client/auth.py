"""Google Calendar API authentication via OAuth2 desktop flow."""

import os
from pathlib import Path

from config import CREDENTIALS_FILE, TOKEN_FILE

SCOPES = ['https://www.googleapis.com/auth/calendar']


def get_calendar_service():
    """Authenticate and return a Google Calendar API service object.

    On first run, opens a browser for OAuth2 consent.
    Subsequent runs use the cached token.json.

    Returns:
        Google Calendar API service object.

    Raises:
        FileNotFoundError: If credentials.json is not found.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f'{CREDENTIALS_FILE} が見つかりません。\n'
                    'Google Cloud Console からOAuth2クライアントIDのJSONをダウンロードし、\n'
                    f'プロジェクトルートに {CREDENTIALS_FILE} として保存してください。'
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)
