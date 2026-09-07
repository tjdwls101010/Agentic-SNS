"""Where a listing stops, and why — the one decision Naver's own numbers cannot make.

Three stops look identical from inside a single page: the results ended, the server hit
its 1,000-item ceiling, and the server ignored the page parameter. Telling them apart is
what makes "how many are there" answerable at all, so each has its own stop_reason and
none of them is inferred from a count the server reported.
"""
import copy
from datetime import date, datetime, timedelta, timezone

from ._errors import NaverBlogError

KST = timezone(timedelta(hours=9))


def kst_day(value, *, end):
    """A date window is a KST day: --since starts it, --until includes the whole day named."""
    if value is None:
        return None
    try:
        day = date.fromisoformat(str(value))
    except ValueError:
        raise NaverBlogError(2, 'Dates are KST calendar days, written YYYY-MM-DD.',
                             'Pass --since 2026-09-01 --until 2026-09-07.') from None
    moment = datetime.combine(day, datetime.max.time() if end else datetime.min.time(), tzinfo=KST)
    return moment.timestamp()


def moment_of(record):
    stamp = record.get('created_at')
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except (ValueError, TypeError):
        return None


class Progress:
    """Mutable walk state; a continuation handle is exactly this, serialized."""

    def __init__(self, state=None):
        state = copy.deepcopy(state or {})
        self.page = state.get('page', 1)
        self.position = state.get('position', 0)
        self.pending = state.get('pending', [])
        self.seen = set(state.get('seen', []))
        self.done = state.get('done', False)
        self.terminal = state.get('terminal', 'exhausted')
        self.reported_total = state.get('reported_total')
        self.reported_is_unreliable = state.get('reported_is_unreliable', True)
        self.unordered = state.get('unordered', False)
        self.last_moment = state.get('last_moment')

    def as_dict(self):
        return {'page': self.page, 'position': self.position, 'pending': self.pending,
                'seen': sorted(self.seen), 'done': self.done, 'terminal': self.terminal,
                'reported_total': self.reported_total, 'reported_is_unreliable': self.reported_is_unreliable,
                'unordered': self.unordered, 'last_moment': self.last_moment}


def collect(spec, fetch, *, limit, state=None, since=None, until=None, monotonic=False, commit=None):
    """fetch(page) -> Page. Returns the displayed records and the reason the walk stopped."""
    progress = Progress(state)
    lower, upper = kst_day(since, end=False), kst_day(until, end=True)
    if lower is not None and upper is not None and lower > upper:
        raise NaverBlogError(2, '--since must not be later than --until.')
    results, error, stop = [], None, None
    identifiers = set()

    while True:
        emitted = []
        while progress.pending and len(results) < limit:
            record = progress.pending.pop(0)
            identity = record.get('id')
            if identity is not None and identity in progress.seen:
                continue
            if identity is not None:
                progress.seen.add(identity)
            results.append(record)
            emitted.append(record)
        if not progress.pending and progress.done:
            stop = progress.terminal
        elif len(results) >= limit:
            # A finished walk keeps its real terminal: "capped" and "one page only" are not "more available".
            stop = (progress.terminal if progress.done and progress.terminal in
                    ('server_capped', 'not_paginable', 'pagination_stalled') else 'limit_reached')
        if commit and (emitted or stop):
            commit(emitted, progress.as_dict(), stop or 'page')
        if stop:
            break
        try:
            page = fetch(progress.page)
            if page.reported_total is not None:
                progress.reported_total = page.reported_total
                progress.reported_is_unreliable = page.reported_is_unreliable
            fingerprint = frozenset(record.get('id') for record in page.items)
            if fingerprint and fingerprint in identifiers:
                # The server ignoring the page parameter and real exhaustion cannot be told apart.
                progress.done, progress.terminal = True, 'pagination_stalled'
                continue
            identifiers.add(fingerprint)
            progress.position += page.raw_count
            records, window_reached = page.items, False
            if lower is not None or upper is not None:
                moments = [moment_of(record) for record in records]
                if any(moment is None for moment in moments):
                    progress.unordered = True
                records = [record for record, moment in zip(records, moments) if moment is not None
                           and (lower is None or moment >= lower) and (upper is None or moment <= upper)]
                present = [moment for moment in moments if moment is not None]
                if present:
                    if progress.last_moment is not None and max(present) > progress.last_moment:
                        progress.unordered = True
                    if any(a < b for a, b in zip(present, present[1:])):
                        progress.unordered = True
                    progress.last_moment = min(present)
                    # Only a newest-first surface lets a page below the window prove the window is done.
                    window_reached = bool(monotonic and lower is not None
                                          and max(present) < lower and not progress.unordered)
            progress.pending = records
            # A marked surface names its own next page; assuming page+1 would skip or repeat.
            progress.page = page.next_page if page.next_page is not None else progress.page + 1
            progress.done, progress.terminal = _terminal(spec, page, progress, window_reached)
            if commit and not records:
                commit([], progress.as_dict(), progress.terminal if progress.done else 'page')
        except NaverBlogError as exception:
            error = exception
            if exception.error == 'query_restricted' and getattr(exception, 'records', None):
                progress.pending = exception.records
            stop = ('blocked' if exception.code in (4, 5) else 'budget' if exception.error == 'budget'
                    else 'query_restricted' if exception.error == 'query_restricted' else 'query_failure')
            break

    code = 0
    if error:
        code = error.code if error.code in (4, 5) or not results else 8
    elif not results and stop in ('exhausted', 'window_reached', 'server_capped',
                                  'not_paginable', 'pagination_stalled'):
        # An empty result is only honest when nothing hid it; a ceiling is not an empty shelf.
        code = 7 if stop in ('exhausted', 'window_reached') else 8
    elif stop in ('server_capped', 'pagination_stalled'):
        code = 8
    return {'ok': error is None, 'results': results, 'stop_reason': stop, 'state': progress.as_dict(),
            'code': code, 'reported_total': progress.reported_total,
            # A walk that stopped for any reason can still be holding records the display
            # limit never reached; losing them would make "server_capped" mean "and the rest
            # is gone", which it does not.
            'pending': len(progress.pending),
            'reported_is_unreliable': progress.reported_is_unreliable,
            **({'error': error.error, 'message': error.message, 'fix': error.fix,
                'error_code': error.code} if error else {})}


def _terminal(spec, page, progress, window_reached):
    """Decide whether this page ended the walk, and under which of the four names."""
    if window_reached:
        return True, 'window_reached'
    if spec.pagination == 'single':
        return True, 'not_paginable'
    if spec.pagination == 'no_paging':
        capped = page.reported_total is not None and page.reported_total > page.raw_count
        return True, 'server_capped' if capped else 'not_paginable'
    if spec.pagination == 'page_marked':
        if page.next_page is None:
            return True, 'exhausted'
        return False, 'exhausted'
    if page.raw_count < (spec.page_size or 0):
        # Near the ceiling a short page is the ceiling: post search went short at 1,000 and
        # tag search went empty at 990. Anywhere else a short page is the end of the results.
        return True, 'server_capped' if spec.at_ceiling(progress.position) else 'exhausted'
    # A full page is only the end if it landed on the ceiling exactly; otherwise ask for the next.
    if spec.cap and progress.position >= spec.cap:
        return True, 'server_capped'
    return False, 'exhausted'
