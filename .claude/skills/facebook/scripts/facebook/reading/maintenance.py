"""Local schema and browser/registry diagnostics."""
from datetime import date

from facebook.graphql.records import SCHEMAS
from facebook.graphql.refresh import refresh
from facebook.graphql.registry import load_registry


def schema(name=None):
    return {'ok': True, 'results': [SCHEMAS[name]] if name in SCHEMAS else list(SCHEMAS.values()),
            'stop_reason': 'complete'}


def run(args, transport):
    if args.command == 'refresh':
        result = refresh(transport, capture=bool(args.capture), post=args.capture)
        required = set(load_registry()['queries'])
        if not args.capture:
            required -= {'comments', 'comments_page', 'replies'}
        missing = required - set(result['updated'])
        result.update(ok=not missing, results=[], request_count=transport.request_count,
                      stop_reason='query_failure' if missing else 'exhausted')
        if missing:
            result.update(code=8, error='refresh_incomplete', message='Some query candidates were not verified.',
                          fix='Read missing/failed; only verified updates were saved. Use --capture POST_URL for comment queries.')
        return result
    registry = load_registry()
    captured = registry.get('captured_at')
    try:
        age = (date.today() - date.fromisoformat(captured[:10])).days
    except (ValueError, TypeError):
        age = None
    return {'ok': True, 'results': [{'account_id': transport.account_id, 'aside': 'available',
                                    'login': 'ready', 'blocked': False, 'registry_age_days': age,
                                    'queries': len(registry['queries'])}],
            'stop_reason': 'ready', 'request_count': transport.request_count}
