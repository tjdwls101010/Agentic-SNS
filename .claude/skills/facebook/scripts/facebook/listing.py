"""feed, profile and group: post lists in the server's order, with the date-window policy of each order.

A newest-first list (feed or group --sort recent) closes a --since window at the first page that holds a dated,
unpinned, unsponsored post older than --since; pinned and undated posts pass any window and never close it. A ranked
list cannot close a window. A profile's window is filtered by Facebook. Days are local days.
"""
from datetime import date, datetime, time

from facebook import connect, graphql
from facebook.paging import paginate

ORDERS = {'feed': {'top': 'ranked', 'recent': 'newest_first'},
          'group': {'top': 'ranked', 'activity': 'ranked', 'recent': 'newest_first'}}


def feed(options):
    sort = options['sort']
    identity = {'sort': sort, 'since': options.get('since'), 'until': options.get('until'),
                'include_sponsored': bool(options.get('include_sponsored'))}

    def read(connection, state, out):
        return _read(options, identity, state, out, order=ORDERS['feed'][sort],
                     fetch=lambda cursor: connection.client.feed(sort, cursor),
                     skip_sponsored=not options.get('include_sponsored'), command='feed', target=None)

    return connect.run(options, command='feed', target=None, identity=identity, reader=read,
                       window=_window(options, ORDERS['feed'][sort]))


def profile(options):
    target = graphql.normalize_profile(options['target'])
    identity = {'since': options.get('since'), 'until': options.get('until')}
    after = _moment(options.get('since'), time.min)
    before = _moment(options.get('until'), time.max)

    def read(connection, state, out):
        profile_id = (state or {}).get('id') or connection.client.resolve('profile', target)
        return _read(options, identity, state, out, order='server', extra={'id': profile_id},
                     fetch=lambda cursor: connection.client.timeline(profile_id, cursor, after_time=after,
                                                                     before_time=before, url=target),
                     command='profile', target=target)

    return connect.run(options, command='profile', target=target, identity=identity, reader=read,
                       window=_window(options, 'server'))


def group(options):
    target = graphql.normalize_group(options['target'])
    sort = options['sort']
    identity = {'sort': sort, 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        group_id = (state or {}).get('id') or connection.client.resolve('group', target)
        return _read(options, identity, state, out, order=ORDERS['group'][sort], extra={'id': group_id},
                     fetch=lambda cursor: connection.client.group_feed(group_id, sort, cursor, url=target),
                     command='group', target=target)

    return connect.run(options, command='group', target=target, identity=identity, reader=read,
                       window=_window(options, ORDERS['group'][sort]))


def _read(options, identity, state, out, *, order, fetch, command, target, skip_sponsored=False, extra=None):
    since, until = options.get('since'), options.get('until')
    issues, notes = [], []

    def fetch_page(cursor):
        page = fetch(cursor)
        issues.extend(page.issues)
        notes.extend(page.issues)
        return page.records, page.page_info, page.has_items

    def commit(records, page_state, reason, skipped):
        out.commit(records, {**(page_state or {}), **(extra or {})} if page_state else None, reason, skipped,
                   list(dict.fromkeys(notes)))
        notes.clear()

    start = dict(out.state or {}) if out is not None else dict(state or {})
    if out is not None:
        start.update(seen=sorted(out.ids | out.skipped, key=str), pending=[])
    limit = options.get('limit')
    if out is not None and limit is not None:
        if out.count >= limit:
            return {'results': [], 'stop_reason': 'limit_reached', 'words': _words(identity)}
        limit -= out.count
    result = paginate(fetch_page, limit=limit, state=start,
                      keep=None if order == 'server' else lambda record: _in_window(record, since, until),
                      skip=(lambda record: record.get('sponsored')) if skip_sponsored else None,
                      closes=(lambda records: _passes(records, since)) if order == 'newest_first' and since else None,
                      commit=commit if out is not None else None, whole_pages=out is not None)
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': result['stop_reason'],
               'failure': result['failure'], 'issues': issues, 'words': _words(identity),
               'partial': bool(result['results'])}
    if skip_sponsored:
        reading['sponsored_skipped'] = len(result['skipped'])
    if result['state'] is not None:
        reading['continuation'] = {'command': command, 'target': target, 'identity': identity,
                                   'words': _words(identity), 'state': {**result['state'], **(extra or {})}}
    return reading


def _words(identity):
    words = []
    if identity.get('sort'):
        words += ['--sort', identity['sort']]
    for key in ('since', 'until'):
        if identity.get(key):
            words += ['--' + key, identity[key]]
    if identity.get('include_sponsored'):
        words.append('--include-sponsored')
    return words


def _window(options, order):
    if not (options.get('since') or options.get('until')):
        return None
    return {'order': order, 'since': options.get('since'), 'until': options.get('until')}


def _moment(day, clock):
    """The unix time at the start or end of a local day, as Facebook's timeline window takes it."""
    if not day:
        return None
    return int(datetime.combine(date.fromisoformat(day), clock).astimezone().timestamp())


def _local_day(record):
    return datetime.fromisoformat(record['created_at'].replace('Z', '+00:00')).astimezone().date()


def _in_window(record, since, until):
    if record.get('pinned') or not record.get('created_at'):
        return True
    day = _local_day(record)
    return (since is None or day >= date.fromisoformat(since)) and (until is None or day <= date.fromisoformat(until))


def _passes(records, since):
    """Whether a newest-first page reached --since."""
    # 성진: 최신순=시간순 실측(피드 9/9, 그룹 15/15) 위의 정지. 순서가 어긋난 응답이 관측되면 경계 이후 한 페이지 더 확인하도록 바꾼다
    start = date.fromisoformat(since)
    return any(r.get('created_at') and not r.get('pinned') and not r.get('sponsored') and _local_day(r) < start
               for r in records)
