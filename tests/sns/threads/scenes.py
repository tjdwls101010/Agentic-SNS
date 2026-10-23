"""Scenes of the Threads tests: a logged-in tab the skill already knows, a tab being opened, an answer of the page's
query function, the real cli.py run against the scripted fake Aside, and protection state stood up through its own
interface.

Snippet operations in the fake Aside are named `threads.<snippet>`: threads.state, threads.query, threads.page,
threads.modules, threads.navigate, and the core's threads.blank. A new tab comes from the fake's `open_ids`. The Aside
account is the fake's default, u0.
"""
import json
from datetime import datetime

from sns import protection
from sns.clock import Deadline
from sns.session import Session
from sns.threads import PLATFORM
from tests.sns.support.cli import command_of as _command_of, run_cli

START = 'https://www.threads.com/search'
ACCOUNT = '1000000009'
ASIDE = 'u0'
ENVIRONMENT = {'TZ': 'UTC', 'SNS_IDLE_SECONDS': 'off'}
LOGGED_IN_DOCUMENT = ('<script>{"csrf_token":"tok","NON_FACEBOOK_USER_ID":"' + ACCOUNT +
                      '","username":"example.viewer","__bbox":{}}</script>')


def command_of(line):
    """The arguments of a printed more: command line, parsed the way a shell would, with the platform word kept."""
    return _command_of(line)


def run(browser, *args, env=None):
    """Run the real cli.py as `cli.py threads <args>` with the fake Aside; returns (exit code, stdout, stderr)."""
    done = run_cli('threads', *args, browser=browser, env={**ENVIRONMENT, **(env or {})})
    return done.returncode, done.stdout, done.stderr


def rerun(browser, line, *extra, env=None):
    """Run the command a more: or resume: line names, as it names it (it already starts with the platform word)."""
    browser.write()
    done = run_cli(*command_of(line), *extra, browser=browser, env={**ENVIRONMENT, **(env or {})})
    return done.returncode, done.stdout, done.stderr


def state(**extra):
    """What the state page function reports for a logged-in tab on the start screen."""
    return {'location': START, 'user_id': ACCOUNT, 'app_id': '999000111222333', 'runtime': True, 'resources': 0,
            'statuses': [], 'signals': [], 'document': None, **extra}


def known_tab(browser, target='T1', **extra):
    """A dedicated tab the skill already knows and that is still open."""
    browser.tab(target, url=START)
    Session('threads', ASIDE).set_tab(target)
    browser.respond('threads.state', state(**extra))
    return browser


def opening(browser, target='NEW1', resources=33, **extra):
    """Aside opens a new tab on the start screen, which loads logged in, then goes quiet."""
    browser.flag(open_ids=[target])
    browser.respond('threads.state', state(resources=resources, document=LOGGED_IN_DOCUMENT, **extra))
    browser.respond('threads.state', state(resources=0, **{k: v for k, v in extra.items() if k != 'resources'}))
    return browser


def query_result(body, status=200, source='live', doc_id='111', resources=1, **extra):
    return {'status': status, 'url': 'https://www.threads.com/api/graphql/',
            'body': body if isinstance(body, str) else json.dumps(body),
            'used': {'source': source, 'doc_id': doc_id, 'flags': {'__relay_internal__pv__BarcelonaIsLoggedInrelayprovider': True}
                     if source == 'live' else None}, 'explicit': 1, 'resources': resources,
            'statuses': [200] * resources, 'signals': [], 'location': START, 'user_id': ACCOUNT, **extra}


AUTHOR = {'pk': '1000000001', 'username': 'example.author'}


def pk(identity):
    return str(3000000000000000000 + sum(ord(c) * 131 ** i for i, c in enumerate(identity)) % 10 ** 15)


def post(identity, created_at=None, pinned=False, unavailable=False, author=AUTHOR, **info):
    if unavailable:
        return {'pk': pk(identity), 'is_post_unavailable': True}
    raw = {'pk': pk(identity), 'code': 'C' + identity.replace('-', ''), 'user': author, 'caption': {'text': 'post ' + identity},
           'text_post_app_info': dict(info)}
    if created_at:
        raw['taken_at'] = int(datetime.fromisoformat(created_at.replace('Z', '+00:00')).timestamp())
    if pinned:
        raw['text_post_app_info']['pinned_post_info'] = {'is_pinned_to_profile': True}
    return raw


def feed_body(groups, has_next, cursor):
    edges = [{'node': {'text_post_app_thread': {'thread_items': [{'post': item} for item in group]}}} for group in groups]
    return {'data': {'feedData': {'edges': edges, 'page_info': {'has_next_page': has_next, 'end_cursor': cursor}}}}


def queries(browser):
    """The query calls the page function was asked to make, in order."""
    return [c for c in browser.calls() if c['op'] == 'threads.query']


# --- protection state, through its interface -------------------------------------------------------------------------

def guard(seconds=100):
    return protection.open('threads', ASIDE, PLATFORM.policy, Deadline(seconds), title=PLATFORM.title,
                           site=PLATFORM.site)


def stand_block(reason='checkpoint', viewer=ACCOUNT):
    """A person block of Threads, as an earlier invocation recorded it."""
    with guard().request() as slot:
        slot.block(reason, viewer=viewer)


def stand_hold(seconds=1800):
    """A 429 hold of the account, as an earlier invocation recorded it."""
    import time
    with guard().request() as slot:
        slot.hold(until=time.time() + seconds)


def state_of():
    return guard().state()
