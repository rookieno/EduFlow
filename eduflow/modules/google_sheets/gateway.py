from re import fullmatch
from secrets import randbelow

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials
from requests.exceptions import RequestException

from eduflow.modules.google_sheets.exceptions import (
    GoogleSheetConfigurationError,
    GoogleSheetRequestError,
)


_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


class GoogleSheetGateWay:
    def __init__(self, *, spreadsheet_id: str, credentials_path: str) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._credentials_path = credentials_path

    def create_tab(self, *, title: str, rows: list[tuple[str, ...]]) -> str:
        """Create a tab from text rows with the first row frozen."""
        spreadsheet_id = self._spreadsheet_id
        if not self._credentials_path or not fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id):
            raise GoogleSheetConfigurationError

        try:
            credentials = Credentials.from_service_account_file(
                self._credentials_path, scopes=[_SHEETS_SCOPE],
            )
        except (OSError, ValueError, GoogleAuthError) as exc:
            raise GoogleSheetConfigurationError from exc

        sheet_id = randbelow(2**31 - 1) + 1
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
            raise GoogleSheetRequestError from exc

        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={sheet_id}"
