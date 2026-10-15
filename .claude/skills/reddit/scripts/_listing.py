"""Validated Reddit envelopes and transport-independent listing selection."""
from copy import deepcopy
from datetime import datetime, timezone
import math
import re

from ._errors import RedditError
from ._models import build_post, build_comment
from ._entities import build_subreddit, build_user

_BUILDERS = {'t3': build_post, 't1': build_comment, 't5': build_subreddit, 't2': build_user}


def walk_listing_nodes(payload):
    """Yield things with their kind; never silently accept a malformed envelope."""
    if isinstance(payload, list):
        for child in payload:
            yield from walk_listing_nodes(child)
        return
    if not isinstance(payload, dict):
        raise RedditError(6, 'Expected a Reddit Listing or thing.')
    if 'json' in payload:
        envelope = payload['json']
        if (not isinstance(envelope, dict) or envelope.get('errors') != []
                or not isinstance(envelope.get('data'), dict)
                or not isinstance(envelope['data'].get('things'), list)):
            raise RedditError(6, 'Invalid morechildren envelope.')
        yield from walk_listing_nodes(envelope['data']['things'])
        return
    kind, data = payload.get('kind'), payload.get('data')
    if not isinstance(data, dict):
        raise RedditError(6, 'Reddit thing has no data object.')
    if kind == 'Listing':
        if not isinstance(data.get('children'), list):
            raise RedditError(6, 'Listing children must be an array.')
        after = data.get('after')
        if after is not None and (not isinstance(after, str) or not re.fullmatch(r't[1235]_[a-z0-9]+', after)):
            raise RedditError(6, 'Invalid Listing continuation fullname.')
        for child in data['children']:
            if not isinstance(child, dict) or child.get('kind') not in (*_BUILDERS, 'more'):
                raise RedditError(6, 'Invalid Listing child kind.')
            yield from walk_listing_nodes(child)
    elif kind in (*_BUILDERS, 'more'):
        if kind != 'more':
            name = kind + '_' + str(data.get('id', '')) if kind == 't2' else data.get('name', kind + '_' + str(data.get('id', '')))
            if not isinstance(name, str) or not re.fullmatch(kind + r'_[a-z0-9]+', name):
                raise RedditError(6, 'Invalid Reddit thing fullname.')
            if data.get('id') is not None and data['id'] != name[3:]:
                raise RedditError(6, 'Reddit thing id and fullname disagree.')
        yield payload
    else:
        raise RedditError(6, 'Unsupported Reddit thing kind.')


def parse_thing(thing):
    """Build a display model dictionary from one validated thing."""
    nodes = list(walk_listing_nodes(thing))
    if len(nodes) != 1 or thing.get('kind') not in _BUILDERS:
        raise RedditError(6, 'Expected one displayable Reddit thing.')
    return _BUILDERS[thing['kind']](thing['data']).to_dict()


def parse_date(value):
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        if isinstance(value, (int, float)):
            result = float(value)
        else:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            result = stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).timestamp()
        if not math.isfinite(result):
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise RedditError(2, 'Dates must be finite epochs or ISO dates/timestamps.') from None


def select_page(payload=None, *, state=None, limit=25, sort='new', since=None,
                until=None, account=None, captured_at=None):
    """Consume pending models first; None stop_reason means fetch the next page."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise RedditError(2, 'Listing limit must be a positive integer.')
    lower, upper = parse_date(since), parse_date(until)
    window = lower is not None or upper is not None
    if window and sort != 'new':
        raise RedditError(2, 'Date windows require sort=new.')
    if lower is not None and upper is not None and lower > upper:
        raise RedditError(2, 'since must not be after until.')
    current = deepcopy(state) if state is not None else dict(
        pending=[], seen=[], after=None, captured_at=captured_at or datetime.now(timezone.utc).isoformat(),
        account=account, window_reached=False)
    if current['account'] != account:
        raise RedditError(2, 'Listing continuation belongs to a different account.')
    if payload is not None:
        if current['pending']:
            raise RedditError(2, 'Drain cached listing records before fetching another page.')
        if not isinstance(payload, dict) or payload.get('kind') != 'Listing':
            raise RedditError(6, 'Page selection requires one Listing.')
        current['pending'] = [parse_thing(node) for node in walk_listing_nodes(payload)]
        current['after'] = payload['data'].get('after')
    seen, results = set(current['seen']), []
    while current['pending'] and len(results) < limit:
        record = current['pending'].pop(0)
        identity = record['fullname']
        if identity in seen:
            continue
        seen.add(identity)
        if window:
            stamp = parse_date(record.get('created_at'))
            if record.get('pinned') or stamp is None:
                record['window_excluded'] = 'pinned' if record.get('pinned') else 'undated'
            elif lower is not None and stamp < lower:
                current.update(window_reached=True, pending=[], after=None)
                break
            elif upper is not None and stamp > upper:
                continue
        results.append(record)
    current['seen'] = sorted(seen)
    reason = ('window_reached' if current['window_reached'] else
              'limit_reached' if current['pending'] else
              'exhausted' if current['after'] is None else None)
    return dict(results=results, state=current, stop_reason=reason)
