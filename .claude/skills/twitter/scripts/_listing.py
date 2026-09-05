"""Pagination policy independent of transport; a pending tail costs no request."""
from ._errors import TwitterError


def collect(fetch, *, limit=10, state=None, users=False, since=None, until=None, monotonic=False, out=None):
    state = dict(state or {})
    pending = list(state.get('pending', []))
    cursor = state.get('cursor')
    seen = set(state.get('seen', []))
    results, empty, metadata = [], 0, dict(state.get('metadata', {}))
    terminal = state.get('terminal')
    reason, failure = 'limit_reached', None
    fetched_page = False

    def units():
        return sum(r.get('role') not in ('parent', 'focal') for r in results)

    while True:
        while pending and (units() < limit or pending[0].get('role') in ('parent', 'focal')):
            results.append(pending.pop(0))
        if units() >= limit:
            reason = terminal if not pending and terminal else 'limit_reached'
            break
        if terminal:
            reason = terminal
            break
        try:
            records, next_cursor, meta = fetch(cursor)
        except TwitterError as error:
            if not results and not fetched_page and not (out and out.count):
                raise
            reason = 'budget' if error.error == 'budget' else 'blocked' if error.code in (4, 5) else 'query_failure'
            failure = error
            break
        fetched_page = True
        branches = set(metadata.get('hidden_branch_ids', [])) | set(meta.get('hidden_branch_ids', []))
        metadata.update(meta)
        if 'hidden_branch_ids' in meta or branches:
            metadata.update(hidden_branch_ids=sorted(branches), hidden_branches=len(branches))
        fresh = []
        for record in records:
            if record.get('id') in seen:
                continue
            seen.add(record.get('id'))
            fresh.append(record)
        old = [r for r in fresh if r.get('created_at') and not r.get('is_pinned')]
        reached = bool(since and monotonic and old and all(r['created_at'] < since for r in old))
        terminal = ('window_reached' if reached else 'terminated' if meta.get('terminated') else
                    'not_paginable' if meta.get('not_paginable') else
                    'exhausted' if not next_cursor or next_cursor == cursor else None)
        cursor = next_cursor
        eligible = [r for r in fresh if not r.get('created_at') or
                    (not since or r['created_at'] >= since) and (not until or r['created_at'] < until)]
        pending.extend(eligible)
        empty = empty + 1 if not fresh else 0
        if users and empty >= 3 and not terminal:
            reason = 'empty_pages'
        if out:
            if metadata.get('focal_id'):
                replies = [r for r in eligible if r.get('role') == 'reply']
                direct = sum(r.get('in_reply_to_id') == metadata['focal_id'] for r in replies)
                metadata['direct_shown'] = metadata.get('direct_shown', 0) + direct
                metadata['nested_shown'] = metadata.get('nested_shown', 0) + len(replies) - direct
            out.commit(eligible, {'cursor': cursor, 'seen': list(seen), 'pending': [], 'metadata': metadata, 'terminal': terminal},
                       terminal or ('empty_pages' if reason == 'empty_pages' else 'limit_reached'))
        if reason == 'empty_pages':
            break
    next_state = dict(state, cursor=cursor, pending=pending, seen=list(seen), metadata=metadata, terminal=terminal)
    result = dict(ok=failure is None, results=results, stop_reason=reason, state=next_state,
                  code=8 if failure or reason in ('budget', 'empty_pages') else 0, **metadata)
    if failure:
        result.update({k: v for k, v in failure.to_dict().items() if k != 'ok'})
    return result
