"""Test-only process doubles, active only when the CLI runs with this directory on PYTHONPATH.

FAKE_NO_SLEEP=1 turns the account pacing sleep into a no-op, so a fake Aside reply costs no real 1-2 s gap; tests
of pacing itself run without it. FAKE_FAIL_REPLACE=<name> makes os.replace onto a file of that name fail, the only
way to reach an atomic-write failure from outside the process. FAKE_FAIL_FSYNC=<name>:<n> fails every fsync of
that file after the first n, a disk that fills up part-way through.
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

_fsync_rule = os.environ.get('FAKE_FAIL_FSYNC')
if _fsync_rule:
    # "<name>:<n>": the first n fsyncs of files with that name succeed, later ones fail — a disk filling up.
    _fsync_name, _fsync_allowed = _fsync_rule.rsplit(':', 1)
    _fsync = os.fsync
    _calls = {'n': 0}

    def _fd_name(fd):
        try:
            return os.path.basename(os.readlink(f'/proc/self/fd/{fd}'))
        except OSError:
            import fcntl
            raw = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
            return os.path.basename(raw.split(b'\0', 1)[0].decode())

    def _fail_later(fd):
        if _fd_name(fd) == _fsync_name:
            _calls['n'] += 1
            if _calls['n'] > int(_fsync_allowed):
                raise OSError('injected fsync failure')
        return _fsync(fd)

    os.fsync = _fail_later
