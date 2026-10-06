"""When a value was true: whether the last bar of a series is final, judged from the session the source reports against the time the response arrived.

A daily bar dated today, fetched while the exchange is open, is the price so far. The verdict compares the observation time with the end of the regular session Yahoo reports for the bar's day, never with the time of the last trade, and it is `unknown` rather than `final` whenever the session or time zone is missing.
"""
import datetime as dt
import time

PERIODS = {"1wk": dt.timedelta(days=7)}
INTRADAY = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "90m": 90, "1h": 60}


def now():
    """The observation time, read from the process clock."""
    return dt.datetime.fromtimestamp(time.time(), dt.timezone.utc)


def stamp(value):
    """An aware datetime from an epoch, an ISO string or a pandas Timestamp; None when it cannot be read."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc)
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else None
    return None


def month_end(start, months):
    month = start.month - 1 + months
    return start.replace(year=start.year + month // 12, month=month % 12 + 1, day=1)


def last_bar(bar_start, interval, observed, session=None, zone=None):
    """(status, reason) for the newest bar: final, provisional or unknown.

    `bar_start` is the bar's own timestamp, `session` the (start, end) of the regular session Yahoo reports as current, `zone` the exchange's time zone.
    """
    bar_start, observed = stamp(bar_start), stamp(observed)
    if bar_start is None or observed is None:
        return "unknown", "the last bar or the observation time has no time zone"
    if interval in INTRADAY:
        end = bar_start + dt.timedelta(minutes=INTRADAY[interval])
        return ("provisional", f"the bar runs until {end.isoformat()}") if observed < end else ("final", f"the bar ended at {end.isoformat()}")
    if interval in ("1mo", "3mo") or interval in PERIODS:
        end = month_end(bar_start, 1 if interval == "1mo" else 3) if interval in ("1mo", "3mo") else bar_start + PERIODS[interval]
        if observed < end:
            return "provisional", f"the bar's period runs until {end.date().isoformat()}"
        return "final", f"the bar's period ended {end.date().isoformat()}"
    if interval != "1d":
        return "unknown", f"the source does not state the span of a {interval} bar"
    if not session or zone is None:
        return "unknown", "Yahoo reported no current trading session for this instrument"
    start, end = stamp(session[0]), stamp(session[1])
    if start is None or end is None:
        return "unknown", "the reported session has no time zone"
    bar_day, session_day = bar_start.astimezone(zone).date(), start.astimezone(zone).date()
    if bar_day < session_day:
        return "final", f"the bar is for {bar_day.isoformat()}, before the current session ({session_day.isoformat()})"
    if bar_day > session_day:
        return "unknown", f"the bar ({bar_day.isoformat()}) is dated after the reported session ({session_day.isoformat()})"
    if observed < end:
        return "provisional", f"observed before the session closes at {end.isoformat()}"
    return "final", f"observed after the session closed at {end.isoformat()}"
