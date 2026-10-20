"""What one fetched page of a listing is, in the skill's own terms."""
from dataclasses import dataclass, field


@dataclass
class Page:
    """One page a platform's system read.

    records: the readable records, in the server's order.
    next: the cursor that asks for the page after (a string, or a dict such as {'page': 3}); None with end False means
      the answer carried no usable pagination data.
    end: the server says nothing follows.
    left_out: what was received and deliberately not shown, by label (e.g. {'promoted': 2}) — reported in coverage.
    unreadable: entries this skill could not read; a page of only those is the platform having changed its answer.
    reported_total: a total the platform states, when it states one (never a count of what was read).
    stop: a natural stop the platform's own rules decided on this page (not_paginable, server_capped,
      pagination_stalled); the page is kept and reading ends with that reason.
    """
    records: list
    next: object = None
    end: bool = False
    left_out: dict = field(default_factory=dict)
    unreadable: int = 0
    reported_total: int | None = None
    stop: str | None = None
