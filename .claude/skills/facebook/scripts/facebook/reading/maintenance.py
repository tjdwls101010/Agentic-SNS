"""Local schema and browser/registry diagnostics."""
from datetime import date

from facebook.collect import describe_out
from facebook.errors import FacebookError
from facebook.graphql.records import SCHEMAS
from facebook.outcome import describe_result
from facebook.graphql.refresh import refresh
from facebook.graphql.registry import load_registry


def schema(name, exit_codes):
    """One object's schema, or every object named with one line."""
    documents = {'result': describe_result(exit_codes), 'out': describe_out(), **SCHEMAS}
    if name:
        return {'results': [documents[name]], 'stop_reason': 'complete'}
    return {'results': [{'object': key, 'description': doc['description']} for key, doc in documents.items()],
            'stop_reason': 'complete'}


def run(args, transport):
    if args.command == 'refresh':
        result = refresh(transport, capture=bool(args.capture), post=args.capture)
        required = set(load_registry()['queries'])
        if not args.capture:
            required -= {'comments', 'comments_page', 'replies'}
        missing = required - set(result['updated'])
        reading = {'results': [], 'stop_reason': 'complete', 'partial': bool(result['updated']), 'details': result}
        if missing:
            reading['failure'] = FacebookError(6, 'Some query candidates were not verified.',
                                               'Read missing and failed; only verified updates were saved. '
                                               'Use --capture POST_URL for comment queries.')
        return reading
    registry = load_registry()
    captured = registry.get('captured_at')
    try:
        age = (date.today() - date.fromisoformat(captured[:10])).days
    except (ValueError, TypeError):
        age = None
    return {'results': [{'account_id': transport.account_id, 'aside': 'available', 'login': 'ready',
                         'blocked': False, 'registry_age_days': age, 'queries': len(registry['queries'])}],
            'stop_reason': 'ready'}
