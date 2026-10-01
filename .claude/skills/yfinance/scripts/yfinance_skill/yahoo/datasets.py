"""What Yahoo returns for each command: how it is fetched, in what order it arrives, and what its values mean.

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

    How much one screen shows is the command's to declare (cli.py). A `counted` dataset sends the source a count: its fetch takes `rows`, the count in force for this call, and records what it asked for as context["requested"]; `shortfall` is what fewer rows than that means for this dataset, formatted with {received} and {requested}, and a dataset without one makes no claim either way. `prepare` fills in what the source itself fixes for a call (a preset's universe and sort); it only sets values on the namespace, because schema runs it on a synthetic one to report defaults. `keyed` says the source returns records keyed by name, which the skill orders by key. `coarser` maps an interval to the next coarser one a too-long series can be asked for again at, as (that interval, its bars' name, these bars' name), or None.
    """

    def __init__(self, fetch, *, ticker=False, counted=False, recent=False, units=None, interpretation=None,
                 limits=None, gotchas=(), conditions=None, prepare=None, sliceable=True, shares_info=False,
                 source_time=None, precise=(), shortfall=None, coarser=None, keyed=False):
        self.fetch, self.ticker, self.counted, self.recent, self.keyed = fetch, ticker, counted, recent, keyed
        self.units, self.interpretation, self.limits = units or {}, interpretation or {}, limits or {}
        self.gotchas, self.conditions, self.prepare = tuple(gotchas), conditions, prepare
        self.sliceable, self.shares_info, self.source_time, self.precise = sliceable, shares_info, source_time, tuple(precise)
        self.shortfall, self.coarser = shortfall, coarser
