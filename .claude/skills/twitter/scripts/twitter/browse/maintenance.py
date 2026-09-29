"""Session diagnosis and explicit registry refresh; the caller writes their one-line summaries."""
import time
from ..account.state import account_lock, cache_dir, read_state, write_state, unblock
from ..continuation import CursorStore
from ..graphql.protocol.refresh import refresh as publish
from ..graphql.protocol.transport import Transport
from ..graphql.responses.records import build_user


def doctor(args):
    """Report a block without a request; otherwise re-read the cookie against the cached viewer and ask X who it is."""
    transport = Transport(10)
    if args.unblock:
        unblock()
    refreshed = transport.registry.refreshed_at
    material = read_state('txid.json')
    state = dict(registry_age_days=days(refreshed), txid_age_days=days(material.get('fetched_at')), cache=str(cache_dir()))
    if block := read_state('budget.json').get('block'):
        result = dict(ok=False, results=[], stop_reason='blocked', error=block['reason'], message='X requests are blocked.',
                      fix='Check x.com in Aside, then run doctor --unblock.', viewer='unverified (blocked)',
                      continuations=CursorStore().sweep(), **state, code=5, summary=None)
        return spent(result, transport)
    cached = read_state('session.json').get('viewer_id')
    session = transport.session(force=True)
    user = build_user(transport.query('Viewer')).to_dict()
    with account_lock():
        session = read_state('session.json')
        session['viewer_handle'] = user['screen_name']
        write_state('session.json', session)
    result = dict(ok=True, results=[user], stop_reason='not_paginable', viewer_id=session['viewer_id'],
                  viewer=('viewer changed' if transport.changed_viewer else 'matches cache' if cached else 'no cached viewer'),
                  viewer_changed=transport.changed_viewer, continuations=CursorStore().sweep(), **state, code=0, summary=None)
    return spent(result, transport)


def days(moment):
    return round((time.time() - moment) / 86400) if moment else None


def refresh(args):
    transport = Transport(10)
    return spent(publish(transport), transport)


def spent(result, transport):
    result.update(budget=transport.budget.summary(), fetched_bytes=transport.fetched_bytes, warnings=transport.warnings)
    return result
