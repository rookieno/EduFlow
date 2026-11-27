class GoogleSheetConfigurationError(Exception):
    """The spreadsheet or service account configuration is missing or invalid."""


class GoogleSheetRequestError(Exception):
    """Google did not confirm the Sheets API request."""
