"""Visible profile About fields: the overview and each of its collections."""
import base64
from datetime import datetime

from facebook.errors import FacebookError
from facebook.graphql import records
from facebook.graphql.registry import ABOUT_SECTION_ID
from facebook.graphql.resolve import resolve_profile_id
from facebook.outcome import FIXES


def about(args, transport, state, commit):
    """The overview, then each collection in order; --section stops at the first place that shows it."""
    profile_id = resolve_profile_id(transport, args.target)
    variables = {'pageID': profile_id, 'userID': profile_id,
                 'sectionToken': base64.b64encode(f'app_section:{profile_id}:{ABOUT_SECTION_ID}'.encode()).decode()}
    setup = transport.request_count
    overview = transport.query('about', {**variables, 'collectionToken': None}, referer=args.target)
    collections = records.about_collections(overview)
    bodies, names, failures, error = [overview], [None], [], None

    def fields():
        found = records.about_fields(bodies, profile_id=profile_id, collection_names=names,
                                     captured_at=datetime.now().astimezone())
        return [f for f in found if not args.section or f['section'] == args.section]

    for collection in collections:
        if args.section and fields():
            break
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
    issues = records.about_issues(bodies)
    result = {'results': fields(), 'stop_reason': 'exhausted', 'issues': issues}
    where = 'the section may be there' if args.section else 'its fields are missing'
    coverage = [f'collection {f["section"]} failed — {where}' for f in failures]
    if args.section and not result['results'] and not failures and not issues:
        coverage.append(f"section {args.section} is not in this profile's visible About")
    if failures:
        result['details'] = {'failed_sections': failures}
        result['failure'] = error
        if error.code == 8:
            needed = setup + 1 + len(collections)
            result['failure'] = FacebookError(8, f'The request budget ran out after {len(bodies) - 1} of '
                                                 f'{len(collections)} About collections; this profile needs '
                                                 f'{"up to " if args.section else ""}{needed} requests.',
                                              FIXES['budget_restart'])
    if coverage:
        result['coverage'] = coverage
    return result
