"""Test-only process doubles, active only when the CLI runs with this directory on PYTHONPATH.

FAKE_NO_SLEEP=1 turns the account pacing sleep into a no-op, so a fake Aside reply costs no real 1-1.5 s gap. Pacing
and the shared request window are still recorded, so every budget and window number stays what it would be.
FAKE_CLOCK_OFFSET=<seconds> runs the process that much later than now, so an expiry is reached without waiting.
"""
import os
import time

if os.environ.get('FAKE_NO_SLEEP') == '1':
    time.sleep = lambda seconds: None

_offset = float(os.environ.get('FAKE_CLOCK_OFFSET') or 0)
if _offset:
    _time = time.time
    time.time = lambda: _time() + _offset
