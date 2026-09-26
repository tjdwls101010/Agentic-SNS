"""Parent comments first, then replies only for the selected parents."""
from datetime import datetime

from facebook.errors import FacebookError
from facebook.graphql import records
from facebook.graphql.records import post_story
from facebook.outcome import ISSUES
from facebook.graphql.registry import COMMENT_SORT_TOKENS
from facebook.graphql.resolve import resolve_story_id
from facebook.reading.paging import page_options, paginate


def fetch_post_story(transport, url):
    """(story, response issues) of the permalink's own post."""
    raw = transport.query('post', {'storyID': resolve_story_id(transport, url)}, referer=url)
    story, issues = post_story(raw)
    if story is None:
        raise FacebookError(6, 'The post response contains no readable post.', 'Run refresh, then retry the permalink.')
    return story, issues


REPLY_RETRY = 'Run more: (or the same --out command); it retries these replies before reading on.'


def _coverage(failure):
    parent = failure['parent_id']
    if failure['reason'] == 'batch_limit':
        return f'replies to {parent}: first batch only; Facebook offers no further reply page here'
    if failure['reason'] == 'missing_page_info':
        return f'replies to {parent}: first batch only; Facebook did not say whether more exist'
    return f'replies to {parent}: not read; the comment carries no reply handle'


def comments(args, transport, *, state, commit, story=None, first_batch=False):
    # Pending parent records retain their expansion handles across --after.
    pending = state.get('pending') or []
    post_id = next((r.get('post_id') for r in pending if r.get('post_id')), None)
    cursor = state.get('cursor')
    retry_parents = cursor.get('reply_retries', []) if isinstance(cursor, dict) else []
    if isinstance(cursor, dict) and 'post_id' in cursor:
        post_id, cursor = cursor['post_id'], cursor['after']
    if post_id is None:
        story = story or fetch_post_story(transport, args.target)[0]
        post_id = (story.get('feedback') or {}).get('id')
    if not post_id:
        raise FacebookError(6, 'The post has no comment feedback handle.')
    failures, expanded, retry_waiting, issues, page_notes = [], {}, [], [], []
    shown = set(state.get('seen') or [])
    fatal = None
    sort = args.sort or 'top'

    def fetch(after):
        if fatal:
            raise fatal
        key = 'comments' if after is None else 'comments_page'
        variables = {'id': post_id, 'commentsIntentToken': COMMENT_SORT_TOKENS[sort]}
        if after is not None:
            variables['commentsAfterCursor'] = after
        raw = transport.query(key, variables, referer=args.target)
        page = records.comment_page(raw, post_id=post_id, captured_at=datetime.now().astimezone(), parents_only=True)
        if not page.records and page.has_items:
            raise FacebookError(6, 'A nonempty comment connection contains no readable comments.',
                                'Run refresh, then retry.')
        issues.extend(page.issues)
        page_notes.extend(ISSUES.get(issue, issue) for issue in page.issues)
        parents = []
        for record in page.records:
            handle = page.handles.get(record['id'], {})
            parents.append({**record, '_reply_handle': {'id': handle.get('feedback_id'),
                                                        'token': handle.get('expansion_token')}})
        return parents, page.page_info

    def expand(parent):
        nonlocal fatal
        handle = parent.get('_reply_handle', {})
        replies = []
        # A reply count of None was not sent, so the handle still decides; 0 means Facebook says there are none.
        if not args.replies or parent.get('reply_count') == 0:
            return replies
        if parent.get('reply_count') is None and not handle.get('token'):
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
                page = records.reply_page(raw, post_id=post_id, parent_id=parent['id'],
                                          captured_at=datetime.now().astimezone())
                issues.extend(page.issues)
                page_notes.extend(ISSUES.get(issue, issue) for issue in page.issues)
                replies = [r for r in page.records if r['id'] not in shown]
                shown.update(r['id'] for r in replies)
                info = page.page_info
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

    def finish_page(parents, after, reason, skipped=()):
        nonlocal fatal
        output = []
        before = len(failures)
        for parent in parents:
            replies = expand(parent)
            expanded[parent['id']] = replies
            output.append({k: v for k, v in parent.items() if k != '_reply_handle'})
            output.extend(replies)
        if commit:
            if retry_waiting:
                # Retry the uncommitted page so failed reply expansions cannot disappear.
                fatal = fatal or FacebookError(6, 'A reply page is incomplete; resume the same output file.')
            else:
                notes = page_notes + [_coverage(f) for f in failures[before:] if not f['retryable']]
                commit(output, {'post_id': post_id, 'after': after}, reason, (), list(dict.fromkeys(notes)))
        page_notes.clear()

    retried = []
    for parent in retry_parents:
        retried.extend(expand(parent))

    options = page_options(args, {**state, 'cursor': cursor}, finish_page)
    if first_batch:
        # post reads only the root batch; --limit still selects parents within it, more: continues after it.
        options['max_pages'] = 1
    if fatal:
        result = {'results': [], 'cursor': cursor, 'pending': pending, 'stop_reason': None, 'failure': fatal}
    else:
        result = paginate(fetch, **options)
    result['results'] = retried + [item for parent in result['results']
        for item in [{k: v for k, v in parent.items() if k != '_reply_handle'},
                     *expanded.get(parent['id'], [])]]
    if result.get('cursor') is not None or retry_waiting:
        result['cursor'] = {'post_id': post_id, 'after': result['cursor'], 'reply_retries': retry_waiting}
    result['issues'] = issues
    if failures:
        result['details'] = {'replies_incomplete': failures}
        result['coverage'] = [_coverage(f) for f in failures if not f['retryable']]
        current = result.get('failure') or fatal
        # A block or login stop outranks everything; a real reply failure outranks a later budget stop.
        failed = any(f['retryable'] and f.get('code') not in (None, 4, 5, 8) for f in failures)
        if current is not None and current.code != 8:
            result['failure'] = current
        elif failed or current is None and any(f['retryable'] for f in failures):
            result['failure'] = FacebookError(6, 'Some replies could not be read.', REPLY_RETRY)
        else:
            result['failure'] = current
    return result
