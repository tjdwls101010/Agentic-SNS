"""Refresh through guarded Transport.mine/capture/query_spec; cache metadata only."""
import base64
import copy
import json
import os
import re
import tempfile
from urllib.parse import urlsplit

from _blocked import cache_dir, account_lock
from _errors import FacebookError
from _registry import ABOUT_SECTION_ID, QuerySpec, load_registry
from _resolve import normalize_post, resolve_story_id
from _cmds_posts import posts_from_raw
from _transport import classify

COMMENT_KEYS = {'comments', 'comments_page', 'replies'}
ROUTES = ('https://www.facebook.com/', 'https://www.facebook.com/zuck',
          'https://www.facebook.com/zuck/about', 'https://www.facebook.com/search/top/?q=facebook',
          'https://www.facebook.com/groups/1084901568224581/')


def _save(updates, flags):
    """Read at commit time so unrelated query overrides survive a refresh."""
    with account_lock():
        directory = cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'registry.json'
        temporary = None
        try:
            saved = json.loads(path.read_text()) if path.exists() else {}
            queries = saved.setdefault('queries', {})
            for key, patch in updates.items():
                queries.setdefault(key, {}).update(patch)
            saved.setdefault('relay_provider_flags', {}).update(flags)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                             prefix='.registry-', suffix='.tmp', delete=False) as output:
                temporary = output.name
                json.dump(saved, output, ensure_ascii=True, allow_nan=False)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        except (OSError, ValueError, TypeError, AttributeError):
            raise FacebookError(6, 'Could not save registry overrides; the previous file was preserved.') from None
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


def _relay_flags(variables):
    return {name: value for name, value in variables.items()
                 if re.fullmatch(r'__relay_internal__pv__[A-Za-z0-9_]+relayprovider', name)
                 and (type(value) in (bool, int) or isinstance(value, str) and
                      re.fullmatch(r'[A-Z][A-Z_]{0,79}', value))}


def refresh(transport, capture=False, post=None):
    """Return updated/missing key lists and a key -> safe failure reason mapping."""
    if capture and not post:
        raise FacebookError(2, 'Capture needs a Facebook post URL.')
    if post is not None:
        post = normalize_post(post)
    registry = load_registry()
    queries = registry['queries']
    by_name = {spec['name']: key for key, spec in queries.items()}
    candidates = {}
    prefetched_flags = {}
    failed = {}
    transport.start()
    seen_scripts = set()
    mining_supported = callable(getattr(transport, 'mine', None))
    mining_failed = not mining_supported
    route_keys = ({'newsfeed', 'post'}, {'timeline'}, {'about'}, {'search'}, {'group'})
    for route, expected in zip(ROUTES, route_keys) if mining_supported else ():
        try:
            page = transport.mine(route, list(by_name))
            classify(page, html=True)
        except FacebookError as error:
            if error.code not in (2, 6):
                raise
            mining_failed = True
            continue
        prefetched_flags.update(_relay_flags(page.get('relay_provider_flags') or {}))
        if expected <= candidates.keys():
            continue
        mined = page
        for candidate in mined.get('queries', []):
            if candidate.get('name') in by_name:
                candidates[by_name[candidate['name']]] = candidate
        for url in mined.get('scripts', []):
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.fbcdn.net')
                    or parsed.username or parsed.password or parsed.port not in (None, 443)
                    or not parsed.path.startswith('/rsrc.php/') or url in seen_scripts):
                continue
            seen_scripts.add(url)
            try:
                bundle = transport.mine(url, list(by_name))
                classify(bundle, html=True, asset=True)
            except FacebookError as error:
                if error.code not in (2, 6):
                    raise
                mining_failed = True
                continue
            found = bundle
            for candidate in found.get('queries', []):
                if candidate.get('name') in by_name:
                    candidates[by_name[candidate['name']]] = candidate
            if expected <= candidates.keys():
                break
    if mining_failed:
        reason = 'mining_request_failed' if mining_supported else 'mining_transport_unsupported'
        failed.update({key: reason for key in queries.keys() - COMMENT_KEYS - candidates.keys()})
    if capture:
        capture_routes = [
            (ROUTES[0], {'newsfeed'}, ['scroll_feed', 'scroll_feed', 'scroll_feed']),
            (post, COMMENT_KEYS, ['open_comments', 'sort_comments', 'more_comments', 'expand_replies']),
        ]
        for url, wanted, actions in capture_routes:
            targets = [queries[key]['name'] for key in queries if key in wanted]
            try:
                envelope = transport.capture({'url': url, 'targets': targets, 'actions': actions})
                classify(envelope)
                captured = json.loads(envelope['body'])
                for observed in captured.get('envelopes', []):
                    classify(observed, html=True, retried=True)
            except FacebookError as error:
                if error.code != 6:
                    raise
                captured = {'queries': [], 'failed': True}
            for candidate in captured.get('queries', []):
                key = by_name.get(candidate.get('name'))
                if key in wanted:
                    if key == 'newsfeed':
                        candidate = {**candidate, 'variables': _relay_flags(candidate.get('variables') or {})}
                    candidates[key] = candidate
            if captured.get('failed'):
                for key in wanted & queries.keys():
                    if key not in candidates:
                        failed[key] = 'capture_failed'
    captured_flags = dict(prefetched_flags)
    for candidate in candidates.values():
        variables = candidate.get('variables') or {}
        if isinstance(variables, dict):
            for name, value in _relay_flags(variables).items():
                # 성진: Captured providers normally agree; split per-query flags if differing values are observed live.
                captured_flags.setdefault(name, value)
    updates, flags = {}, {}
    for key in sorted(candidates, key=lambda key: (key != 'newsfeed', key == 'post', key)):
        candidate = candidates[key]
        if not re.fullmatch(r'[0-9]+', str(candidate.get('doc_id', ''))):
            failed[key] = 'invalid_candidate'
            continue
        replay = getattr(transport, 'query_spec', None)
        if not callable(replay):
            failed[key] = 'candidate_replay_unsupported'
            continue
        variables = candidate.get('variables', {})
        if not isinstance(variables, dict):
            failed[key] = 'invalid_candidate'
            continue
        relay = _relay_flags(variables)
        spec = copy.deepcopy(queries[key])
        spec['doc_id'] = candidate['doc_id']
        spec['relay_provider_flags'] = {**registry.get('relay_provider_flags', {}), **captured_flags, **relay}
        seeds = {}
        referer = spec['referer']
        if key == 'timeline':
            seeds, referer = {'id': '4', 'count': 3}, ROUTES[1]
        elif key == 'about':
            seeds = {'userID': '4', 'pageID': '4', 'sectionToken': base64.b64encode(f'app_section:4:{ABOUT_SECTION_ID}'.encode()).decode()}
            referer = ROUTES[2]
        elif key == 'search':
            seeds = {'args': {**copy.deepcopy(spec['variables']['args']), 'text': 'facebook'}, 'count': 3}
            referer = ROUTES[3]
        elif key == 'group':
            seeds, referer = {'id': '1084901568224581', 'count': 3}, ROUTES[4]
        elif key == 'newsfeed':
            seeds = {'count': 3}
        elif key in COMMENT_KEYS:
            referer = post
        body = b''
        try:
            if key == 'post':
                if not post:
                    failed[key] = 'sample_post_missing'
                    continue
                seeds, referer = {'storyID': resolve_story_id(transport, post)}, post
            body = replay(QuerySpec(**spec), overrides={**seeds, **copy.deepcopy(variables)}, referer=referer)
            if not isinstance(body, bytes):
                raise FacebookError(6, 'Candidate replay did not return bytes.')
            try:
                body = body.decode('utf-8')
            except UnicodeError:
                raise FacebookError(6, 'Candidate replay returned invalid data.') from None
            classify({'status': 200, 'url': 'https://www.facebook.com/api/graphql/', 'body': body},
                     expected=QuerySpec(**spec))
        except FacebookError as error:
            if error.code not in (6, 7):
                raise
            if error.code == 6:
                failed[key] = 'replay_failed'
                continue
            # Exit 7 means classification verified an explicitly empty connection.
        if key in ('newsfeed', 'timeline', 'group', 'search') and not post:
            for sample in posts_from_raw(body.encode() if isinstance(body, str) else body, 'newsfeed'):
                try:
                    post = normalize_post(sample.get('url') or '')
                    break
                except FacebookError:
                    continue
        updates[key] = {'name': spec['name'], 'doc_id': spec['doc_id']}
        flags.update(captured_flags)
        flags.update(relay)
    if updates:
        _save(updates, flags)
    return {'updated': sorted(updates), 'missing': sorted(set(queries) - candidates.keys() - failed.keys()),
            'failed': failed}
