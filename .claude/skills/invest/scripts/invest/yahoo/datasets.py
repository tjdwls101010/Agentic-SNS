"""One dataset's contract with Yahoo: how it is fetched and what it hands back in the skill's terms.

A fetch returns what the library returned and records on its Context what the response itself says besides the rows: which currency, when the values were true, how much of the source they cover, which conditions the rows confirm, and what changes their interpretation (warnings) or explains it (notes). `Dataset.observe` then turns the library value into rows or records with every unit normalised, so nothing outside this package sees Yahoo's scales.
"""
import pandas as pd
import yfinance as yf

from invest.yahoo import encode, refusals, timing, units


class Context:
    """What one target's fetch learns besides its rows. `receipt` holds facts kept only in receipt.json (evidence, the query sent)."""

    def __init__(self, args, target):
        self.args, self.target = args, target
        self.warnings, self.notes = {}, []
        self.coverage, self.conditions, self.as_of, self.receipt = {}, {}, {}, {}
        self.currency = self.financial_currency = self.quote_type = self.observed_at = None
        self.rate_limited = False

    def warn(self, code, text):
        self.warnings.setdefault(code, text)

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)


class Observation:
    """One target's result in the skill's terms: rows (format csv) or records (format json), each value on the skill's scale.

    `units` maps every column (or record field) to a unit of the vocabulary and `statuses` says whether each is verified or declared. `keys` are the columns that identify a row, kept in any inline projection. `precise` names the columns whose inline display keeps 7 significant digits; `fields` is the default inline projection of a wide record; `preview` turns records into the short form a trimmed receipt shows.
    """

    def __init__(self, context, *, columns=None, rows=None, records=None, units=None, statuses=None, empty=False, precise=(),
                 fields=(), preview=None, keys=()):
        self.columns, self.rows, self.records, self.keys = columns, rows, records, tuple(keys)
        self.format = "csv" if columns is not None else "json"
        self.units, self.statuses = units or {}, statuses or {}
        self.empty, self.precise, self.fields, self.preview = empty, tuple(precise), tuple(fields), preview
        self.warnings, self.notes = dict(context.warnings), list(context.notes)
        self.coverage, self.conditions, self.as_of, self.receipt = context.coverage, context.conditions, context.as_of, context.receipt
        self.currency, self.financial_currency = context.currency, context.financial_currency
        self.rate_limited, self.observed_at = context.rate_limited, context.observed_at

    @property
    def count(self):
        if self.columns is not None:
            return len(self.rows)
        if isinstance(self.records, list):
            return len(self.records)
        return None if self.records is None else 1


def blank(value):
    if value is None or value == "" or value == [] or value == {}:
        return True
    if isinstance(value, list):
        return all(blank(v) for v in value)
    if isinstance(value, dict):
        return all(blank(v) for v in value.values())
    return False


def empty_rows(columns, rows, keys):
    """No rows, or rows whose every value outside the identifying columns is blank (a fund statistic table of nulls is empty)."""
    measured = [i for i, c in enumerate(columns) if c not in keys] or list(range(len(columns)))
    return not rows or all(blank(row[i]) for row in rows for i in measured)


def flat_rows(records):
    """(columns, rows) from a list of mappings: the union of their keys in first-seen order, a missing key left empty."""
    columns = []
    for record in records:
        for key in record:
            if key not in columns:
                columns.append(key)
    return columns, [[record.get(c) for c in columns] for record in records]


def quote_currency(ticker, context):
    """The currency the symbol is quoted in, from one chart-metadata request, for a dataset whose own response does not name it."""
    try:
        context.currency = (ticker.get_history_metadata() or {}).get("currency")
    except Exception as exc:
        if refusals.is_rate_limited(exc):
            context.rate_limited = True
            context.warn("secondary_rate_limited", "Yahoo rate-limited the currency lookup after the data arrived; the data is kept and the remaining targets were not attempted.")
        context.receipt["currency_error"] = str(exc)


MONEY_ROLES = {units.MONEY_QUOTE: "currency", units.PER_SHARE_QUOTE: "currency",
               units.MONEY_FINANCIAL: "financial_currency", units.PER_SHARE_FINANCIAL: "financial_currency"}


class Dataset:
    """How one command kind reads Yahoo. `form` is how its library value becomes rows:

    - table: a DataFrame or Series; index levels become leading columns.
    - row: one flat mapping, one row per target.
    - rows: a list of flat mappings, one row each, under the union of their keys.
    - mixed: a table whose rows carry different units in one column; each cell becomes (metric, source_column, value, unit), with `mixed(metric, column)` deciding the unit.
    - records: any JSON value, saved as result.json; `units` names the unit of each declared field.

    `row_currency` names the column that gives each row's own currency, for rows that are different instruments (a screen, a market summary).
    `coverage` is the sentence saying how much of the source the rows are; `notes` explain the values; `possible` lists every warning code this dataset can raise, which bounds the receipt that cannot be cut. `counted` datasets send the source a count (`args.limit`).
    """

    def __init__(self, fetch, *, form="table", units=None, coverage=None, notes=(), possible=(), ticker=True, counted=False, precise=(),
                 fields=(), preview=None, mixed=None, label=None, index=True, keys=(), row_currency=None, check=None):
        self.fetch, self.form, self.units = fetch, form, units or {}
        self.coverage, self.notes, self.possible = coverage, tuple(notes), tuple(possible)
        self.ticker, self.counted, self.precise, self.fields, self.preview = ticker, counted, tuple(precise), tuple(fields), preview
        self.mixed, self.label, self.index, self.keys, self.row_currency = mixed, label, index, tuple(keys), row_currency
        if check:
            self.check = check

    def warning_codes(self):
        """Every code this dataset's receipts can carry, the shared ones included."""
        shared = ("unit_undeclared", "currency_unconfirmed", "secondary_rate_limited")
        return tuple(dict.fromkeys(self.possible + shared))

    def check(self, args):
        """Refuse, before any request, an argument this dataset can judge without the network; most have none."""

    def reader(self, args, target):
        """(fetch, target) for this call; a dataset whose source depends on its arguments overrides it."""
        return self.fetch, (yf.Ticker(target) if self.ticker else target)

    def form_for(self, args):
        return self.form

    def observe(self, target, args):
        context = Context(args, target)
        fetch, subject = self.reader(args, target)
        value = fetch(subject, args, context)
        context.observed_at = context.observed_at or timing.now()
        for text in self.notes:
            context.note(text)
        if self.coverage and "statement" not in context.coverage:
            context.coverage = {"statement": self.coverage, **context.coverage}
        found = self.shape(value, context)
        if self.ticker and not found.empty and found.currency is None and self.needs_quote_currency(found):
            quote_currency(subject, context)
            found.currency, found.rate_limited = context.currency, context.rate_limited
            found.warnings.update(context.warnings)
        self.check_currency(found, context)
        if found.count is not None:
            found.coverage = {**found.coverage, "received": found.count}
        return found

    def shape(self, value, context):
        warn, quote_type, form = context.warn, context.quote_type, self.form_for(context.args)
        if form == "records":
            records = encode.encode(value)
            if isinstance(records, dict) and self.units:
                records, found_units, statuses = units.normalise_record(records, self.units, warn, quote_type)
            elif isinstance(records, list) and self.units:
                found_units, statuses, normalised = {}, {}, []
                for item in records:
                    item, item_units, item_statuses = units.normalise_record(item, self.units, warn, quote_type) if isinstance(item, dict) else (item, {}, {})
                    normalised.append(item)
                    found_units.update(item_units)
                    statuses.update(item_statuses)
                records = normalised
            else:
                found_units, statuses = {}, {}
            return Observation(context, records=records, units=found_units, statuses=statuses, empty=blank(records),
                               fields=self.fields, preview=self.preview)
        if form == "mixed":
            columns, rows = self.mixed_rows(value, warn)
            return Observation(context, columns=columns, rows=rows, units={"metric": units.TEXT, "source_column": units.TEXT, "value": units.MIXED, "unit": units.TEXT},
                               statuses=self.mixed_statuses(value), empty=not rows or all(r[2] is None for r in rows), keys=("metric", "source_column", "unit"))
        keys = self.keys
        if form == "row":
            mapping = encode.encode(value) if value is not None else {}
            columns, rows = (list(mapping), [list(mapping.values())]) if mapping else ([], [])
        elif form == "rows":
            columns, rows = flat_rows(encode.encode(value) if value is not None else [])
        else:
            columns, rows, leading = encode.table(value, index=self.index) if value is not None else ([], [], [])
            keys = keys or tuple(leading)
        rows, found_units, statuses = units.normalise_table(columns, rows, self.units, warn, quote_type)
        return Observation(context, columns=columns, rows=rows, units=found_units, statuses=statuses, empty=empty_rows(columns, rows, keys),
                           precise=self.precise, keys=keys)

    def mixed_cells(self, frame):
        """(metric, source column, raw value) for every cell of a table whose rows differ in unit."""
        if frame is None or (isinstance(frame, pd.DataFrame) and frame.empty):
            return []
        if self.label:
            frame = frame.set_index(self.label)
        cells = []
        for metric, row in frame.iterrows():
            for column, value in row.items():
                cells.append((encode.encode(metric), encode.label(column), encode.encode(value)))
        return cells

    def mixed_rows(self, frame, warn):
        rows = []
        for metric, column, value in self.mixed_cells(frame):
            unit = self.mixed(metric, column)
            rows.append([metric, column, units.converted(value, unit.convert, warn, f"{metric} ({column})"), unit.name])
        return ["metric", "source_column", "value", "unit"], rows

    def mixed_statuses(self, frame):
        found = {"metric": units.DECLARED, "source_column": units.DECLARED, "unit": units.DECLARED}
        for metric, column, _ in self.mixed_cells(frame):
            found[f"{metric} | {column}"] = self.mixed(metric, column).status
        return found

    def needs_quote_currency(self, found):
        roles = set(found.units.values()) | ({r[3] for r in found.rows} if found.format == "csv" and "unit" in (found.columns or []) else set())
        return bool(roles & {units.MONEY_QUOTE, units.PER_SHARE_QUOTE})

    def check_currency(self, found, context):
        """A money value whose currency the source did not give keeps its value and says so."""
        if self.row_currency:
            found.notes.append(f"Each row is its own instrument: its {self.row_currency} column names the currency of its money values.")
            return
        roles = {MONEY_ROLES[u] for u in found.units.values() if u in MONEY_ROLES}
        if found.format == "csv" and "unit" in (found.columns or []):
            roles |= {MONEY_ROLES[r[3]] for r in found.rows if r[3] in MONEY_ROLES}
        missing = [role for role in sorted(roles) if getattr(found, role) is None]
        if missing and not found.empty:
            found.warnings.setdefault("currency_unconfirmed", f"The source gave no {' or '.join(missing)} for these money values; their currency is unconfirmed.")
