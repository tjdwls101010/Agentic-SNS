"""The receipt every command prints: its failures and their exit codes, the document's status, and how it is cut to fit."""


class Failure(Exception):
    """A target, or the whole call, failed for the reason `code` names; `fix` says what to do instead."""

    code = "upstream"

    def __init__(self, message, fix=None, code=None):
        super().__init__(message)
        self.fix = fix
        if code:
            self.code = code


class Invalid(Failure):
    """An argument the caller has to change, refused before anything is paid for."""

    code = "invalid"


class LocalIO(Failure):
    """A local file could not be written or read: a fault in this machine's path, not in the request."""

    code = "local_io"
