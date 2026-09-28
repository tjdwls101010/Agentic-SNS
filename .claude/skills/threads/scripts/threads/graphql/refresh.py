"""Discover metadata, verify through the same guarded transport, then merge atomically."""
import re
from datetime import date

from ..errors import ThreadsError
from .capture import CAPTURABLE, capture
from .decode import read_page
from .operations import OPERATIONS
from .registry import save
from .ssr import SSR
from .target import parse_target


def flags(variables):
    return {key: value for key, value in variables.items()
            if re.fullmatch(r'__relay_internal__pv__[A-Za-z0-9_]+relayprovider', key)
            and (type(value) in (bool, int) or isinstance(value, str) and re.fullmatch(r'[A-Z_]{1,80}', value))}


def refresh(transport, capture_post=False, post_url=None):
    """Discover, verify and save; returns the system result, without the budget a command adds to it."""
    candidates, failed, updated = {}, {}, {}
    registry = transport.registry
    wanted = set(CAPTURABLE if capture_post else [op.id for op in OPERATIONS.values() if op.discovery == 'route'])
    by_name = {registry.name(operation): operation for operation in wanted}
    post_route = None
    post = parse_target(post_url, 'post') if post_url else None
    if capture_post and (not post or not post.username):
        raise ThreadsError(2, 'Capture needs a canonical public post URL to start the SPA flow.',
                           'Run `refresh --capture --post <public post URL>`.')
    html = transport.page('/')
    viewer = transport.session.viewer
    def discover(html):
        ssr = SSR(html)
        for entry in ssr.preloaders:
            if entry['name'] in by_name:
                candidates[by_name[entry['name']]] = entry
        return ssr
    if not capture_post:
        discover(html)
        for path in ['/@' + viewer, *['/@' + viewer + '/' + tab for tab in ('replies', 'reposts', 'media')], '/search?q=a&serp_type=default']:
            try:
                ssr = discover(transport.page(path))
                if path == '/@' + viewer and not post:
                    try:
                        user_id = transport.session.identity(registry.name('profile.threads'), 'userID')
                        data = transport.rendered(ssr, 'profile.threads', user_id)
                        records = read_page(data, OPERATIONS['profile.threads']).records
                        seed = next((p.get('url') for p in records if p.get('url')), None)
                        if seed:
                            post = parse_target(seed, 'post')
                    except ThreadsError:
                        pass
            except ThreadsError as error:
                if error.code in (4, 5):
                    raise
                failed[path] = error.error
        # Post pages are read from the route itself, so refresh has nothing to update there; it only reports whether
        # a post route still decodes into the post, its parents and its replies.
        if post:
            try:
                SSR(transport.page(post.path)).post_page(post.code)
                post_route = 'decoded'
            except ThreadsError as error:
                if error.code in (4, 5):
                    raise
                post_route = 'failed'
                failed['post_route'] = error.message
        else:
            post_route = 'not_checked'
            failed['post_route'] = 'No own post in SSR; supply --post URL to check that post pages still decode.'
    else:
        observed = capture(transport, post, [registry.name(operation) for operation in CAPTURABLE])
        for candidate in observed['queries']:
            if candidate['name'] in by_name:
                candidates[by_name[candidate['name']]] = candidate
        failed.update(observed.get('missing', {}))
    for operation, candidate in candidates.items():
        entry = {'name': candidate['name'], 'doc_id': candidate['doc_id'], 'flags': flags(candidate['variables']),
                 'captured_at': date.today().isoformat()}
        try:
            values = {key: value for key, value in candidate['variables'].items() if not key.startswith('__relay_internal__')}
            payload = transport.query(operation, values, entry=entry)
            if OPERATIONS[operation].connection:
                read_page(payload, OPERATIONS[operation])
            updated[operation] = entry
        except ThreadsError as error:
            if error.code in (4, 5):
                raise
            failed[candidate['name']] = error.error
    if updated:
        save(updated)
    missing = {registry.name(operation): failed.get(registry.name(operation),
                                                    'Not observed in this route/capture; previous registry entry retained.')
               for operation in registry.operations if operation not in updated}
    incomplete = wanted - updated.keys() or post_route == 'failed'
    result = {'ok': not incomplete, 'updated': sorted(entry['name'] for entry in updated.values()), 'missing': missing,
              'failed': failed,
              'stop_reason': 'query_failure' if incomplete else 'exhausted', 'code': 8 if incomplete else 0,
              'results': []}
    if post_route:
        result['post_route'] = post_route
    if capture_post:
        result['capture'] = {key: value for key, value in observed.items() if key != 'queries'}
    return result
