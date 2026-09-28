"""Date windows: kept locally by each post's writing time, and when a newest-first surface proves its start was passed.

Threads has no server-side date filter for these surfaces. A window is complete when the read reached the end of the
surface, or when a newest-first (chronological) surface returned a page wholly older than the window's start with every
page so far in order; anything else leaves part of the window unread.
"""
from datetime import datetime, timezone

MESSAGE = 'Dates must be ISO dates or date-times; dates without offsets use UTC.'


def moment(value):
    """An ISO date or date-time as a Unix timestamp (UTC when no offset is given); None for None."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def stamp(value):
    try:
        return moment(value)
    except (ValueError, AttributeError):
        return None


class Window:
    def __init__(self, since=None, until=None, chronological=False):
        self.since, self.until = since, until
        self.lower, self.upper = moment(since), moment(until)
        self.chronological = chronological

    @property
    def active(self):
        return self.lower is not None or self.upper is not None

    def keep(self, page, state):
        """The page's records written inside the window, and whether the window's start is now proven passed."""
        if not self.active:
            return page.records, False
        records = [p for p in page.records if (t := stamp(p.get('created_at'))) is not None
                   and (self.lower is None or t >= self.lower) and (self.upper is None or t < self.upper)]
        activity, unknown = [], False
        for group in page.groups:
            if any(p.get('is_pinned') for p in group):
                continue
            times = [stamp(p.get('created_at')) for p in group]
            if not times or any(t is None for t in times):
                unknown = True
            else:
                activity.append(max(times))
        previous = state.get('last_activity')
        ordered = all(a >= b for a, b in zip(activity, activity[1:]))
        if previous is not None and activity and activity[0] > previous:
            ordered = False
        state['unordered'] = state.get('unordered', False) or not ordered or unknown
        if activity:
            state['last_activity'] = activity[-1]
        reached = bool(self.chronological and self.lower is not None and activity and max(activity) < self.lower
                       and not state['unordered'])
        return records, reached

    def report(self, stop):
        return {'since': self.since, 'until': self.until, 'complete': stop in ('exhausted', 'window_reached')}
