"""Facebook's record lines: the dense text of a post, a comment, a person, page or group, an About field and a group
card. The page frame (header, window, coverage, more:) is the core's; all clipping and labels live here, the records
themselves are never shortened."""
from sns.text import count as _count, limit_of, line as _line, quote as _quote, shown as _shown, time as _time


def _handle(value):
    return _quote(value) if value else 'unavailable'


def _media(record):
    parts = []
    for item in record.get('media') or []:
        part = item.get('kind', 'photo')
        if item.get('alt'):
            part += ' alt=' + _quote(item['alt'])
        parts.append(part)
    return ' · '.join(parts)


def post(record, index, chars):
    labels = [_line(record.get('author_name') or 'unavailable')]
    if record.get('created_at') or not record.get('sponsored'):
        labels.append(_time(record.get('created_at')))
    labels += [flag for flag in ('sponsored', 'pinned', 'incomplete') if record.get(flag)]
    if record.get('text_truncated'):
        labels.append('text cut by Facebook')
    labels += [record.get('type', 'unknown'), f'reactions={_count(record.get("reaction_count"))} '
                                              f'comments={_count(record.get("comment_count"))} '
                                              f'shares={_count(record.get("share_count"))}']
    lines = [f'[p{index}] ' + ' · '.join(labels), '     ' + _shown(record.get('text'), chars)]
    shared, depth, seen = record.get('shared_post'), 1, {id(record)}
    while shared is not None and id(shared) not in seen:
        seen.add(id(shared))
        label = 'shared-from' if depth == 1 else f'shared-from[{depth}]'
        state = ' · incomplete' if shared.get('incomplete') else ''
        lines.append(f'     {label}: {_line(shared.get("author_name") or "unavailable")} · '
                     f'{_time(shared.get("created_at"))}{state} · url: {_handle(shared.get("url"))} · '
                     f'author: {_handle(shared.get("author_url"))} · {_shown(shared.get("text"), chars)}')
        shared, depth = shared.get('shared_post'), depth + 1
    if record.get('media'):
        lines.append('     media: ' + _media(record))
    lines.append(f'     url: {_handle(record.get("url"))}   author: {_handle(record.get("author_url"))}')
    return '\n'.join(lines)


def comment(record, index, parent_label, chars):
    depth = record.get('depth') or 0
    indent = '  ' * min(max(depth, 0), 10)
    parent = f' reply-to={parent_label}' if depth and parent_label else ''
    kinds = ','.join(_line(a.get('kind')) for a in record.get('attachments') or [])
    tail = f'   replies {record["replies_handle"]}' if record.get('replies_handle') else ''
    return (f'{indent}[c{index}{parent}] {_line(record.get("author_name") or "unavailable")} · '
            f'{_time(record.get("created_at"))} · reactions={_count(record.get("reaction_count"))} '
            f'replies={_count(record.get("reply_count"))}\n'
            f'{indent}     {_shown(record.get("text"), chars)}' + (f' · attachment={kinds}' if kinds else '') + '\n'
            f'{indent}     author: {_handle(record.get("author_url"))}{tail}')


def group_card(record, index):
    parts = [_line(record.get('name') or 'unavailable')] + [_line(record[key]) for key in ('privacy', 'member_count_text')
                                                            if record.get(key)]
    if record.get('join_state'):
        parts.append('you: ' + _line(record['join_state']))
    if record.get('membership_questions'):
        parts.append('membership questions')
    lines = [f'[e{index}] group id={_line(record["id"])} · ' + ' · '.join(parts)
             + f' · url: {_handle(record.get("url"))}']
    if record.get('description'):
        lines.append('     description: ' + _quote(record['description']))
    activity = [f'{record["posts_last_day"]} posts in the last day' if record.get('posts_last_day') is not None else None,
                f'{record["posts_last_month"]} in the last month' if record.get('posts_last_month') is not None else None,
                f'created {record["created_at"][:10]}' if record.get('created_at') else None]
    if any(activity):
        lines.append('     activity: ' + ' · '.join(a for a in activity if a))
    for number, rule in enumerate(record.get('rules') or [], 1):
        lines.append(f'     rule {number}: {_quote(rule["title"])}'
                     + (f' — {_quote(rule["description"])}' if rule.get('description') else ''))
    return '\n'.join(lines)


def entity(record, index):
    if 'privacy' in record:  # a group card
        return group_card(record, index)
    verified = {True: 'verified', False: 'unverified', None: 'verified=?'}[record.get('verified')]
    return (f'[e{index}] {_line(record["kind"])} id={_line(record["id"])} · {_line(record.get("name") or "unavailable")} '
            f'· {verified} · url: {_handle(record.get("url"))}')


def about(record):
    return (f'{_line(record["section"])}: {_line(record["text"])}'
            + (f' ({_quote(record["url"])})' if record.get('url') else ''))


def render(envelope, chars, command):
    """The record lines of a text page: chars None is the default length, 0 everything received."""
    limit = limit_of(chars)
    results = envelope.get('results') or []
    lines = []
    thread = envelope.get('thread')
    if thread:
        lines.append(f'thread: post {_handle(thread.get("post_url"))} · replies to comment {_line(thread.get("parent_id"))}')
    labels = {r['id']: f'c{i}' for i, r in enumerate((r for r in results if r.get('kind') == 'comment'), 1)}
    counts = {'p': 0, 'c': 0, 'e': 0}
    for record in results:
        kind = record.get('kind')
        if kind == 'comment':
            counts['c'] += 1
            lines.append(comment(record, counts['c'], labels.get(record.get('parent_id')), limit))
        elif kind == 'about':
            lines.append(about(record))
        elif kind in ('person', 'page', 'group'):
            counts['e'] += 1
            lines.append(entity(record, counts['e']))
        else:
            counts['p'] += 1
            lines.append(post(record, counts['p'], None if command == 'post' else limit))
    return lines
