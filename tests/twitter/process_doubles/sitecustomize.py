"""Loaded by the CLI process when this folder is on PYTHONPATH.

FAKE_NO_SLEEP=1 skips pacing sleeps; reservations, the account window and bucket bookkeeping still run. FAKE_CLOCK_OFFSET=<seconds> runs the process that much later than now, so an expiry is reached without waiting.
"""
import os
import time

if os.environ.get('FAKE_NO_SLEEP') == '1':
    time.sleep = lambda seconds: None

_offset = float(os.environ.get('FAKE_CLOCK_OFFSET') or 0)
if _offset:
    _time = time.time
    time.time = lambda: _time() + _offset
