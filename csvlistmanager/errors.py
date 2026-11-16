"""Application exceptions shared by the core service and HTTP boundary."""


class CSVListManagerError(Exception):
    """An expected, actionable application error."""

    status = 400
    code = "invalid_request"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationError(CSVListManagerError):
    code = "validation_error"


class NotFoundError(CSVListManagerError):
    status = 404
    code = "not_found"


class ConflictError(CSVListManagerError):
    status = 409
    code = "revision_conflict"


class ReadOnlyError(CSVListManagerError):
    status = 403
    code = "read_only"
