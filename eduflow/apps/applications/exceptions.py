from eduflow.apps.courses.choices import IntakeStatus


class IntakeClosed(Exception):
    def __init__(self, status: IntakeStatus) -> None:
        self.status = status
        super().__init__(status.label)


class SubmissionConflict(Exception):
    """The same submission identifier was used for different input."""


class SheetsExportLimitExceeded(Exception):
    """The selected applications exceed the per-export row limit."""
