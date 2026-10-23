"""Scenes of the X tests: a logged-in tab the skill already knows, a tab being opened, an answer of the page's query
function, the real cli.py run against the scripted fake Aside, and protection state stood up through its own interface.

Snippet operations in the fake Aside are named `x.<snippet>`: x.state, x.query, x.modules, x.arm (as `load:x.arm`), and
the core's x.close / x.blank. The Aside account is the fake's default, u0.
"""
import json
import time

from sns import protection
from sns.clock import Deadline
from sns.session import Session
from sns.x import PLATFORM
from tests.sns.support.cli import command_of as _command_of, run_cli

START = 'https://x.com/i/xskill'
ACCOUNT = '1000000099'
ASIDE = 'u0'
ENVIRONMENT = {'TZ': 'UTC', 'SNS_IDLE_SECONDS': 'off'}


def command_of(line):
    """The arguments of a printed more: command line, parsed the way a shell would, with the platform word kept."""
    return _command_of(line)


def run(browser, *args, env=None):
    """Run the real cli.py as `cli.py x <args>` with the fake Aside; returns (exit code, stdout, stderr)."""
    done = run_cli('x', *args, browser=browser, env={**ENVIRONMENT, **(env or {})})
    return done.returncode, done.stdout, done.stderr


def rerun(browser, line, env=None):
    """Run the command a more: or resume: line names, as it names it (it already starts with the platform word)."""
    browser.write()
    done = run_cli(*command_of(line), browser=browser, env={**ENVIRONMENT, **(env or {})})
    return done.returncode, done.stdout, done.stderr


def state(**extra):
    """What the state page function reports for a logged-in tab on the start screen."""
    return {'location': START, 'user_id': ACCOUNT, 'language': 'en', 'app': True, 'store': True, 'switches': 1442,
            'ct0': True, 'installed_at': 300, 'ready_at_install': 'loading', 'app_at_install': False, 'resources': 0,
            'ours': 0, 'statuses': [], 'signals': [], 'moved': None, **extra}


def known_tab(browser, target='T1', **extra):
    """A dedicated tab the skill already knows and that is still open."""
    browser.tab(target, url=START)
    Session('x', ASIDE).set_tab(target)
    browser.respond('x.state', state(**extra))
    return browser


def opening(browser, target='NEW1', resources=13, early=True, quiet=True, **extra):
    """Aside opens a new tab; it loads x.com with the kit installed early (or late) and is logged in. quiet: the two
    looks after the app is ready that see nothing new (the load has settled)."""
    browser.respond('opener', {'tabs': [target]})
    browser.respond('load:x.arm', {'installed_at': 300 if early else 4000, 'location': START,
                                   'ready_at_install': 'loading' if early else 'complete', 'app_at_install': not early})
    browser.respond('x.state', state(resources=resources, **extra))
    if quiet and extra.get('user_id', ACCOUNT) and not extra.get('signals'):
        browser.respond('x.state', state(**extra)).respond('x.state', state(**extra))
    return browser


def query_result(body, status=200, headers=None, resources=0, ours=1, **extra):
    return {'status': status, 'body': body if isinstance(body, str) else json.dumps(body), 'headers': headers or {},
            'used': {'source': 'live', 'query_id': 'SYNTHq', 'features': []}, 'nonce': 'n1', 'explicit': 1,
            'resources': resources, 'ours': ours, 'statuses': [200] * resources, 'signals': [], 'location': START,
            'moved': None, **extra}


MODULES = {'live': {'Viewer': {'query_id': 'SYNTHqVW01', 'type': 'query', 'features': 0}}, 'modules': 3702,
           'generator': True, 'bearer': True, 'resources': 0, 'ours': 0, 'statuses': [], 'signals': [],
           'location': START, 'moved': None}


def queries(browser):
    """The query calls the page function was asked to make, in order."""
    return [c for c in browser.calls() if c['op'] == 'x.query']


# --- protection state, through its interface -------------------------------------------------------------------------

def guard(seconds=100):
    return protection.open('x', ASIDE, PLATFORM.policy, Deadline(seconds), title=PLATFORM.title, site=PLATFORM.site)


def stand_block(reason='account_locked', viewer=ACCOUNT):
    """A person block of X, as an earlier invocation recorded it."""
    with guard().request() as slot:
        slot.block(reason, viewer=viewer)


def stand_limit(operation, remaining=0, limit=500, seconds=300):
    """A known window of one operation, as an earlier response's headers left it."""
    from sns.limits import Fact
    with guard().request(scope=operation) as slot:
        slot.fact(operation, Fact(limit, remaining, time.time() + seconds))


def limits():
    """The windows protection knows now: {operation: {status, limit, remaining, reset_at, …}}."""
    return guard().state()['scopes']


def state_of():
    return guard().state()
