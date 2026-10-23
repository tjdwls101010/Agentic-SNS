"""The date window of one read: which days it keeps, and whether a newest-first page proves its start passed.

A window keeps the dated records written on its days (--since included, --until the last day included) in the
platform's zone (this computer's local zone, or KST for Naver). A record without a date cannot be placed and is left out
and counted; an unavailable one is never kept. The bounds are fixed when the window is made and saved with a
continuation, so a later run continues the same span even if the time zone changed.

Only a newest-first surface can prove it passed --since: a page closes the window once a unit (a record, or the records
the platform groups into one entry, judged by its newest) is older than the start by more than the platform's jitter,
pinned records aside, provided every unit so far came newest first within that jitter; once the order breaks by more,
nothing closes it. Which surfaces are newest first is the caller's declaration (order).
"""
from dataclasses import dataclass

from sns.clock import iso_utc, midnight, stamp
from datetime import date, datetime, timedelta

ORDERS = ('newest_first', 'server', 'finite', 'ranked')


@dataclass(frozen=True)
class WindowPolicy:
    """A platform's window rules: tz (None: this computer's zone), jitter (seconds a newest-first listing may be out
    of order, e.g. Reddit's submission order), pinned_key and unit_key (record fields naming a pinned record and the
    entry a record belongs to)."""
    tz: object = None
    jitter: float = 0
    pinned_key: str = 'pinned'
    unit_key: str | None = None


def bounds(since, until, tz=None):
    """{since, until, tz, start, end}: start and end are epochs, end exclusive (the midnight after --until)."""
    start = midnight(since, tz) if since else None
    end = midnight(date.fromisoformat(until) + timedelta(days=1), tz) if until else None
    zone = tz.tzname(None) if tz is not None else datetime.now().astimezone().tzname()
    return {'since': since, 'until': until, 'tz': zone, 'start': start, 'end': end}


class Window:
    """The date-window policy of one read, with the state a continuation carries."""

    def __init__(self, since, until, *, order, policy=None, state=None):
        if order not in ORDERS:
            raise ValueError(order)
        self.order = order
        self.policy = policy or WindowPolicy()
        state = state or {}
        self.bounds = state.get('bounds') or bounds(since, until, self.policy.tz)
        self.last = state.get('last')                  # the time of the oldest unit seen so far, epoch
        self.unordered = bool(state.get('unordered'))
        self.undated = list(state.get('undated') or [])

    @property
    def active(self):
        return self.bounds['start'] is not None or self.bounds['end'] is not None

    @property
    def since(self):
        return self.bounds['since']

    @property
    def until(self):
        return self.bounds['until']

    def state(self):
        return {'bounds': self.bounds, 'last': self.last, 'unordered': self.unordered, 'undated': self.undated}

    def keep(self, record):
        if not self.active:
            return True
        if record.get('unavailable'):
            return False
        if not record.get('created_at'):
            if record.get('id') not in self.undated:
                self.undated.append(record.get('id'))
            return False
        moment = stamp(record['created_at'])
        start, end = self.bounds['start'], self.bounds['end']
        return (start is None or moment >= start) and (end is None or moment < end)

    def closes(self, records):
        """Whether this newest-first page proves the window's start was passed (see the module docstring)."""
        units = {}
        for index, record in enumerate(records):
            if record.get(self.policy.pinned_key) or record.get('unavailable'):
                continue
            key = record.get(self.policy.unit_key) if self.policy.unit_key else None
            if not record.get('created_at'):
                if key is not None:
                    self.unordered = True  # a grouped unit with an undated record has no knowable newest time
                continue
            units.setdefault(key if key is not None else ('#', index), []).append(stamp(record['created_at']))
        times = [max(moments) for moments in units.values()]
        lowest = self.last
        for moment in times:
            if lowest is not None and moment > lowest + self.policy.jitter:
                self.unordered = True
            lowest = moment if lowest is None else min(lowest, moment)
        self.last = lowest
        start = self.bounds['start']
        return start is not None and bool(times) and not self.unordered and min(times) < start - self.policy.jitter

    def describe(self):
        """The window as a result names it: its days, the zone they were judged in, the UTC bounds and the order."""
        return {'since': self.bounds['since'], 'until': self.bounds['until'], 'tz': self.bounds['tz'],
                'start_utc': iso_utc(self.bounds['start']), 'end_utc': iso_utc(self.bounds['end']), 'order': self.order}

    def report(self):
        notes = []
        if self.undated:
            many = len(self.undated) > 1
            notes.append(f'{len(self.undated)} undated record{"s" if many else ""} left out: no date places '
                         f'{"them" if many else "it"} in the window')
        if self.order == 'newest_first' and self.unordered and self.bounds['start'] is not None:
            notes.append('this surface did not come newest first here, so reading on cannot prove --since was passed')
        return notes
