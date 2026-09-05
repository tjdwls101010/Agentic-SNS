"""Discover metadata, verify through the same guarded transport, then merge atomically."""
import json
import re
from datetime import date

from ._blocked import account_lock, cache_dir, write_state
from ._cmds_common import finish
from ._errors import ThreadsError
from ._ssr import SSR
from ._target import parse_target
from ._walk import read_page

CAPTURE = ['useBarcelonaAccountSearchGraphQLDataSourceQuery', 'BarcelonaFriendshipsFollowersTabQuery',
           'BarcelonaFriendshipsFollowingTabQuery', 'BarcelonaFriendshipsFollowingTabRefetchableQuery',
           'BarcelonaLikedPageViewerQuery', 'BarcelonaSavedPageViewerQuery']


def save(updates):
    with account_lock():
        path = cache_dir() / 'registry.json'
        try:
            saved = json.loads(path.read_text()) if path.exists() else {'operations': {}}
            saved['operations'].update(updates)
            write_state('registry.json', saved)
        except (ValueError, KeyError, AttributeError, OSError):
            raise ThreadsError(6, 'Registry override cannot be merged; previous file preserved.') from None


def flags(variables):
    return {key: value for key, value in variables.items()
            if re.fullmatch(r'__relay_internal__pv__[A-Za-z0-9_]+relayprovider', key)
            and (type(value) in (bool, int) or isinstance(value, str) and re.fullmatch(r'[A-Z_]{1,80}', value))}


def refresh(transport, args):
    candidates, documents, failed, updated = {}, {}, {}, {}
    wanted = set(CAPTURE if args.capture else transport.registry.operations.keys() - set(CAPTURE))
    post = parse_target(args.post, 'post') if args.post else None
    html = transport.page('/')
    viewer = transport.session.viewer
    def discover(html):
        ssr = SSR(html)
        for entry in ssr.preloaders:
            if entry['name'] in wanted:
                candidates[entry['name']] = entry
                documents[entry['name']] = ssr
        return ssr
    if not args.capture:
        discover(html)
        for path in ['/@' + viewer, *['/@' + viewer + '/' + tab for tab in ('replies', 'reposts', 'media')], '/search?q=a&serp_type=default']:
            try:
                ssr = discover(transport.page(path))
                if path == '/@' + viewer and not post:
                    try:
                        data = ssr.select('BarcelonaProfileThreadsTabDirectQuery',
                                          transport.session.identity('BarcelonaProfileThreadsTabDirectQuery', 'userID'))
                        records = read_page(data, 'BarcelonaProfileThreadsTabDirectQuery').records
                        seed = next((p.get('url') for p in records if p.get('url')), None)
                        if seed:
                            post = parse_target(seed, 'post')
                    except ThreadsError:
                        pass
            except ThreadsError as error:
                if error.code in (4, 5):
                    raise
                failed[path] = error.error
        if post:
            try:
                discover(transport.page(post.path))
            except ThreadsError as error:
                if error.code in (4, 5):
                    raise
                failed['post_route'] = error.error
        else:
            failed['post_route'] = 'No own post in SSR; supply --post URL to verify the three post operations.'
    else:
        if not post:
            raise ThreadsError(2, 'Capture needs a public post page to start the SPA flow.', 'Run refresh --capture --post <post URL>.')
        capture = transport.capture(post, CAPTURE)
        for candidate in capture['queries']:
            if candidate['name'] in wanted:
                candidates[candidate['name']] = candidate
        failed.update(capture.get('missing', {}))
    for name, candidate in candidates.items():
        spec = transport.registry.get(name)
        spec.update(doc_id=candidate['doc_id'], flags=flags(candidate['variables']),
                    captured_at=date.today().isoformat(), verified=True)
        spec['flag_count'] = len(spec['flags'])
        try:
            if 'StrongId' in name:
                documents[name].select(name, str(candidate['variables']['postID']))
            else:
                values = {key: value for key, value in candidate['variables'].items() if not key.startswith('__relay_internal__')}
                transport.query(name, values, spec=spec)
            updated[name] = spec
        except ThreadsError as error:
            if error.code in (4, 5):
                raise
            failed[name] = error.error
    if updated:
        save(updated)
    missing = {name: failed.get(name, 'Not observed in this route/capture; previous registry entry retained.')
               for name in transport.registry.operations if name not in updated}
    required_missing = wanted - updated.keys()
    result = {'ok': not required_missing, 'updated': sorted(updated), 'missing': missing, 'failed': failed,
              'stop_reason': 'query_failure' if required_missing else 'exhausted', 'code': 8 if required_missing else 0,
              'results': []}
    if args.capture:
        result['capture'] = {key: value for key, value in capture.items() if key != 'queries'}
    return finish(result, transport)
