"""Visible profile About fields: the overview and each of its collections."""
import base64
from datetime import datetime

from facebook.errors import FacebookError
from facebook.graphql.records import about as _about
from facebook.graphql.registry import ABOUT_SECTION_ID
from facebook.graphql.resolve import resolve_profile_id
from facebook.reading.comments import _failure


def about(args, transport, state, commit):
    profile_id = resolve_profile_id(transport, args.target)
    variables = {'pageID': profile_id, 'userID': profile_id,
                 'sectionToken': base64.b64encode(f'app_section:{profile_id}:{ABOUT_SECTION_ID}'.encode()).decode()}
    failures = []
    overview = transport.query('about', {**variables, 'collectionToken': None}, referer=args.target)
    collections = _about.iter_collections([overview])
    bodies, names = [overview], [None]
    error = None
    for collection in collections:
        try:
            raw = transport.query('about', {**variables, 'collectionToken': collection['id']}, referer=args.target)
        except FacebookError as exc:
            failures.append({'section': collection['name'], 'code': exc.code, 'message': exc.message})
            error = exc
            if exc.code in (4, 5, 8):
                break
        else:
            bodies.append(raw)
            names.append(collection['name'])
    fields = [r.to_dict() for r in _about.build_fields(
        bodies, profile_id=profile_id, collection_names=names, captured_at=datetime.now().astimezone())
        if not args.section or r.section == args.section]
    result = {'ok': True, 'results': fields[:args.limit] if args.limit and not args.out else fields,
              'stop_reason': 'limit_reached' if args.limit and len(fields) > args.limit else 'exhausted'}
    if failures:
        result['failed_sections'] = failures
        _failure(result, error)
    if commit and not failures:
        # About has no stable field id: commit the whole logical page only when complete.
        commit(result['results'], {'exhausted': True}, 'exhausted')
    return result
