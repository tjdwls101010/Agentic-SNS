"""The one error type every unit raises, and the scrubbed diagnostic line.

A unit raises the kind of failure it saw, never an exit number: cli.py owns the one table from kind to exit code.
"""
import json
import sys

from sns.redact import scrub

# The failure kinds a unit may raise (cli.py maps each to an exit code; results.py adds the success kinds).
KINDS = ('argument', 'aside', 'login', 'blocked', 'failed', 'empty', 'partial', 'unavailable', 'scope_limit')


class SnsError(Exception):
    """A failure every caller can report: its kind (see KINDS), what happened, and what to do next."""

    def __init__(self, kind, message, fix, reason=None, **details):
        if kind not in KINDS:
            raise ValueError(f'unknown failure kind {kind!r}')
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.fix = fix
        self.reason = reason    # a finer cause a caller may act on: 'time_limit', 'tab_missing', 'account_changed', …
        self.details = details  # what the result should also carry, e.g. a limit's scope and reset

    def __repr__(self):
        return f'SnsError({self.kind!r}, {self.message!r}, reason={self.reason!r})'


def diagnostic(stage, **details):
    """Write caller-chosen request metadata to stderr, scrubbed; never page source, bodies or tokens."""
    print(json.dumps(scrub({'stage': stage, **details}), ensure_ascii=False), file=sys.stderr)
