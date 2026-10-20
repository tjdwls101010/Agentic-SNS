"""feed, profile and group: post lists in the server's order, with the date-window policy of each order (sns.window).

A newest-first list (feed or group --sort recent) closes a --since window at the first page that holds a dated,
unpinned post older than --since; a ranked list (feed top, group top or activity) cannot close one; a profile's window
is filtered by Facebook as well. Days are local days. `surface` is the one place a Facebook answer becomes a reading
page: advertisements are left out (and counted) before the window weighs the page's order.
"""
from datetime import date, datetime, time

from sns import reading
from sns.page import Page
from sns.window import Window
from sns.facebook import web

# What a page left out, in coverage's words
NOTES = {'sponsored': 'sponsored posts (ads)'}
# What a response's issues become in coverage
ISSUES = {
    'unsupported_path_patch': 'part of a response could not be placed on any record; some records may lack fields',
    'graphql_errors': 'Facebook reported errors for part of a response; some records may lack fields',
    'cyclic_shared_story': 'a chain of shares looped back on itself and was cut there',
}


def paged(batch, *, keep_sponsored=False):
    """The reading Page of one answer (web.Batch): its cursor from page_info, ads counted and left out unless kept."""
    records = list(batch.records)
    # 성진: 광고만 있는 쪽이 연달아 둘 오면 paginate가 "새것 없는 쪽 2번"으로 읽기를 멈춘다(광고를 어댑터에서 빼므로). 실제로 보이면 idle_limit을 올린다
    left_out = {}
    if not keep_sponsored:
        ads = sum(1 for record in records if record.get('sponsored'))
        records = [record for record in records if not record.get('sponsored')]
        if ads:
            left_out['sponsored'] = ads
    info = batch.page_info if isinstance(batch.page_info, dict) else {}
    cursor = info.get('end_cursor') if info.get('has_next_page') is True and isinstance(info.get('end_cursor'), str) \
        else None
    # a page of items none of which could be read is the platform having changed its answer, not an empty one
    return Page(records, next=cursor or None, end=info.get('has_next_page') is False, left_out=left_out,
                unreadable=1 if batch.has_items and not batch.records else 0)


def ended(out):
    """A collection whose last page was committed but whose final line was lost: read_list judges its end again from
    the file, so nothing needs the id lookup a resumed read would otherwise make."""
    return out is not None and out.state is None and out.count and not out.complete


def issue_notes(issues):
    return [ISSUES.get(issue, issue) for issue in dict.fromkeys(issues)]


def surface(connection, state, out, *, fetch, order, command, target, identity, words=(), extra=None,
            keep_sponsored=False, end_covers_window=False):
    """Read a post list (fetch(cursor) → a web.Batch) as reading.read_list does; the issues of the answers read become
    coverage notes."""
    issues = []

    def read(cursor):
        batch = fetch(cursor)
        issues.extend(batch.issues)
        return paged(batch, keep_sponsored=keep_sponsored)

    result = reading.read_list(connection, state, out, order=order, command=command, target=target, identity=identity,
                               words=words, extra=extra, notes=NOTES, end_covers_window=end_covers_window, fetch=read)
    result['coverage'] = [*result.get('coverage', []), *issue_notes(issues)]
    return result


def window_of(platform, options, order):
    """The date window a result names even when the read failed before it began (None: no --since/--until)."""
    if not (options.get('since') or options.get('until')):
        return None
    return Window(options.get('since'), options.get('until'), order=order, policy=platform.window).describe()


def feed(platform, invocation):
    options = invocation.options
    sort = options['sort']
    keep = bool(options.get('include_sponsored'))
    order = 'ranked' if sort == 'top' else 'newest_first'
    identity = {'sort': sort, 'include_sponsored': True if keep else None}
    words = ['--sort', sort] + (['--include-sponsored'] if keep else [])

    def read(connection, state, out):
        return surface(connection, state, out, order=order, command='feed', target=None, identity=identity,
                       words=words, keep_sponsored=keep, fetch=lambda cursor: connection.client.feed(sort, cursor))

    # the ranked feed never ends by itself, so --out needs --limit
    return reading.run(platform, invocation, command='feed', target=None, identity=identity, reader=read,
                       window=window_of(platform, options, order), endless=order == 'ranked')


def profile(platform, invocation):
    options = invocation.options
    target = web.normalize_profile(options['target'])
    after = _moment(options.get('since'), time.min)
    before = _moment(options.get('until'), time.max)

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        profile_id = saved.get('id') or (None if ended(out) else client.resolve('profile', target))
        return surface(connection, state, out, order='server', command='profile', target=target, identity={},
                       extra={'id': profile_id}, end_covers_window=True,
                       fetch=lambda cursor: client.timeline(profile_id, cursor, after_time=after, before_time=before,
                                                            url=target))

    return reading.run(platform, invocation, command='profile', target=target, identity={}, reader=read,
                       window=window_of(platform, options, 'server'))


def group(platform, invocation):
    options = invocation.options
    target = web.normalize_group(options['target'])
    sort = options['sort']
    order = 'newest_first' if sort == 'recent' else 'ranked'
    identity = {'sort': sort}

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        group_id = saved.get('id') or (None if ended(out) else client.resolve('group', target))
        # a group's chronological end is its oldest post, so reaching it covers the window
        return surface(connection, state, out, order=order, command='group', target=target, identity=identity,
                       words=['--sort', sort], extra={'id': group_id}, end_covers_window=True,
                       fetch=lambda cursor: client.group_feed(group_id, sort, cursor, url=target))

    return reading.run(platform, invocation, command='group', target=target, identity=identity, reader=read,
                       window=window_of(platform, options, order))


def _moment(day, clock):
    """The unix time at the start or end of a local day, as Facebook's timeline window takes it."""
    if not day:
        return None
    return int(datetime.combine(date.fromisoformat(day), clock).astimezone().timestamp())
