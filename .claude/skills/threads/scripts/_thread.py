"""SSR reply completeness never pretends an unreplayable cursor is pagination."""
from ._cmds_common import context
from ._errors import ThreadsError
from ._models import build_post
from ._output import OutFile
from ._ssr import SSR
from ._walk import at, drift


def read_thread(html, session, args):
    ssr = SSR(html)
    target_id = session.identity('BarcelonaPostPageStrongIdTargetQuery', 'postID')
    raw = ssr.select('BarcelonaPostPageStrongIdTargetQuery', target_id)['media']
    if str(raw.get('pk')) != target_id or raw.get('code') != args.target.code:
        raise drift('The SSR post identity or shortcode differs from the requested post.')
    post = build_post(raw)
    if post is None or post.unavailable:
        raise ThreadsError(9, 'This post is unavailable.')
    upward = ssr.select('BarcelonaPostPageStrongIdUpwardQuery', target_id)
    downward = ssr.select('BarcelonaPostPageStrongIdDownwardQuery', target_id)
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
        if groups_shown >= (args.limit or 10):
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
    coverage = {'reported_direct': reported, 'received_direct': received, 'shown_direct': shown,
                'shown_descendants': descendants, 'unshown_received': received - shown,
                'unavailable': unavailable, 'unfetched': estimate, 'unfetched_is_estimate': estimate is not None}
    result = {'ok': True, 'results': records, 'stop_reason': 'not_paginable', 'next': None,
              'completeness': coverage, 'context': {'sort': args.sort or 'top'}, 'post_id': target_id}
    if args.out:
        output = OutFile(args.out, context(args))
        try:
            output.commit(records, {'completeness': coverage, 'terminal': 'not_paginable'}, 'ssr_complete')
            result.update(out=str(output.path), count=output.count, results=[])
        finally:
            output.close()
    return result
