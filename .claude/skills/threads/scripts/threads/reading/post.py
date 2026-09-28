"""One post page: the post, its parent chain and the first reply batch, all from the route's own payloads.

SSR reply completeness never pretends an unreplayable cursor is pagination."""
from ..errors import ThreadsError
from ..graphql.decode import at, drift
from ..graphql.normalize import build_post
from ..graphql.ssr import SSR
from ..graphql.transport import Transport
from ..model import Completeness
from ..store import OutFile
from .common import finish


def run(target, *, sort, limit, out, ctx):
    transport = Transport(40 if limit or out else 10)
    html = transport.page(target.path + ('?sort_order=recent' if sort == 'recent' else ''))
    result = read_thread(html, target.code, sort=sort, limit=limit)
    if out:
        output = OutFile(out, ctx)
        try:
            output.commit(result['results'], {'completeness': result['completeness'], 'terminal': 'not_paginable'},
                          'ssr_complete')
            result.update(out=str(output.path), count=output.count, results=[])
        finally:
            output.close()
    return finish(result, transport)


def read_thread(html, code, *, sort, limit):
    target_id, target, upward, downward = SSR(html).post_page(code)
    post = build_post(target['media'])
    if post is None or post.unavailable:
        raise ThreadsError(9, 'This post is unavailable.')
    parents = at(upward, 'media.text_post_app_info.containing_thread.posts.edges')
    threads = at(downward, 'media.text_post_app_info.direct_replies.edges')
    if not isinstance(parents, list) or not isinstance(threads, list):
        raise drift('Expected explicit parent and direct-reply edges.')
    records, seen = [], {target_id}
    for edge in parents:
        item = build_post(at(edge, 'node'))
        if item and item.id not in seen:
            records.append(item.to_dict() | {'role': 'parent', 'depth': 0})
            if item.id:
                seen.add(item.id)
    records.append(post.to_dict() | {'role': 'post', 'depth': 0})
    received, shown, descendants, unavailable, groups_shown = 0, 0, 0, 0, 0
    for edge in threads:
        posts = at(edge, 'node.posts.edges')
        if not isinstance(posts, list) or not posts:
            unavailable += 1
            continue
        group = [build_post(at(item, 'node')) for item in posts]
        first = group[0]
        missing = not first or first.unavailable
        if missing:
            unavailable += 1
        else:
            if first.id in seen:
                continue
            received += 1
            seen.add(first.id)
        if groups_shown >= (limit or 10):
            continue
        groups_shown += 1
        if not missing:
            shown += 1
        depths = {target_id: -1, first.id if first else None: 0}
        for index, item in enumerate(group):
            if item is None:
                continue
            if index and item.id in seen:
                continue
            if index and item.id:
                seen.add(item.id)
            record = item.to_dict() | {'role': 'reply', 'depth': 0}
            if index:
                descendants += 1
                parent_depth = depths.get(item.reply_to_id)
                record['depth'] = parent_depth + 1 if parent_depth is not None else 1
                record['relation'] = 'reply-to=' + item.reply_to_id if item.reply_to_id else 'thread continuation'
            if item.id:
                depths[item.id] = record['depth']
            records.append(record)
    reported = post.reply_count
    estimate = max(reported - received - unavailable, 0) if reported is not None and reported >= received + unavailable else None
    coverage = Completeness(reported, received, shown, descendants, received - shown,
                            unavailable, estimate, estimate is not None).to_dict()
    result = {'ok': True, 'results': records, 'stop_reason': 'not_paginable', 'next': None,
              'completeness': coverage, 'context': {'sort': sort or 'top'}, 'post_id': target_id}
    return result
