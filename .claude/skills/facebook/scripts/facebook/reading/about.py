"""Visible profile About fields: the overview and each of its collections."""
import base64
from datetime import datetime

from facebook.errors import FacebookError
from facebook.graphql.records import about as _about
from facebook.graphql.registry import ABOUT_SECTION_ID
from facebook.graphql.resolve import resolve_profile_id


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
    result = {'results': fields, 'stop_reason': 'exhausted'}
    if failures:
        result['details'] = {'failed_sections': failures}
        result['coverage'] = [f'collection {f["section"]}: not read — fields there are missing' for f in failures]
        result['failure'] = error
    return result
