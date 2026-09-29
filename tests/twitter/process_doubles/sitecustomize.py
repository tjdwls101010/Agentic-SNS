"""Loaded by the CLI process when this folder is on PYTHONPATH.

FAKE_NO_SLEEP=1 skips pacing sleeps; reservations, the account window and bucket bookkeeping still run. FAKE_CLOCK_OFFSET=<seconds> runs the process that much later than now, so an expiry is reached without waiting. FAKE_HANDLE_CHARS=<letters> makes secrets.choice return these characters in turn, so a continuation handle and its collisions are predictable.
"""
import os
import secrets
import time

if os.environ.get('FAKE_NO_SLEEP') == '1':
    time.sleep = lambda seconds: None

_offset = float(os.environ.get('FAKE_CLOCK_OFFSET') or 0)
if _offset:
    _time = time.time
    time.time = lambda: _time() + _offset

if _chars := os.environ.get('FAKE_HANDLE_CHARS'):
    _stream = iter(_chars)
    secrets.choice = lambda sequence: next(_stream)
