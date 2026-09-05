"""Comments, search results, and visible About collections."""
import base64
import json
from datetime import datetime
from urllib.parse import quote

import _about
import _comment
import _entity
from _cmds_posts import fetch_post_story, page_options, posts_from_raw
from _errors import FacebookError
from _paginate import paginate, find_page_info, connection_has_items
from _parse import iter_json_objects
from _registry import ABOUT_SECTION_ID, COMMENT_SORT_TOKENS, build_variables, get_query
from _resolve import resolve_profile_id


def _failure(result, error):
    result.update(ok=False, error='partial' if result['results'] else 'query_failure',
                  code=error.code, message=error.message, fix=error.fix)
    result['stop_reason'] = 'blocked' if error.code == 5 else 'budget' if error.code == 8 else 'query_failure'


def comments(args, transport, *, state, commit, story=None, first_batch=False):
    # Pending parent records retain their expansion handles across --after.
    pending = state.get('pending') or []
    post_id = next((r.get('post_id') for r in pending if r.get('post_id')), None)
    cursor = state.get('cursor')
    retry_parents = cursor.get('reply_retries', []) if isinstance(cursor, dict) else []
    if isinstance(cursor, dict) and 'post_id' in cursor:
        post_id, cursor = cursor['post_id'], cursor['after']
    if post_id is None:
        story = story or fetch_post_story(transport, args.target)
        post_id = (story.get('feedback') or {}).get('id')
    if not post_id:
        raise FacebookError(6, 'The post has no comment feedback handle.')
    failures, expanded, retry_waiting = [], {}, []
    shown = set(state.get('seen') or [])
    fatal = None
    sort = getattr(args, 'sort', 'top')
    first_page_info = {}

    def fetch(after):
        if fatal:
            raise fatal
        key = 'comments' if after is None else 'comments_page'
        variables = {'id': post_id, 'commentsIntentToken': COMMENT_SORT_TOKENS[sort]}
        if after is not None:
            variables['commentsAfterCursor'] = after
        raw = transport.query(key, variables, referer=args.target)
        parents = []
        for node in _comment.iter_comment_nodes([raw]):
            comment = _comment.build_comment(node, post_id=post_id, captured_at=datetime.now().astimezone())
            if comment.depth != 0:
                continue
            record = comment.to_dict()
            record['_reply_handle'] = {'id': _comment.feedback_id(node), 'token': _comment.expansion_token(node)}
            parents.append(record)
        info = find_page_info(raw, 'comments')
        if first_batch and info:
            first_page_info.update(info)
            info = {'has_next_page': False, 'end_cursor': None}
        return parents, info

    def expand(parent):
        nonlocal fatal
        handle = parent.get('_reply_handle', {})
        replies = []
        if not getattr(args, 'replies', False) or not parent.get('reply_count'):
            return replies
        failure = {'parent_id': parent['id']}
        if fatal:
            failure.update(reason='request_failure', retryable=True,
                           message='Skipped after a terminal request failure.')
        elif not handle.get('id') or not handle.get('token'):
            failure.update(reason='missing_handle', retryable=False,
                           message='Reply expansion handle is unavailable.')
        else:
            try:
                raw = transport.query('replies', {'id': handle['id'], 'expansionToken': handle['token']},
                                      referer=args.target)
                replies = [r.to_dict() for r in _comment.build_comments(
                    [raw], post_id=post_id, captured_at=datetime.now().astimezone()) if r.depth > 0]
                for reply in replies:
                    if not reply.get('parent_id'):
                        reply['parent_id'] = parent['id']
                replies = [r for r in replies if r['parent_id'] == parent['id'] and r['id'] not in shown]
                shown.update(r['id'] for r in replies)
                info = find_page_info(raw, 'replies_connection')
                if info and info.get('has_next_page') is False:
                    return replies
                failure.update(reason='batch_limit' if info and info.get('has_next_page') else 'missing_page_info',
                               retryable=False, message='Only the first reply batch is available; it will not be retried.')
            except FacebookError as error:
                if error.code == 7:
                    return []
                failure.update(reason='request_failure', retryable=True, code=error.code, message=error.message)
                if error.code in (4, 5, 8):
                    fatal = error
        failures.append(failure)
        if failure['retryable']:
            retry_waiting.append(dict(parent))
        return replies

    def finish_page(records, after, reason):
        nonlocal fatal
        output = []
        for parent in records:
            replies = expand(parent)
            expanded[parent['id']] = replies
            output.append({k: v for k, v in parent.items() if k != '_reply_handle'})
            output.extend(replies)
        if commit:
            if retry_waiting:
                # Retry the uncommitted page so failed reply expansions cannot disappear.
                fatal = fatal or FacebookError(6, 'A reply page is incomplete; resume the same output file.')
            else:
                commit(output, {'post_id': post_id, 'after': after}, reason)

    retried = []
    for parent in retry_parents:
        retried.extend(expand(parent))

    options = page_options(args, {**state, 'cursor': cursor}, finish_page)
    if first_batch:
        # post returns only this root batch; --limit still selects parents within it.
        options['page_limit'] = bool(args.out)
        options['since'] = options['until'] = None
    if fatal:
        result = {'ok': True, 'results': [], 'cursor': cursor, 'pending': pending, 'stop_reason': 'query_failure'}
    else:
        result = paginate(fetch, **options)
    if first_batch and first_page_info.get('has_next_page') is True:
        result['cursor'] = first_page_info.get('end_cursor')
        if result['stop_reason'] == 'exhausted':
            result['stop_reason'] = 'limit_reached'
    result['results'] = retried + [item for parent in result['results']
        for item in [{k: v for k, v in parent.items() if k != '_reply_handle'},
                     *expanded.get(parent['id'], [])]]
    if result.get('cursor') is not None or retry_waiting:
        result['cursor'] = {'post_id': post_id, 'after': result['cursor'], 'reply_retries': retry_waiting}
    if failures:
        result['replies_incomplete'] = failures
        if result.get('code') not in (4, 5, 8):
            query_failed = not result['ok']
            _failure(result, fatal or FacebookError(6, 'Some replies could not be read completely.'))
            if not query_failed and all(f['reason'] == 'batch_limit' for f in failures):
                result['stop_reason'] = 'reply_batch_limit'
    return result


def search(args, transport, state, commit):
    spec = get_query('search')
    variables = build_variables(spec)
    variables['args']['text'] = args.target
    variables['args']['experience']['type'] = _entity.SEARCH_EXPERIENCE_TYPES[args.type]

    def fetch(cursor):
        raw = transport.query('search', {**variables, 'cursor': cursor},
                              referer='https://www.facebook.com/search/' + args.type + '/?q=' + quote(args.target))
        records = posts_from_raw(raw, 'search') if args.type in ('top', 'posts') else []
        if args.type != 'posts':
            records += [r.to_dict() for r in _entity.build_entities(
                [raw], search_type=args.type, captured_at=datetime.now().astimezone())]
        if args.type == 'top':
            by_id = {r['id']: r for r in records}
            ordered = []
            emitted = set()
            for edge in _search_edges(raw):
                single = json.dumps({'data': {'results': {'edges': [edge]}}}).encode()
                candidates = posts_from_raw(single, 'search') + [r.to_dict() for r in _entity.build_entities(
                    [single], search_type='top', captured_at=datetime.now().astimezone())]
                for record in candidates:
                    if record['id'] not in emitted:
                        ordered.append(by_id.pop(record['id'], record))
                        emitted.add(record['id'])
            records = ordered + list(by_id.values())
        if not records and connection_has_items(raw, spec.connection_key):
            raise FacebookError(6, 'A nonempty search connection contains no readable results.', 'Run refresh, then retry.')
        return records, find_page_info(raw, spec.connection_key)

    return paginate(fetch, **page_options(args, state, commit))



def _search_edges(raw):
    # Connection indices, rather than deferred arrival times, define result order.
    positions = {}
    wrappers = {'node', 'result', 'entity', 'profile', 'group', 'page', 'user',
                'rendering_strategy', 'view_model'}

    def connection(value):
        for key in ('edges', 'nodes'):
            for index, item in enumerate(value.get(key) or []):
                positions.setdefault(index, []).append(item if key == 'edges' else {'node': item})

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('results', 'search_results') and isinstance(child, dict):
                    connection(child)
                elif key != 'incremental':
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for envelope in iter_json_objects([raw]):
        for chunk in [envelope, *(envelope.get('incremental') or [])]:
            if not isinstance(chunk, dict):
                continue
            path, data = chunk.get('path') or [], chunk.get('data')
            indices = [i for i, key in enumerate(path) if key in ('results', 'search_results')]
            if not path:
                walk(data)
            elif indices:
                tail = path[indices[-1] + 1:]
                if not tail and isinstance(data, dict):
                    connection(data)
                elif len(tail) == 1 and tail[0] in ('edges', 'nodes') and isinstance(data, list):
                    connection({tail[0]: data})
                elif (len(tail) >= 2 and tail[0] in ('edges', 'nodes') and type(tail[1]) is int
                      and all(type(key) is int or key in wrappers for key in tail[2:])):
                    positions.setdefault(tail[1], []).append({'node': data})
    for index in sorted(positions):
        yield from positions[index]


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


def run(args, transport, *, state=None, commit=None):
    state = state or {}
    if args.command == 'comments':
        return comments(args, transport, state=state, commit=commit)
    if args.command == 'search':
        return search(args, transport, state, commit)
    return about(args, transport, state, commit)
