"""Time for one invocation: the clock it reads and sleeps on, its deadline, and day boundaries.

Every invocation shares one Deadline made at process start: account resolution, lock waits, pacing and every Aside
call fit inside it, so a command ends within the Bash tool's two minutes with its output written.
"""
import os
import shutil
import time
from datetime import date, datetime, timedelta, timezone

# 성진: 명령 하나는 Bash 도구의 2분 안에 출력·저장까지 끝나야 한다 — 그 여유를 남긴 기본 마감(X에서 이어받음, 다섯 플랫폼 공통)
DEADLINE_SECONDS = 100
KST = timezone(timedelta(hours=9), 'KST')



def _is_fake(binary):
    """Whether the Aside backend is the suite's fake: the fake itself or the one-line launcher that runs it."""
    path = shutil.which(binary) if binary else None
    try:
        with open(path or '', 'rb') as file:
            return b'fake_aside' in file.read(4096)
    except OSError:
        return False

class Clock:
    """Wall and monotonic time and sleep. With the suite's fake Aside (SNS_ASIDE_BIN and SNS_FAKE_SCENARIO) and
    SNS_TEST_NO_WAIT, sleeping moves a virtual offset instead of the process: waits keep their order and their effect on
    the deadline, the suite does not spend minutes. Against the real browser the switch does nothing."""

    def __init__(self):
        # only the suite's fake Aside may move time without waiting: a real aside named in SNS_ASIDE_BIN, with a stray
        # SNS_TEST_NO_WAIT or scenario beside it, still paces for real
        self.virtual = bool(os.environ.get('SNS_TEST_NO_WAIT') and os.environ.get('SNS_FAKE_SCENARIO')
                            and _is_fake(os.environ.get('SNS_ASIDE_BIN')))
        self.offset = 0.0
        self.slept = 0.0  # seconds this invocation waited, virtual or real
        # Virtual time goes on from where earlier commands in this data directory left it, as real time would: a
        # command started right after one cut short by its deadline must not find that one's requests in its future.
        self._mark = os.path.join(os.environ['SNS_DATA_DIR'], '.virtual-clock') \
            if self.virtual and os.environ.get('SNS_DATA_DIR') else None
        if self._mark:
            try:
                with open(self._mark) as file:
                    self.offset = max(0.0, float(file.read()) - time.time())
            except (OSError, ValueError):
                pass

    def time(self):
        return time.time() + self.offset

    def monotonic(self):
        return time.monotonic() + self.offset

    def sleep(self, seconds):
        if seconds <= 0:
            return
        self.slept += seconds
        if self.virtual:
            self.offset += seconds
            if self._mark:
                try:
                    os.makedirs(os.path.dirname(self._mark), exist_ok=True)
                    with open(self._mark, 'w') as file:
                        file.write(repr(self.time()))
                except OSError:
                    pass
        else:
            time.sleep(seconds)


class Deadline:
    """The time left to one invocation (or to one idle cleanup attempt)."""

    def __init__(self, seconds=None, clock=None):
        self.clock = clock or Clock()
        if seconds is None:
            override = os.environ.get('SNS_DEADLINE_SECONDS')  # tests and smoke runs shorten it
            seconds = float(override) if override else DEADLINE_SECONDS
        self.seconds = seconds
        self.end = self.clock.monotonic() + seconds

    def left(self):
        """Seconds until the deadline, never negative."""
        return max(0.0, self.end - self.clock.monotonic())

    def clamp(self, seconds):
        """The part of `seconds` that fits before the deadline."""
        return max(0.0, min(seconds, self.left()))

    @property
    def expired(self):
        return self.left() <= 0


def midnight(day, tz=None):
    """The epoch of a day's first instant in `tz` (None: this computer's zone, daylight saving included)."""
    moment = datetime.combine(date.fromisoformat(day) if isinstance(day, str) else day, datetime.min.time())
    return (moment.replace(tzinfo=tz) if tz else moment.astimezone()).timestamp()


def stamp(value):
    """An ISO-8601 time (with Z or an offset; a naive one is UTC) as an epoch."""
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def iso_utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch is not None else None


def local(epoch, seconds=True):
    """An epoch as local time with its offset, for text the user reads."""
    if not isinstance(epoch, (int, float)):
        return '?'
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec='seconds' if seconds else 'minutes')
