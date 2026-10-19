"""The date window of one read: which local days it keeps, and whether a newest-first page proves its start passed.

A window keeps the dated posts written on its local days; a post without a date cannot be placed and is left out and
counted (a tombstone is not counted). Only a newest-first surface (a profile's posts and replies tabs, latest search)
can prove it passed --since: a page closes the window when every unit on it is older than --since, pinned units aside,
provided every unit so far came newest first by its newest post — once the order breaks, nothing closes it. A finite
list in no date order covers the window only when read to the end; a ranked or unordered feed (for you, following)
never does.
"""
from datetime import date, datetime


def _local_day(stamp):
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone().date()


class Window:
    """The date-window policy of one read, with the state a continuation carries."""

    def __init__(self, since, until, order, state=None):
        self.since = date.fromisoformat(since) if since else None
        self.until = date.fromisoformat(until) if until else None
        self.order = order
        state = state or {}
        self.last = state.get('last')                  # the newest-post time of the last unit seen, ISO
        self.unordered = bool(state.get('unordered'))
        self.undated = list(state.get('undated') or [])

    @property
    def active(self):
        return self.since is not None or self.until is not None

    def state(self):
        return {'last': self.last, 'unordered': self.unordered, 'undated': self.undated}

    def keep(self, record):
        if not self.active:
            return True
        if record.get('unavailable'):
            return False
        if not record.get('created_at'):
            if record.get('id') not in self.undated:
                self.undated.append(record.get('id'))
            return False
        day = _local_day(record['created_at'])
        return (self.since is None or day >= self.since) and (self.until is None or day <= self.until)

    def closes(self, records):
        """Whether this newest-first page proves the window's start was passed (see the module docstring)."""
        units = {}
        for record in records:
            units.setdefault(record.get('unit') or record.get('id'), []).append(record)
        times = []
        for unit in units.values():
            if any(r.get('is_pinned') for r in unit):
                continue
            stamps = [r.get('created_at') for r in unit if not r.get('unavailable')]
            if not stamps or any(s is None for s in stamps):
                self.unordered = True
                continue
            times.append(max(datetime.fromisoformat(s.replace('Z', '+00:00')) for s in stamps))
        previous = datetime.fromisoformat(self.last) if self.last else None
        if any(a < b for a, b in zip(times, times[1:])) or (previous and times and times[0] > previous):
            self.unordered = True
        if times:
            self.last = times[-1].isoformat()
        return (self.since is not None and bool(times) and not self.unordered
                and max(times).astimezone().date() < self.since)

    def report(self):
        notes = []
        if self.undated:
            notes.append(f'{len(self.undated)} undated post{"s" if len(self.undated) > 1 else ""} left out: no date '
                         'places them in the window')
        if self.order == 'newest_first' and self.unordered and self.since:
            notes.append('this surface did not come newest first here, so reading on cannot prove --since was passed')
        return notes
