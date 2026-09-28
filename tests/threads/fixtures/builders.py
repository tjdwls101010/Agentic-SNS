"""Synthetic Threads responses for the fake Aside, and fixture sets built from them.

Nothing here imports the skill: a fixture is what Threads would send, written from the shapes observed on the real site,
so a test that passes agrees with Threads rather than with the code under test. `routes.ndjson` holds the base set;
`Routes` copies it, lets a test replace or add rows, and writes the copy the fake reads through THREADS_FIXTURES.
"""
import json
from pathlib import Path

BASE = Path(__file__).with_name('routes.ndjson')
GRAPHQL = 'https://www.threads.com/graphql/query'
USER = {'pk': '42', 'username': 'fixture_user', 'full_name': 'Synthetic Person'}
OTHER = {'pk': '43', 'username': 'fixture__other', 'full_name': 'Synthetic Other'}
PROFILE = {'pk': '42', 'username': 'fixture_user', 'full_name': 'Synthetic Person', 'follower_count': 1000}


def raw_post(pk='1', **extra):
    return {'pk': pk, 'code': 'FIX_' + pk, 'taken_at': 1788566400,
            'user': {'pk': '42', 'username': 'fixture_user', 'full_name': 'Synthetic Person'},
            'caption': {'text': 'A synthetic post'}, **extra}


def listed_post(pk, taken_at=None, **extra):
    """A post as feed and profile listings carry it: numbered text, one second older per number."""
    fields = {'caption': {'text': f'Synthetic post {pk}'}, 'text_post_app_info': {'direct_reply_count': 12}, **extra}
    return raw_post(str(pk), taken_at=1788566400 - int(pk) if taken_at is None else taken_at, **fields)


def page_info(cursor=None):
    return {'end_cursor': cursor, 'has_next_page': cursor is not None}


def feed(posts, cursor=None):
    return {'data': {'feedData': {'edges': [{'node': {'text_post_app_thread': {'thread_items': [{'post': p}]}}}
                                            for p in posts], 'page_info': page_info(cursor)}}}


def tab(posts, cursor=None, groups=None):
    """A profile tab page; `groups` gives several posts per edge (a thread and its continuations)."""
    groups = groups if groups is not None else [[p] for p in posts]
    return {'data': {'mediaData': {'edges': [{'node': {'thread_items': [{'post': p} for p in group]}}
                                             for group in groups], 'page_info': page_info(cursor)}}}


def users(key, people, cursor=None, counts=None, root='user'):
    connection = {'edges': [{'node': p} for p in people]}
    if cursor is not False:
        connection['page_info'] = page_info(cursor)
    data = {root: {key: connection}}
    if counts is not None:
        data['counts'] = counts
    return {'data': data}


def person(pk, username='fixture_user', **extra):
    return {'pk': str(pk), 'username': username, **extra}


def envelope(body, status=200, url=GRAPHQL):
    return {'status': status, 'url': url, 'body': body if isinstance(body, str) else json.dumps(body)}


def route(items, url='https://www.threads.com/', viewer='fixture_viewer', actor='100'):
    """A logged-in route: session fields and Relay items (preloaders and __bbox results) in one JSON script."""
    document = {'DTSGInitialData': [], 'csrf_token': 'synthetic-csrf', 'NON_FACEBOOK_USER_ID': actor,
                'username': viewer, 'items': items}
    return envelope('<html><script type="application/json">' + json.dumps(document) + '</script></html>', url=url)


def preloader(name, **variables):
    return {'preloaderID': f'adp_{name}RelayPreloader_hash', 'queryID': '1001', 'variables': variables}


def bbox(data):
    return {'queryName': None, '__bbox': {'result': {'data': data}}}


ERRORS = {
    'checkpoint': envelope({'errors': [{'message': 'checkpoint_required'}]}),
    'rate_limit': envelope({}, status=429),
    'login': envelope('', status=302, url='https://www.threads.com/accounts/login/'),
    'rotated': envelope({'data': None, 'errors': [{'message': 'execution error', 'severity': 'CRITICAL'}]}),
    'http': envelope('bad gateway', status=502),
}


class Routes:
    """A private copy of the base fixture set; rows sharing a key answer successive calls in order."""

    def __init__(self, directory):
        self.path = Path(directory) / 'routes.ndjson'
        self.rows = [json.loads(line) for line in BASE.read_text().splitlines()]

    def body(self, key):
        return next(row['envelope']['body'] for row in self.rows if row['key'] == key)

    def set(self, key, *envelopes):
        """Replace every row with this key; several envelopes answer successive calls."""
        self.rows = [row for row in self.rows if row['key'] != key]
        return self.add(key, *envelopes)

    def add(self, key, *envelopes):
        self.rows += [{'key': key, 'envelope': e} for e in envelopes]
        return self

    def edit(self, key, change):
        """Rewrite the body text of every row with this key."""
        for row in self.rows:
            if row['key'] == key:
                row['envelope'] = dict(row['envelope'], body=change(row['envelope']['body']))
        return self

    def copy(self, key, new):
        """Serve `new` exactly as `key`, replacing whatever `new` answered before."""
        copies = [dict(row, key=new) for row in self.rows if row['key'] == key]
        self.rows = [row for row in self.rows if row['key'] != new] + copies
        return self

    def write(self):
        self.path.write_text(''.join(json.dumps(row) + '\n' for row in self.rows))
        return self.path


def collections(routes):
    """Search, account search and the viewer's collections, shaped like the profile tab's posts."""
    base = json.loads(routes.body('BarcelonaProfileThreadsTabDirectQuery'))['data']['mediaData']
    search = {'edges': [{'node': {'thread': edge['node']}} for edge in base['edges']], 'page_info': base['page_info']}
    routes.set('BarcelonaSearchResultsQuery', envelope({'data': {'searchResults': search}}))
    routes.set('useBarcelonaAccountSearchGraphQLDataSourceQuery', envelope({
        'data': {'xdt_api__v1__users__search_connection': {'edges': [
            {'node': {'pk': str(i), 'username': 'fixture_user'}} for i in (42, 43, 44)]}},
        'errors': [{'message': 'field_exception', 'path': ['users', 4]}]}))
    routes.set('BarcelonaLikedPageViewerQuery', envelope({'data': {'xdt_text_app_viewer': {'liked_media': base}}}))
    routes.set('BarcelonaSavedPageViewerQuery', envelope({'data': {'xdt_text_app_viewer': {}}}))
    return routes


def null_profile(routes, profile=None):
    """The profile route with a null SSR profile, and the profile query that fills it in."""
    routes.edit('/@fixture_user', lambda body: body.replace(json.dumps({'user': PROFILE}), json.dumps({'user': None})))
    routes.set('BarcelonaProfilePageDirectQuery', envelope({'data': {'user': profile or PROFILE}}))
    return routes
