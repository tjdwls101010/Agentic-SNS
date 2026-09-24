"""One declaration per leaf: its arguments, its adapter, how much of it a first call returns, and the contracts a value
cannot be read without.

Leaf knowledge used to live in six places — the parser's if-chain, the validator's, a recovery filter that mirrored the
validator by hand, two adapter dispatchers and a condition dispatcher — so changing a leaf meant finding all six, and a
recovery sentence could name a narrowing the leaf's mode rejects. Here each group module declares its leaves with
`@leaf`, and the parser, validation, selection, recovery and schema all read that one declaration.

`units` carries scale and direction per field instead of prose, because a warning list only protects the fields someone
thought to list: a reader who sees the contract beside the value generalises where a reader who memorised six warnings
does not.
"""
import argparse

RATE = {"scale": "ratio", "kind": "rate"}  # 0.0452 means 4.52%
PERCENT = {"scale": "percent", "kind": "rate"}  # 33.33 means 33.33%
WEIGHT = {"scale": "ratio", "kind": "weight"}
CURRENCY = {"kind": "currency"}
MULTIPLE = {"kind": "multiple"}
COUNT = {"kind": "count"}
SHARES = {"kind": "shares"}
PER_SHARE = {"kind": "per_share"}

GLOBAL_DEFAULTS = {"max_chars": 20000, "filter": "", "ttl_days": 14}


class Arg:
    """One argparse argument. `minimum` is checked after parsing, with the same message for every leaf."""

    def __init__(self, *flags, minimum=None, **kwargs):
        self.flags, self.minimum, self.kwargs = flags, minimum, kwargs

    @property
    def dest(self):
        return self.kwargs.get("dest") or self.flags[-1].lstrip("-").replace("-", "_")

    def add(self, parser):
        parser.add_argument(*self.flags, **self.kwargs)


class OneOf:
    """Arguments of which exactly one (or at most one) is given."""

    def __init__(self, *args, required=False):
        self.args, self.required = args, required

    def add(self, parser):
        group = parser.add_mutually_exclusive_group(required=self.required)
        for arg in self.args:
            arg.add(group)


def dates(help_start, help_end):
    return [Arg("--start", help=help_start), Arg("--end", help=help_end)]


SYMBOLS = Arg("symbols", nargs="+", help="One or more Yahoo symbols; each is queried separately.")


class Leaf:
    """A leaf's contract. `recent` is the one field that cannot be guessed: it says the source publishes oldest first,
    so a limit has to keep the tail. Declaring it per leaf rather than per group is not fussiness — the direction
    differs inside `analysts` and inside `calendar`, and a single flip would silently break the other half.

    `defaults` fills the namespace (execution, schema and the echoed request all read it), `check` only reads it, and
    `forbidden` names the narrowings this call's own mode rejects so a recovery never recommends them.
    """

    def __init__(self, group, name, purpose, fetch, *, args=(), ticker=False, limit=None, fields=(), recent=False, narrow=(),
                 units=None, interpretation=None, limits=None, gotchas=(), conditions=None, defaults=None, check=None,
                 forbidden=None, sliceable=True, shares_info=False, source_time=None, end_exclusive=False, epilog=None,
                 exportable=True, precise=(), coarser=None):
        self.group, self.name, self.purpose, self.fetch = group, name, purpose, fetch
        self.args, self.ticker, self.limit, self.fields, self.recent = tuple(args), ticker, limit, tuple(fields), recent
        self.narrow, self.gotchas = tuple(narrow), tuple(gotchas)
        self.units, self.interpretation, self.limits = units or {}, interpretation or {}, limits or {}
        self.conditions, self.defaults, self.check, self.forbidden = conditions, defaults, check, forbidden
        self.sliceable, self.shares_info, self.source_time = sliceable, shares_info, source_time
        self.end_exclusive, self.epilog, self.exportable, self.precise = end_exclusive, epilog, exportable, tuple(precise)
        self.coarser = coarser

    @property
    def path(self):
        return self.group + (" " + self.name if self.name else "")

    def limit_keeps(self):
        return "the newest rows of a series the source publishes oldest first" if self.recent else "the first rows in source order"

    def positionals(self):
        """The targets this leaf is asked about: its positional arguments, never an option that happens to share a name."""
        return [arg.dest for arg in self.args if isinstance(arg, Arg) and not arg.flags[0].startswith("-")]

    def minimums(self):
        return {arg.dest: arg.minimum for arg in self.args if isinstance(arg, Arg) and arg.minimum is not None}


GROUPS = {}
LEAVES = {}


def group(name, purpose):
    GROUPS[name] = purpose


def leaf(group_name, name, purpose, **spec):
    """Register the decorated adapter as this leaf's fetch. With ticker=True it receives a yf.Ticker for the target."""
    def register(fetch):
        LEAVES[group_name, name] = Leaf(group_name, name, purpose, fetch, **spec)
        return fetch
    return register


def get(group_name, name):
    return LEAVES.get((group_name, name))


def by_path(path):
    return get(*path.split(" ", 1)) if " " in path else get(path, "")


def effective_limit(args, item):
    """The row count in force: an explicit --limit, else this leaf's own default window.

    Adapters that pass a count upstream need the same number local selection will use, or the window a caller sees is
    cut from a batch that was never sized for it.
    """
    explicit = getattr(args, "limit", None)
    return explicit if explicit is not None else (item.limit if item else None)


OUT_HELP = ("Write this observation's rows to a new CSV file and print only a summary: every digit and timestamp as saved, one target column, "
            "table indices as columns, option sides as side, mapping keys as key, lists of values as value, nested records as dotted columns, "
            "other objects and lists as JSON cells, nulls as blank cells, and a name that would collide prefixed source. — read the returned columns. "
            "The screen's default window and projection do not apply; an explicit --fields or --limit does. Commands that ask the source for a set number of rows "
            "(news, screen, calendars) still ask for their default unless --limit raises it, and no further pages are fetched. "
            "Targets with nothing selected add no rows and no file is made when none do, so check each target's status before comparing. An existing file is never overwritten.")


def add_common(parser, selection=True, root=False):
    parser.add_argument("--max-chars", type=int, default=GLOBAL_DEFAULTS["max_chars"] if root else argparse.SUPPRESS, help="Maximum JSON characters. Each command's own default window is what keeps a result to one screen; this is the safety boundary behind it.")
    parser.add_argument("--filter", default=GLOBAL_DEFAULTS["filter"] if root else argparse.SUPPRESS, help="Case-insensitive substring for schema, catalogs or --list-fields.")
    parser.add_argument("--store", default=argparse.SUPPRESS if not root else None, help="Directory holding saved observations; the same path is needed to read an earlier id. Defaults to the user cache, or $YF_STORE.")
    if selection:
        parser.add_argument("--fields", type=lambda value: [f.strip() for f in value.split(",")], help="Comma-separated output fields, replacing this command's default projection. Nested payloads take dotted paths such as content.title; --list-fields names them.")
        parser.add_argument("--list-fields", action="store_true", help="Name the fields available for this dataset and target instead of returning values.")
        parser.add_argument("--limit", type=int, help="Maximum output rows, replacing this command's default window. schema reports which end of the series a limit keeps.")
        parser.add_argument("--timeout", type=int, default=30, help="Wall-clock seconds per target (includes library calls); default 30.")
