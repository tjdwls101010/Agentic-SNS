"""How Naver's numbered pages go, and why a listing stopped — the decision Naver's own numbers cannot make.

Three stops look alike from inside one page: the results ended, the server hit its 1,000-result ceiling, and the server
ignored the page number. Each has its own stop reason, and none is inferred from a total Naver reported. A surface's
Policy says how its pages go; numbered() turns a source of Fetched pages into the fetch(cursor) that sns.paging
paginates, carrying the page number and the position (records received so far, which the ceiling arithmetic needs) in
the cursor so a continuation resumes exactly there.
"""
from dataclasses import dataclass, field

from sns.errors import SnsError
from sns.page import Page


@dataclass(frozen=True)
class Policy:
    """How a surface's pages go: plain (page + 1; a short page ends it, or is the ceiling near it) or marked (the
    answer names its last page). ceiling: the most results Naver serves in any order."""
    pagination: str
    page_size: int | None = None
    ceiling: int | None = None

    def at_ceiling(self, position):
        """Is a short page here the ceiling rather than the end? Post search went short at 1,000 and tag search empty
        at 990: the test is whether one more page would cross it."""
        return bool(self.ceiling) and position + (self.page_size or 0) > self.ceiling


@dataclass
class Fetched:
    """One answer: its records, how many the server really sent (before any filtering), and its paging marks."""
    items: list = field(default_factory=list)
    raw_count: int = 0
    last_page: int | None = None       # a marked surface's last page number
    next_page: int | None = None       # a surface that names its next page itself (the comment box)
    reported_total: int | None = None  # Naver's own figure: it drifts, so it is shown and never decided on
    ends: bool = False                 # the answer closes the listing whatever its size (a restricted query)


def numbered(policy, source):
    """fetch(cursor) → sns.page.Page for a numbered surface. source(number) returns a Fetched. The same set of records
    twice is the server ignoring the page number: reading stops there (pagination_stalled)."""
    seen = set()

    def fetch(cursor):
        cursor = cursor or {}
        number, before = cursor.get('page', 1), cursor.get('position', 0)
        got = source(number)
        fingerprint = frozenset(record.get('id') for record in got.items)
        if fingerprint and fingerprint in seen:
            return Page([], end=True, stop='pagination_stalled', reported_total=got.reported_total)
        seen.add(fingerprint)
        position = before + got.raw_count
        end, stop, following = _terminal(policy, got, number, before, position)
        return Page(got.items, next=None if end else {'page': following, 'position': position}, end=end, stop=stop,
                    reported_total=got.reported_total,
                    unreadable=0 if got.items else got.raw_count)   # items came and none could be read: a changed answer
    return fetch


def _terminal(policy, got, number, before, position):
    """(end, stop, the next page's number) after one page."""
    capped = bool(policy.ceiling) and position >= policy.ceiling
    if got.ends:
        return True, None, None
    if got.next_page is not None:
        return False, None, got.next_page
    if policy.pagination == 'marked':
        if isinstance(got.last_page, bool) or not isinstance(got.last_page, int):
            raise SnsError('failed', 'A page did not say how many pages there are.',
                           'Run doctor; the response shape changed.', reason='drift')
        if number >= got.last_page:
            return True, 'server_capped' if capped else None, None
        return False, None, number + 1
    if got.raw_count < (policy.page_size or 0):
        return True, 'server_capped' if policy.at_ceiling(before) or capped else None, None
    if capped:
        return True, 'server_capped', None
    return False, None, number + 1
