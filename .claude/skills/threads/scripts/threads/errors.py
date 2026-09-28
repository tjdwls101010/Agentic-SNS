"""Public errors: a kind, a message, and the fix that says what to do next."""

_FIXES = {
    2: 'Run this command with --help.',
    3: 'Check that Aside is running, then run `{cli} doctor`.',
    4: 'Log in to Threads in Aside, then run `{cli} doctor`.',
    5: 'Stop requests. Check Threads in Aside, then run `{cli} doctor --unblock`.',
    6: 'Wait briefly before retrying; no automatic retry was made.',
    7: 'Try another target or date window; this is an explicitly empty result.',
    8: 'Run more: later, or rerun the same --out command.',
    9: 'This account cannot read it (deleted, private and not followed, or redirected away); tell the user rather '
       'than retrying.',
}
ROTATED = 'Run `{cli} refresh`, then retry this command.'
CAPTURE = ('Ask the user first: it opens a Threads tab in their browser, where the app itself may record views; then run '
           '`{cli} refresh --capture --post <public post URL>` with a real post URL, and retry this command.')
# The CLI fills in {cli} (its own invocation, as more: writes it) and {command} (the command that failed).
CHANGED = "Threads changed this response's shape; refresh cannot repair it. Tell the user the {command} reader needs an update."


class ThreadsError(Exception):
    def __init__(self, code, message, fix=None, error=None):
        super().__init__(message)
        self.code = code
        self.error = error or {2: "arguments", 3: "aside", 4: "login", 5: "blocked", 6: "transient", 7: "empty", 8: "partial", 9: "unavailable"}.get(code, "failure")
        self.message = message
        self.fix = fix or _FIXES.get(code, 'Check the command with --help.')

    def as_dict(self):
        return {'ok': False, 'error': self.error, 'code': self.code, 'message': self.message, 'fix': self.fix}


def rotated(message, capture=False):
    """A query Threads no longer answers under its registered id or name: refresh can find the new one."""
    return ThreadsError(6, message, CAPTURE if capture else ROTATED, error='operation_rotated')


def changed(message):
    """A response that arrived without what its declaration reads: only a new version of the reader can fix it."""
    return ThreadsError(6, message, CHANGED, error='shape_changed')
