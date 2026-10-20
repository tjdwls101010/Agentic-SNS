"""The date window of one read: which local days it keeps, and whether a newest-first page proves its start passed.

A window keeps the dated records written on its local days (--since included, --until the last day included); a record
without a date cannot be placed and is left out and counted. Its bounds are fixed when the window is made — the local
midnights of --since and the day after --until, in the computer's time zone then — and saved with a continuation, so
a later run continues the same span even if the time zone changed. Only a newest-first listing (sort new) can prove it
passed --since: a record older than the start by more than JITTER closes the window, pinned records aside (a profile
pins them to the top whatever their date), provided every record so far came newest first within JITTER; once the
order breaks by more, nothing closes it. Reddit lists new posts in submission order, which can differ from their
creation times by a minute or so (measured on 2026-10-20 in the home feed), hence the margin.
"""
from datetime import date, datetime, time, timedelta, timezone

JITTER = 600  # seconds a newest-first listing may be out of creation order without counting as unordered


def _midnight(day):
    """The epoch of a local day's first instant, by the computer's own time-zone rules (daylight saving included)."""
    return datetime.combine(day, time()).astimezone().timestamp()


def _stamp(value):
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def bounds(since, until):
    """{since, until, tz, start, end} for local days YYYY-MM-DD (either may be None): start and end are epochs, end is
    exclusive (the midnight after --until)."""
    start = _midnight(date.fromisoformat(since)) if since else None
    end = _midnight(date.fromisoformat(until) + timedelta(days=1)) if until else None
    return {'since': since, 'until': until, 'tz': datetime.now().astimezone().tzname(), 'start': start, 'end': end}


def utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch is not None else None


class Window:
    """The date-window policy of one read, with the state a continuation carries."""

    def __init__(self, since, until, state=None):
        state = state or {}
        self.bounds = state.get('bounds') or bounds(since, until)
        self.last = state.get('last')                  # the time of the last dated record seen, epoch
        self.unordered = bool(state.get('unordered'))
        self.undated = list(state.get('undated') or [])

    @property
    def active(self):
        return self.bounds['start'] is not None or self.bounds['end'] is not None

    def state(self):
        return {'bounds': self.bounds, 'last': self.last, 'unordered': self.unordered, 'undated': self.undated}

    def keep(self, record):
        if not self.active:
            return True
        if not record.get('created_at'):
            if record.get('id') not in self.undated:
                self.undated.append(record.get('id'))
            return False
        moment = _stamp(record['created_at'])
        start, end = self.bounds['start'], self.bounds['end']
        return (start is None or moment >= start) and (end is None or moment < end)

    def closes(self, records):
        """Whether this newest-first page proves the window's start was passed (see the module docstring)."""
        times = []
        for record in records:
            if record.get('pinned'):
                continue
            if not record.get('created_at'):
                continue
            times.append(_stamp(record['created_at']))
        lowest = self.last
        for moment in times:
            if lowest is not None and moment > lowest + JITTER:
                self.unordered = True
            lowest = moment if lowest is None else min(lowest, moment)
        self.last = lowest
        start = self.bounds['start']
        return start is not None and bool(times) and not self.unordered and min(times) < start - JITTER

    def describe(self):
        """The window as the result names it: local days, the zone they were judged in, and the UTC bounds."""
        return {'since': self.bounds['since'], 'until': self.bounds['until'], 'tz': self.bounds['tz'],
                'start_utc': utc(self.bounds['start']), 'end_utc': utc(self.bounds['end'])}

    def report(self):
        notes = []
        if self.undated:
            notes.append(f'{len(self.undated)} undated record{"s" if len(self.undated) > 1 else ""} left out: no date '
                         'places them in the window')
        if self.unordered and self.bounds['start'] is not None:
            notes.append('this listing did not come newest first here, so reading on cannot prove --since was passed')
        return notes
