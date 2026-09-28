"""Discover current ids on Threads' own pages, verify each by replay through the guarded transport, then save.

A route operation is found on the GET route whose render loads it as a preloader. Under its registered name it is a
candidate for a new doc_id or flags. When its name is gone, the route itself can still prove the rename: a preloader
there that no declaration claims and whose variables fit the operation's signature, matched one-to-one with every
declared operation the route lost. That candidate is replayed once under its new name, and saved only if the reply
decodes, carries the declared identity and plays the declared role. Operations only an app tab loads are never adopted
under a new name; an unseen one is reported as possibly renamed.
"""
import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

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


def plays_role(operation, page, user_id):
    """A replayed tab must be this profile's own posts (or its reposts), not another list of the same shape."""
    if operation.role == 'authored':
        return all(any((post.get('author') or {}).get('id') == str(user_id) for post in group) for group in page.groups)
    if operation.role == 'reposted':
        return all(any(post.get('reposted_post') for post in group) for group in page.groups)
    return True


def match_renames(declared, preloaders, claimed, route):
    """{operation id: preloader} when every declared operation missing from this route has exactly one unclaimed,
    signature-fitting preloader and no preloader fits two of them; otherwise a reason."""
    users = {str(p['variables']['userID']) for p in preloaders if 'userID' in p['variables']}
    profile = users.pop() if len(users) == 1 else None
    query = (parse_qs(urlsplit(route).query).get('q') or [None])[0]
    pool = [p for p in preloaders if p['name'] not in claimed]
    fits = {op.id: [p for p in pool if op.signature and op.signature.fits(p['variables'], profile, query)]
            for op in declared}
    chosen = [found[0]['name'] for found in fits.values() if len(found) == 1]
    if any(len(found) != 1 for found in fits.values()) or len(set(chosen)) != len(chosen):
        counts = ', '.join(f'{op}: {len(found)}' for op, found in fits.items())
        return None, f'Its name is gone from {route} and the route does not prove a rename (candidates {counts}).'
    return {op: found[0] for op, found in fits.items()}, None


def refresh(transport, capture_post=False, post_url=None):
    """Discover, verify and save; returns the system result, without the budget a command adds to it."""
    candidates, renames, failed, updated, renamed = {}, {}, {}, {}, {}
    registry = transport.registry
    wanted = set(CAPTURABLE if capture_post else [op.id for op in OPERATIONS.values() if op.discovery == 'route'])
    by_name = {registry.name(operation): operation for operation in wanted}
    claimed = set(registry.admitted())
    post_route = None
    post = parse_target(post_url, 'post') if post_url else None
    if capture_post and (not post or not post.username):
        raise ThreadsError(2, 'Capture needs a canonical public post URL to start the SPA flow.',
                           'Run `refresh --capture --post <public post URL>`.')
    html = transport.page('/')
    viewer = transport.session.viewer
    if not capture_post:
        routes = {}
        for op in OPERATIONS.values():
            if op.discovery == 'route':
                routes.setdefault(op.route.format(viewer=viewer), []).append(op)
        for path, declared in routes.items():
            try:
                page_html = html if path == '/' else transport.page(path, profile_check=False)
            except ThreadsError as error:
                if error.code in (4, 5):
                    raise
                failed[path] = error.error
                continue
            ssr = SSR(page_html)
            present = set()
            for entry in ssr.preloaders:
                if entry['name'] in by_name:
                    candidates[by_name[entry['name']]] = entry
                    present.add(entry['name'])
            lost = [op for op in declared if registry.name(op.id) not in present]
            if lost:
                matched, reason = match_renames(lost, ssr.preloaders, claimed, path)
                if matched:
                    renames.update(matched)
                else:
                    failed.update({registry.name(op.id): reason for op in lost})
            if path == '/@' + viewer and not post:
                post = own_post(transport, ssr)
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
    for operation, candidate in [*candidates.items(), *renames.items()]:
        provisional = operation in renames
        entry = {'name': candidate['name'], 'doc_id': candidate['doc_id'], 'flags': flags(candidate['variables']),
                 'captured_at': date.today().isoformat()}
        declared = OPERATIONS[operation]
        try:
            values = {key: value for key, value in candidate['variables'].items() if not key.startswith('__relay_internal__')}
            payload = transport.query(operation, values, entry=entry, provisional=provisional)
            if declared.connection:
                page = read_page(payload, declared)
                if provisional and not plays_role(declared, page, values.get('userID')):
                    raise ThreadsError(6, f'The replay of {candidate["name"]} is not this profile\'s {operation} list.',
                                       error='role_mismatch')
            updated[operation] = entry
            if provisional:
                renamed[operation] = {'from': registry.name(operation), 'to': candidate['name']}
        except ThreadsError as error:
            if error.code in (4, 5):
                raise
            failed[registry.name(operation) if provisional else candidate['name']] = error.error
    if updated:
        save(updated)
    missing = {registry.name(operation): failed.get(registry.name(operation),
                                                    'Not observed in this route/capture; previous registry entry retained.')
               for operation in registry.operations if operation not in updated}
    incomplete = wanted - updated.keys() or post_route == 'failed'
    result = {'ok': not incomplete, 'updated': sorted(entry['name'] for entry in updated.values()), 'renamed': renamed,
              'missing': missing, 'failed': failed,
              'stop_reason': 'query_failure' if incomplete else 'exhausted', 'code': 8 if incomplete else 0,
              'results': []}
    if post_route:
        result['post_route'] = post_route
    if capture_post:
        result['capture'] = {key: value for key, value in observed.items() if key != 'queries'}
    return result


def own_post(transport, ssr):
    """A post of the viewer's own, rendered on their profile, to check post pages with."""
    try:
        user_id = transport.session.identity(transport.registry.name('profile.threads'), 'userID')
        data = transport.rendered(ssr, 'profile.threads', user_id)
        records = read_page(data, OPERATIONS['profile.threads']).records
        seed = next((p.get('url') for p in records if p.get('url')), None)
        return parse_target(seed, 'post') if seed else None
    except ThreadsError:
        return None
