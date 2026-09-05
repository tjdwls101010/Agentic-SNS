"""Local schema and browser/registry diagnostics."""
from datetime import date

from _registry import load_registry


def schema():
    import _post
    import _comment
    import _entity
    import _about
    return {'ok': True, 'results': [module.json_schema() for module in (_post, _comment, _entity, _about)],
            'stop_reason': 'complete'}


def run(args, transport):
    if args.command == 'refresh':
        from _refresh import refresh
        result = refresh(transport, capture=args.capture, post=args.post)
        required = set(load_registry()['queries'])
        if not args.capture:
            required -= {'comments', 'comments_page', 'replies'}
        missing = required - set(result['updated'])
        result.update(ok=not missing, results=[], request_count=transport.request_count,
                      stop_reason='query_failure' if missing else 'exhausted')
        if missing:
            result.update(code=8, error='refresh_incomplete', message='Some query candidates were not verified.',
                          fix='Read missing/failed; only verified updates were saved. Use --capture --post URL for comment queries.')
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
