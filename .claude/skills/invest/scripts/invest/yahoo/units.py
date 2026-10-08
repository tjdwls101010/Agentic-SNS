"""The skill's unit vocabulary and the normalisation every dataset passes through before its values leave this package.

A value leaves as a ratio (0.0302, never 3.02 meaning percent) or a multiple (28.3, never its reciprocal), so a reader never converts a scale; what was converted is said by the unit and by a warning or note, never by a second copy of the raw value. The scale is changed and nothing else: a field keeps its name and its meaning.
"""
import datetime as dt

RATIO, MULTIPLE, SHARES, COUNT, RANK = "ratio", "multiple", "shares", "count", "rank"
MONEY_QUOTE, MONEY_FINANCIAL, MONEY_UNCONFIRMED = "money:quote", "money:financial", "money:unconfirmed"
PER_SHARE_QUOTE, PER_SHARE_FINANCIAL, PER_SHARE_UNCONFIRMED = "per_share:quote", "per_share:financial", "per_share:unconfirmed"
DATE, DATETIME, TEXT, UNVERIFIED = "date", "datetime", "text", "unverified"
VOCABULARY = (RATIO, MULTIPLE, SHARES, COUNT, RANK, MONEY_QUOTE, MONEY_FINANCIAL, MONEY_UNCONFIRMED,
              PER_SHARE_QUOTE, PER_SHARE_FINANCIAL, PER_SHARE_UNCONFIRMED, DATE, DATETIME, TEXT, UNVERIFIED)
MIXED = "per row: see the unit column"

VERIFIED, DECLARED, UNDECLARED = "verified", "declared", "undeclared"
PERCENT, INVERSE = "percent", "inverse"  # the two scale conversions: x / 100, and 1 / x
EPOCH, EPOCH_MS = "epoch", "epoch_ms"  # Unix seconds or milliseconds written as an ISO time in UTC, so no reader converts them


class Unit:
    """One field's unit, the conversion its raw value needs, and whether that is verified (a relation or measurement stands behind it) or declared (carried over from an earlier reading).

    `by_quote_type` maps a quoteType to a different conversion for the same field, for a source that changes scale with the instrument.
    """

    def __init__(self, name, convert=None, evidence=None, by_quote_type=None):
        assert name in VOCABULARY, name
        self.name, self.convert, self.evidence, self.by_quote_type = name, convert, evidence, by_quote_type or {}

    @property
    def status(self):
        return VERIFIED if self.evidence else DECLARED

    def conversion(self, quote_type=None):
        return self.by_quote_type.get(quote_type, self.convert)


def u(name, convert=None, evidence=None, **kwargs):
    return Unit(name, convert, evidence, **kwargs)


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def converted(value, convert, warn=None, field=None):
    """The value on the skill's scale. A reciprocal of zero does not exist, so it becomes null and says why; a negative keeps its sign."""
    if convert is None or not numeric(value):
        return value
    if convert == PERCENT:
        return value / 100
    if convert in (EPOCH, EPOCH_MS):
        seconds = value / 1000 if convert == EPOCH_MS else value
        try:
            return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return value
    if convert == INVERSE:
        if value == 0:
            if warn:
                warn("inverse_of_zero", f"{field} arrived as 0, whose reciprocal does not exist, so it is null; the source reports this multiple as its reciprocal.")
            return None
        return 1 / value
    raise ValueError(convert)


def guess(values):
    """The unit of an undeclared column that holds no number: a date, a timestamp or text."""
    strings = [v for v in values if v is not None]
    if strings and all(isinstance(v, str) and len(v) >= 10 and v[4] == "-" and v[7] == "-" for v in strings):
        return DATE if all(len(v) == 10 or v[10:19] == "T00:00:00" for v in strings) else DATETIME
    return TEXT


def normalise_table(columns, rows, declared, warn, quote_type=None, skip=()):
    """(rows, units, statuses) with every declared conversion applied. A numeric column without a declaration is reported as undeclared, never guessed."""
    units, statuses, out = {}, {}, [list(r) for r in rows]
    for i, name in enumerate(columns):
        values = [r[i] for r in rows]
        unit = declared.get(name) or declared.get("*") if name not in skip else None
        if unit is None:
            if any(numeric(v) for v in values) and name not in skip:
                units[name], statuses[name] = UNVERIFIED, UNDECLARED
                warn("unit_undeclared", f"{name} has no declared unit; do not compute with it.")
            else:
                units[name], statuses[name] = guess(values), DECLARED
            continue
        convert = unit.conversion(quote_type)
        for row in out:
            row[i] = converted(row[i], convert, warn, name)
        units[name], statuses[name] = unit.name, unit.status
    return out, units, statuses


def normalise_record(record, declared, warn, quote_type=None):
    """(record, units, statuses) for a flat mapping such as Yahoo's info: every numeric field converted by its declaration."""
    out, units, statuses = dict(record), {}, {}
    for name, value in record.items():
        unit = declared.get(name)
        if unit is None:
            if numeric(value):
                units[name], statuses[name] = UNVERIFIED, UNDECLARED
                warn("unit_undeclared", "A numeric field has no declared unit; do not compute with it (receipt.json lists which).")
            continue
        out[name] = converted(value, unit.conversion(quote_type), warn, name)
        units[name], statuses[name] = unit.name, unit.status
    return out, units, statuses
