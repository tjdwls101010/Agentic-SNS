"""Session diagnosis and explicit registry refresh; the caller writes their one-line summaries."""
import time
from ..account.state import account_lock, read_state, write_state, unblock
from ..graphql.protocol.transport import Transport
from ..graphql.responses.records import build_user


def run(args):
    transport = Transport(10)
    if args.command == 'refresh':
        from ..graphql.protocol.refresh import refresh
        result = refresh(transport)
    else:
        if args.unblock:
            unblock()
        session = transport.session(personal=True)
        user = build_user(transport.query('Viewer')).to_dict()
        with account_lock():
            session = read_state('session.json')
            session['viewer_handle'] = user['screen_name']
            write_state('session.json', session)
        material = read_state('txid.json')
        refreshed = transport.registry.refreshed_at
        registry_age = (time.time() - refreshed) / 86400 if refreshed else None
        txid_age = (time.time() - material['fetched_at']) / 86400 if material.get('fetched_at') else None
        result = dict(ok=True, results=[user], stop_reason='not_paginable', registry_age_days=registry_age,
                      txid_age_days=txid_age, viewer_changed=transport.changed_viewer, code=0, summary=None)
    result.update(budget=transport.budget.summary(), fetched_bytes=transport.fetched_bytes, warnings=transport.warnings)
    return result
