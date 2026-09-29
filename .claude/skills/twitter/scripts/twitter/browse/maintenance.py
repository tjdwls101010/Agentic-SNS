"""Session diagnosis and explicit registry refresh; the caller writes their one-line summaries."""
import time
from ..account.budget import Budget
from ..account.state import account_lock, cache_dir, read_state, write_state, unblock
from ..continuation import CursorStore
from ..dates import moment
from ..errors import TwitterError
from ..graphql.protocol.refresh import refresh as publish
from ..graphql.protocol.transport import Transport
from ..graphql.responses.records import build_user


def doctor(args):
    """Sweep expired continuations; report a block without a request; otherwise re-read the cookie against the cached viewer and ask X who it is."""
    store = CursorStore()
    store.sweep()
    if args.unblock:
        unblock()
    if block := read_state('budget.json').get('block'):
        result = dict(ok=False, results=[], stop_reason='blocked', error=block['reason'], message='X requests are blocked.',
                      fix='Check x.com in Aside, then run doctor --unblock.', viewer='unverified (blocked)',
                      continuations=store.sweep(), **ages(readable('registry.json').get('refreshed_at')), code=5, summary=None)
        return dict(result, budget=Budget(10).summary(), fetched_bytes=0, warnings=[])
    transport = Transport(10)
    cached = read_state('session.json').get('viewer_id')
    session = transport.session(force=True)
    user = build_user(transport.query('Viewer')).to_dict()
    if user['id'] != session['viewer_id']:
        raise TwitterError(2, f'X answered as account {user["id"]}, but the browser cookie says {session["viewer_id"]}; the account changed during the check.',
                           'Run doctor again once the browser shows the account you mean.', 'viewer_changed')
    with account_lock():
        session = read_state('session.json')
        if session.get('viewer_id') != user['id']:
            raise TwitterError(2, 'Another run changed the cached account while doctor was checking.', 'Run doctor again once the other run has finished.', 'viewer_changed')
        session['viewer_handle'] = user['screen_name']
        write_state('session.json', session)
    result = dict(ok=True, results=[user], stop_reason='not_paginable', viewer_id=session['viewer_id'],
                  viewer=('viewer changed' if transport.changed_viewer else 'matches cache' if cached else 'no cached viewer'),
                  viewer_changed=transport.changed_viewer, continuations=store.sweep(), **ages(transport.registry.refreshed_at),
                  code=0, summary=None)
    return spent(result, transport)


def ages(refreshed):
    return dict(registry_age_days=days(refreshed), txid_age_days=days(readable('txid.json').get('fetched_at')), cache=str(cache_dir()))


def readable(name):
    """A cache file's state, or nothing when it is unreadable; diagnosis reports around a damaged file rather than stopping."""
    try:
        state = read_state(name)
    except TwitterError:
        return {}
    return state if isinstance(state, dict) else {}


def days(value):
    value = moment(value)
    return round((time.time() - value) / 86400) if value else None


def refresh(args):
    transport = Transport(10)
    return spent(publish(transport), transport)


def spent(result, transport):
    result.update(budget=transport.budget.summary(), fetched_bytes=transport.fetched_bytes, warnings=transport.warnings)
    return result
