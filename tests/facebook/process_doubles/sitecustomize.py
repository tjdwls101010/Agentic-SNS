"""Test-only process doubles, active only when the CLI runs with this directory on PYTHONPATH.

FAKE_NO_SLEEP=1 turns the account pacing sleep into a no-op, so a fake Aside reply costs no real 1-2 s gap; tests
of pacing itself run without it. FAKE_FAIL_REPLACE=<name> makes os.replace onto a file of that name fail, the only
way to reach an atomic-write failure from outside the process.
"""
import os
import time

if os.environ.get('FAKE_NO_SLEEP') == '1':
    time.sleep = lambda seconds: None

_failing = os.environ.get('FAKE_FAIL_REPLACE')
if _failing:
    _replace = os.replace

    def _fail_named(source, destination, *args, **kwargs):
        if os.path.basename(os.fspath(destination)) == _failing:
            raise OSError('injected replace failure')
        return _replace(source, destination, *args, **kwargs)

    os.replace = _fail_named
