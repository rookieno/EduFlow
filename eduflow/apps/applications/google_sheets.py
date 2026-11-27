from dataclasses import dataclass
from re import fullmatch
from secrets import randbelow
from uuid import uuid4

from django.conf import settings
from django.utils.timezone import localtime
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials
from requests.exceptions import RequestException

from eduflow.apps.applications.exceptions import SheetsExportFailed, SheetsExportNotConfigured


_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


@dataclass(frozen=True)
class SheetsExportResult:
    count: int
    sheet_url: str


def create_export_tab(rows: list[tuple[str, ...]]) -> SheetsExportResult:
    """Create and populate a new tab in a single Sheets API request."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    credentials_path = settings.GOOGLE_APPLICATION_CREDENTIALS
    if not credentials_path or not fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id):
        raise SheetsExportNotConfigured

    try:
        credentials = Credentials.from_service_account_file(
            credentials_path, scopes=[_SHEETS_SCOPE],
        )
    except (OSError, ValueError, GoogleAuthError) as exc:
        raise SheetsExportNotConfigured from exc

    sheet_id = randbelow(2**31 - 1) + 1
    title = f"신청 목록 {localtime():%Y-%m-%d %H-%M} {uuid4().hex[:8]}"
    payload = {
        "requests": [
            {
                "addSheet": {"properties": {
                    "sheetId": sheet_id,
                    "title": title,
                    "gridProperties": {
                        "rowCount": len(rows),
                        "columnCount": len(rows[0]),
                        "frozenRowCount": 1,
                    },
                }},
            },
            {
                "updateCells": {
                    "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                    "rows": [
                        {"values": [
                            {"userEnteredValue": {"stringValue": value}} for value in row
                        ]}
                        for row in rows
                    ],
                    "fields": "userEnteredValue",
                },
            },
        ],
    }
    endpoint = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate"
    try:
        with AuthorizedSession(credentials, refresh_timeout=10) as session:
            response = session.post(endpoint, json=payload, timeout=(5, 20))
            response.raise_for_status()
    except (GoogleAuthError, RequestException) as exc:
        raise SheetsExportFailed from exc

    return SheetsExportResult(
        count=len(rows) - 1,
        sheet_url=f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={sheet_id}",
    )
