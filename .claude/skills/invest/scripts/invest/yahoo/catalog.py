"""Every dataset by the key a command names ("history", "company.profile"), the kinds each command offers, and the call that fetches one target."""
import yfinance as yf

from invest.receipts import Failure
from invest.yahoo import analysts, calendar, company, financials, fund, holders, market, options, prices, screen, search
from invest.yahoo.refusals import refusal

DATASETS = {**search.DATASETS, **prices.DATASETS, **company.DATASETS, **financials.DATASETS, **analysts.DATASETS, **holders.DATASETS,
            **fund.DATASETS, **options.DATASETS, **screen.DATASETS, **market.DATASETS, **calendar.DATASETS}


def kinds():
    """{command: [kind, ...]}; a command without kinds maps to []."""
    found = {}
    for key in DATASETS:
        command, _, kind = key.partition(".")
        found.setdefault(command, [])
        if kind:
            found[command].append(kind)
    return found


def dataset(key):
    if key not in DATASETS:
        raise LookupError(f"invest.yahoo defines no dataset {key!r}")
    return DATASETS[key]


def check(key, args):
    """Refuse an argument before any request is made or anything is saved (a malformed screen query, an unknown sort field)."""
    dataset(key).check(args)


def warning_codes(key):
    return dataset(key).warning_codes()


def fetch(key, target, args):
    """One target's Observation. A failure the library or Yahoo reports arrives as a receipts.Failure with its code; anything that is not an Exception (the caller's deadline) passes through."""
    found = dataset(key)
    yf.config.debug.hide_exceptions = False
    try:
        return found.observe(target, args)
    except Failure:
        raise
    except Exception as exc:
        raise refusal(exc, args) from exc
