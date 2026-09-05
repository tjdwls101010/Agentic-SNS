"""Local schema, session diagnosis and explicit registry refresh."""
import time
from ._blocked import account_lock, read_state, write_state, unblock
from ._transport import Transport
from ._entities import build_user
from ._schema import schema


def run(args):
    if args.command == 'schema':
        return schema()
    transport = Transport(10)
    if args.command == 'refresh':
        from ._bundles import refresh
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
                      txid_age_days=txid_age, viewer_changed=transport.changed_viewer, code=0)
        result['summary'] = (f'Aside u0 · @{user["screen_name"]} · viewer {user["id"]} · unblocked · '
                             f'registry age {registry_age if registry_age is not None else "bundled"} days · txid age {txid_age} days')
    result.update(budget=transport.budget.summary(), fetched_bytes=transport.fetched_bytes, warnings=transport.warnings)
    if args.command == 'doctor':
        bucket = result['budget']['operations'].get('Viewer', {})
        result['summary'] += f' · budget Viewer {bucket.get("remaining", "?")} of {bucket.get("limit", "?")} · window {result["budget"]["window"]}/200'
    return result
