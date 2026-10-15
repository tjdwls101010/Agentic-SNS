"""Pure envelope reading: how many items the server really sent, and does it say there are more.

The raw count matters on its own because Naver's own totals are unusable — a post list
reports totalCount 0 forever, and a search past 1,000 reports 0 as well. So a page's raw
length, before any filtering this tool does, is the only honest end-of-results signal.
"""
from dataclasses import dataclass, field

from ._transport import at, drift


@dataclass
class Page:
    """One server answer, described in the terms the walker's caller can act on."""
    items: list = field(default_factory=list)
    raw_count: int = 0
    total_pages: int | None = None
    next_page: int | None = None
    reported_total: int | None = None
    # A server figure that is known to drift; kept for display, never for a decision.
    reported_is_unreliable: bool = True


def read_page(spec, payload, *, page=1):
    leaf = at(payload, spec.leaf) if spec.leaf else None
    if spec.leaf_type == 'list':
        if not isinstance(leaf, list):
            raise drift('Expected a list at ' + spec.leaf)
        items = leaf
    elif spec.leaf_type == 'dict':
        items = [leaf] if isinstance(leaf, dict) else []
    else:
        items = []
    result = Page(items=list(items), raw_count=len(items))

    if spec.marker:
        marker = at(payload, spec.marker)
        if isinstance(marker, bool) or not isinstance(marker, int):
            # A surface that promised a marker and stopped giving one has changed shape.
            raise drift('Expected a page marker at ' + spec.marker)
        result.total_pages = marker
        result.next_page = page + 1 if page < marker else None
    if spec.total_field:
        total = at(payload, spec.total_field)
        result.reported_total = total if isinstance(total, int) and not isinstance(total, bool) else None
    else:
        value = at(payload, 'result.totalCount')
        if isinstance(value, int) and not isinstance(value, bool):
            # A post list reports 0 forever. A zero next to actual items is provably false,
            # and repeating it would put a number in the header that means nothing.
            result.reported_total = None if value == 0 and items else value
    # The comment box is the one surface whose next-page marker has been trustworthy.
    if spec.op == 'comments':
        model = at(payload, 'result.pageModel') or {}
        following = model.get('nextPage')
        result.next_page = following if isinstance(following, int) and following > page else None
        counts = at(payload, 'result.count') or {}
        result.reported_total = counts.get('total') if isinstance(counts.get('total'), int) else result.reported_total
        result.reported_is_unreliable = False
    return result
