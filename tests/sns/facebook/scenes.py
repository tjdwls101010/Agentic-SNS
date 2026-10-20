"""Scenes of the Facebook tests: a logged-in tab the skill already knows, a tab being opened, an answer of the page's
query function, the real cli.py run against the scripted fake Aside, and protection state stood up through its own
interface.

Snippet operations in the fake Aside are named `facebook.<snippet>`: facebook.state, facebook.query, facebook.page,
facebook.route, facebook.modules, and the core's facebook.blank. A tab is opened with `aside <url>` (the fake's `open`),
which gives the next id of the scenario's open_ids. The Aside account is the fake's default, u0.
"""
import json
from datetime import datetime

from sns import protection
from sns.clock import Deadline
from sns.facebook import PLATFORM
from sns.session import Session
from tests.sns.support.cli import command_of as _command_of, run_cli

HOME = 'https://www.facebook.com/'
ACCOUNT = '1000123'
ASIDE = 'u0'
ENVIRONMENT = {'TZ': 'UTC', 'SNS_IDLE_SECONDS': 'off'}
GRAPHQL = 'https://www.facebook.com/api/graphql/'


def command_of(line):
    """The arguments of a printed more: command line, parsed the way a shell would, with the platform word kept."""
    return _command_of(line)


def run(browser, *args, env=None):
    """Run the real cli.py as `cli.py facebook <args>` with the fake Aside; returns (exit code, stdout, stderr)."""
    done = run_cli('facebook', *args, browser=browser, env={**ENVIRONMENT, **(env or {})})
    return done.returncode, done.stdout, done.stderr


def rerun(browser, line, *extra, env=None):
    """Run the command a more: or resume: line names, as it names it (it already starts with the platform word)."""
    browser.write()
    done = run_cli(*command_of(line), *extra, browser=browser, env={**ENVIRONMENT, **(env or {})})
    return done.returncode, done.stdout, done.stderr


def state(**extra):
    """What the state page function reports for a logged-in tab on the home screen."""
    return {'location': HOME, 'user_id': ACCOUNT, 'runtime': True, 'resources': 0, 'statuses': [], 'unwatched': [],
            'limited': False, **extra}


def known_tab(browser, target='T1', **extra):
    """A dedicated tab the skill already knows and that is still open."""
    browser.tab(target, url=HOME)
    Session('facebook', ASIDE).set_tab(target)
    browser.respond('facebook.state', state(**extra))
    return browser


def look(browser, **extra):
    """The state look a later command makes of the known tab before it sends anything."""
    return browser.respond('facebook.state', state(**extra))


def opening(browser, target='T9', resources=29, **extra):
    """Aside opens a new tab at the home screen (`aside <url>`); its first look is logged in (and the page made
    `resources` requests while it loaded)."""
    browser.flag(open_ids=[target])
    browser.respond('facebook.state', state(resources=resources, **extra))
    return browser


def query_result(body, status=200, source='live', doc_id='111', resources=1, **extra):
    return {'status': status, 'url': GRAPHQL, 'body': body,
            'used': {'source': source, 'doc_id': doc_id,
                     'flags': {'__relay_internal__pv__Xrelayprovider': True} if source == 'live' else None},
            'explicit': 1, 'resources': resources, 'statuses': [200] * resources, 'unwatched': [], 'limited': False,
            'user_id': ACCOUNT, **extra}


def page_result(url, body, status=200, **extra):
    """An answer of the page function (one GET of a facebook.com page)."""
    return {'status': status, 'url': url, 'body': body, 'explicit': 1, 'resources': 1, 'statuses': [200],
            'unwatched': [], 'limited': False, 'user_id': ACCOUNT, **extra}


def queries(browser):
    """The query calls the page function was asked to make, in order."""
    return [c for c in browser.calls() if c['op'] == 'facebook.query']


def sent(browser):
    """The names of the queries sent, in order."""
    return [c['args']['name'] for c in queries(browser)]


# --- records a scripted answer carries --------------------------------------------------------------------------------

def story(identity, created='2026-09-12T03:00:00Z', text=None, **flags):
    """A minimal feed story for a scripted response; created is an ISO time or None."""
    node = {'feedback': {'id': identity}, 'actors': [{'id': '9' + identity, 'name': 'Author ' + identity,
                                                      'url': 'https://www.facebook.com/author.' + identity.lower()}],
            'message': {'text': text if text is not None else f'post {identity}'},
            'permalink_url': f'https://www.facebook.com/author.{identity.lower()}/posts/{identity}'}
    if created:
        node['creation_time'] = int(datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp())
    if flags.get('sponsored'):
        node['sponsored_data'] = {'ad_id': '1'}
    if flags.get('pinned'):
        node['is_pinned'] = True
    return node


def graphql_body(connection_path, stories, has_next=True, cursor='CUR1'):
    """A GraphQL body with one connection at connection_path (e.g. ['viewer', 'news_feed'])."""
    connection = {'edges': [{'node': s} for s in stories],
                  'page_info': {'has_next_page': has_next, 'end_cursor': cursor if has_next else None}}
    data = connection
    for key in reversed(connection_path):
        data = {key: data}
    return json.dumps({'data': data})


# --- protection state, through its interface --------------------------------------------------------------------------

def guard(seconds=100):
    return protection.open('facebook', ASIDE, PLATFORM.policy, Deadline(seconds), title=PLATFORM.title,
                           site=PLATFORM.site)


def stand_block(reason='checkpoint', viewer=ACCOUNT):
    """A person block of Facebook, as an earlier invocation recorded it."""
    with guard().request() as slot:
        slot.block(reason, viewer=viewer)


def stand_hold(seconds=900):
    """An account hold (a 429), as an earlier invocation recorded it."""
    import time
    with guard().request() as slot:
        slot.hold(until=time.time() + seconds)


def state_of():
    return guard().state()


def stand_block_and_hold(seconds=900):
    """A person block and an account hold together (neither lifts the other), folded in as the legacy converter does."""
    import time
    guard().merge(person={'reason': 'checkpoint', 'at': time.time(), 'viewer': ACCOUNT},
                  hold={'until': time.time() + seconds, 'at': time.time()}, source={'path': 'test', 'sha256': 'x'})
