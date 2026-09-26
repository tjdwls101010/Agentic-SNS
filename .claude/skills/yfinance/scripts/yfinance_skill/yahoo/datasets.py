"""What Yahoo returns for each command: how it is fetched, how much of it one screen shows, and what its values mean.

`units` carries scale and direction per field instead of prose, because a warning list only protects the fields someone
thought to list: a reader who sees the contract beside the value generalises where a reader who memorised six warnings
does not.
"""

RATE = {"scale": "ratio", "kind": "rate"}  # 0.0452 means 4.52%
PERCENT = {"scale": "percent", "kind": "rate"}  # 33.33 means 33.33%
WEIGHT = {"scale": "ratio", "kind": "weight"}
CURRENCY = {"kind": "currency"}
MULTIPLE = {"kind": "multiple"}
COUNT = {"kind": "count"}
SHARES = {"kind": "shares"}
PER_SHARE = {"kind": "per_share"}


class Dataset:
    """One dataset's contract with the source. `recent` is the one field that cannot be guessed: it says the source
    publishes oldest first, so a limit has to keep the tail. Declaring it per dataset rather than per group is not
    fussiness — the direction differs inside `analysts` and inside `calendar`, and a single flip would silently break
    the other half.

    `rows` and `fields` are the default window, what one screen shows. `prepare` fills in what the source itself fixes
    for a call (a preset's universe and sort); it only sets values on the namespace, because schema runs it on a
    synthetic one to report defaults.
    """

    def __init__(self, fetch, *, ticker=False, rows=None, fields=(), recent=False, units=None, interpretation=None,
                 limits=None, gotchas=(), conditions=None, prepare=None, sliceable=True, shares_info=False,
                 source_time=None, precise=()):
        self.fetch, self.ticker, self.rows, self.fields, self.recent = fetch, ticker, rows, tuple(fields), recent
        self.units, self.interpretation, self.limits = units or {}, interpretation or {}, limits or {}
        self.gotchas, self.conditions, self.prepare = tuple(gotchas), conditions, prepare
        self.sliceable, self.shares_info, self.source_time, self.precise = sliceable, shares_info, source_time, tuple(precise)


def asked(args, dataset):
    """The row count in force: an explicit --limit, else this dataset's own default window.

    Adapters that pass a count upstream need the same number local selection will use, or the window a caller sees is
    cut from a batch that was never sized for it.
    """
    explicit = getattr(args, "limit", None)
    return explicit if explicit is not None else dataset.rows
