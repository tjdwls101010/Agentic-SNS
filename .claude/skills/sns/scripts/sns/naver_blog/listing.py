"""The listing every numbered Naver surface shares (search, a blog's posts, the feed, neighbors, topics, comments): pages
asked for by number, what Naver's own rules make of their ends (a short page, the last page it names, the
1,000-result ceiling, the same page twice), and what a restricted query keeps — read through reading.read_list, so the
screen's size, --limit, windows, handles and --out files work as on every platform."""
from sns import reading
from sns.errors import SnsError

from sns.naver_blog import account, web

EMPTY_FIX = 'Try another target, keyword or window; an explicitly empty result is not a failure.'


def resumed(state, out):
    """The state a reading starts from: a handle's, or the --out file's last committed page."""
    return dict(out.state or {}) if out is not None else dict(state or {})


def window_of(options, order):
    """The window a result states even when the read failed before it was made."""
    if options.get('since') or options.get('until'):
        return {'since': options.get('since'), 'until': options.get('until'), 'order': order}
    return None


def pages_of(client, op, ids, build):
    """source(number) → Fetched for a plain surface: ledger row `op`, identifiers `ids`, records built by `build`."""
    return lambda number: client.page(op, number, build, **ids)[0]


def read_numbered(connection, state, out, *, op, source, command, target, identity, order, show, words=(), blog=None,
                  carry=None, end_covers_window=True, empty=None):
    """One numbered surface as a reading.

    op: its ledger row (how its pages go). source(number): its Fetched pages (see pages_of). blog: the blog id the
    request names, whose canonical form (a domain address resolves to its own id once) rides in every saved state with
    carry — what else must survive a handle or an --out page (a category number); `capped` joins them once Naver's
    ceiling ended the listing, so a continuation that shows the last waiting records still says why it ended. order,
    show, end_covers_window: see read_list. empty: what no records means here, when Naver's silence needs saying.
    """
    client = connection.client
    saved = resumed(state, out)
    carried = dict(carry or {})
    if saved.get('capped'):
        carried['capped'] = True
    restricted = []

    def fetched(number):
        try:
            got = source(number)
        except SnsError as error:
            if error.reason == 'restricted' and getattr(error, 'records', None) is not None:
                restricted.append(error)  # what arrived beside a restriction is shown, and the listing ends there
                return web.Fetched(items=error.records, raw_count=len(error.records), ends=True)
            raise
        if blog:
            carried['blog_id'] = client.canonical.get(blog, blog)
        return got

    inner = web.numbered(web.policy(op), fetched)

    def fetch(cursor):
        page = inner(cursor)
        if page.stop == 'server_capped':
            carried['capped'] = True
        return page

    if out is None:
        account.adopt_hint(connection, state)
    result = reading.read_list(connection, state, out, order=order, fetch=fetch, command=command, target=target,
                               identity=identity, words=words, extra=carried, show=show,
                               end_covers_window=end_covers_window)
    if result.get('failure') is None:
        if restricted:
            result['failure'] = restricted[0]
        elif saved.get('capped') and result.get('stop_reason') == 'exhausted':
            result['stop_reason'] = 'server_capped'
        elif empty and not result.get('results') and result.get('stop_reason') == 'exhausted' \
                and 'continuation' not in result and not (out is not None and out.count):
            result['failure'] = SnsError('empty', empty, EMPTY_FIX)
    return result
