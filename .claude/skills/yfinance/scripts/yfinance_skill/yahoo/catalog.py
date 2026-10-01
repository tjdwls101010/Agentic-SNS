"""Every dataset this skill reads, by the key a command names, and the call that fetches one."""
import yfinance as yf

from yfinance_skill.envelope import InputError
from yfinance_skill.yahoo import analysts, calendar, company, financials, fund, holders, market, options, prices, screen, search
from yfinance_skill.yahoo.encode import encode
from yfinance_skill.yahoo.refusals import refusal

DATASETS = {**search.DATASETS, **prices.DATASETS, **company.DATASETS, **financials.DATASETS, **analysts.DATASETS,
            **holders.DATASETS, **fund.DATASETS, **options.DATASETS, **screen.DATASETS, **market.DATASETS,
            **calendar.DATASETS}


def dataset(key):
    """The dataset a command names. A key with no dataset fails here, on the command's first use."""
    if key not in DATASETS:
        raise LookupError(f"yfinance_skill.yahoo defines no dataset {key!r}")
    return DATASETS[key]


def fetch(key, target, args, context, warnings, rows=None):
    """One target's response, encoded before anything is selected from it.

    `rows` is the row count in force, which a dataset that sends the source a count (`counted`) asks for. A failure the library or the source reports arrives as a SourceFailure; InputError, and anything that is not an Exception (the CLI's deadline), pass through unchanged.
    """
    found = dataset(key)
    yf.config.debug.hide_exceptions = False
    try:
        subject = yf.Ticker(target) if found.ticker else target
        return encode(found.fetch(subject, args, context, warnings, **({"rows": rows} if found.counted else {})))
    except InputError:
        raise
    except Exception as exc:
        raise refusal(exc) from exc
