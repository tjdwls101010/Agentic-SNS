"""Diagnostics do not persist session credentials."""
from datetime import date

from ._transport import Transport
from ._blocked import cache_dir


def run(args):
    if args.command == 'schema':
        from ._schema import schema
        return schema()
    transport = Transport(60 if args.command == 'refresh' and args.capture else 40 if args.command == 'refresh' else 10)
    if args.command == 'refresh':
        from ._refresh import refresh
        return refresh(transport, args)
    transport.page('/', unblock=args.unblock)
    dates = [s['captured_at'] for s in transport.registry.operations.values()]
    return {'ok': True, 'viewer': transport.session.viewer, 'blocked': False,
            'capture_cleanup_uncertain': (cache_dir() / 'capture-active.json').exists(),
            'registry_age_days': (date.today() - date.fromisoformat(min(dates)[:10])).days,
            'budget': transport.budget.snapshot(), 'fetched_bytes': transport.fetched_bytes}
