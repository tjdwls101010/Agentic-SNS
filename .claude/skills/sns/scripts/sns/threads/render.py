"""Threads' record lines: the dense text of a post, a reply, a parent or an account. The page frame (header, window,
coverage, more:) is the core's; all clipping and labels live here, the records themselves are never shortened."""
from sns.text import count as _count, limit_of, line as _line, quote as _quote, shown as _shown, time as _time


def _handle(value):
    return _quote(value) if value else 'unavailable'


def _who(account):
    if not account:
        return 'unavailable'
    parts = ['@' + _line(account.get('username') or '?')]
    if account.get('full_name'):
        parts[0] += f' ({_line(account["full_name"])})'
    if account.get('is_verified'):
        parts.append('verified')
    if account.get('private'):
        parts.append('private')
    return ' · '.join(parts)


def _media(record):
    parts = []
    for item in record.get('media') or []:
        part = item.get('kind', 'photo')
        if item.get('alt'):
            part += ' alt=' + _quote(item['alt'])
        parts.append(part)
    return ' · '.join(parts)


def _nested(label, record, chars):
    if record.get('unavailable'):
        return f'     {label}: unavailable — {_line(record.get("unavailable_reason") or "")}'
    return (f'     {label}: {_who(record.get("author"))} · {_time(record.get("created_at"))} · '
            f'{_shown(record.get("text"), chars)} · url: {_handle(record.get("url"))}')


def post(record, label, labels, chars):
    """One post, reply or parent; `labels` maps ids already shown on this page to their labels."""
    indent = '  ' * min(max(record.get('depth') or 0, 0), 10)
    if record.get('unavailable'):
        return f'{indent}[{label}] unavailable — {_line(record.get("unavailable_reason") or "")}'
    flags = [_who(record.get('author')), _time(record.get('created_at')), record.get('media_type', 'text'),
             f'likes={_count(record.get("like_count"))} replies={_count(record.get("reply_count"))} '
             f'reposts={_count(record.get("repost_count"))} quotes={_count(record.get("quote_count"))}']
    if record.get('role') == 'parent':
        flags.append('parent')
    relation = record.get('relation')
    if relation:
        target = labels.get(relation.get('to'), '?')
        flags.append(f'continuation of {target}' if relation.get('kind') == 'continuation' else f'reply-to={target}')
    elif record.get('is_reply') and record.get('role') != 'reply':
        flags.append('a reply')
    if record.get('pinned'):
        flags.append('pinned')
    lines = [f'{indent}[{label}] ' + ' · '.join(flags), f'{indent}     {_shown(record.get("text"), chars)}']
    if record.get('quoted_post'):
        lines.append(indent + _nested('quoting', record['quoted_post'], chars))
    if record.get('reposted_post'):
        lines.append(indent + _nested('repost of', record['reposted_post'], chars))
    if record.get('media'):
        lines.append(f'{indent}     media: ' + _media(record))
    link = record.get('link_preview')
    if link:
        lines.append(f'{indent}     link: {_quote(link.get("title") or "")} ({_line(link.get("url") or "")})')
    author = _handle((record.get('author') or {}).get('username'))
    tail = f'{indent}     url: {_handle(record.get("url"))}   author: {author}'
    if record.get('replies_handle'):
        tail += f'   replies {record["replies_handle"]}'
    lines.append(tail)
    return '\n'.join(lines)


def account(record, label):
    parts = [_who(record)]
    counts = record.get('counts')
    if counts:
        parts.append(' '.join(f'{key}={_count(counts.get(key))}' for key in ('followers', 'following', 'mutuals')))
    elif record.get('follower_count') is not None:
        parts.append(f'followers={record["follower_count"]}')
    if record.get('reposted_at'):
        parts.append('reposted ' + _time(record['reposted_at']))
    lines = [f'[{label}] ' + ' · '.join(parts)]
    if record.get('bio'):
        lines.append('     bio: ' + _quote(record['bio']))
    if record.get('bio_links'):
        lines.append('     links: ' + ', '.join(_line(link) for link in record['bio_links']))
    lines.append(f'     url: {_handle(record.get("url"))}   author: {_handle(record.get("username"))}')
    return '\n'.join(lines)


def _replies_line(replies):
    reported = '?' if replies.get('reported_direct') is None else replies['reported_direct']
    unfetched = (f'≈{replies["unfetched"]} never received (estimate)' if replies.get('unfetched') is not None
                 else 'never received: unknown')
    return (f'replies: {replies.get("received_direct", 0)} of {reported} direct received · {unfetched} · '
            f'{replies.get("shown_direct", 0)} shown · +{replies.get("shown_descendants", 0)} nested · '
            f'{replies.get("unshown_received", 0)} received but not shown · '
            f'{replies.get("unavailable", 0)} unavailable')


def render(envelope, chars, command):
    """The record lines of a text page (a post read's replies line first). chars None: the default; 0: everything
    received."""
    limit = limit_of(chars)
    lines = [_replies_line(envelope['replies'])] if envelope.get('replies') else []
    labels, counts = {}, {'p': 0, 'r': 0, 'a': 0}
    for record in envelope.get('results') or []:
        if record.get('kind') == 'account':
            counts['a'] += 1
            lines.append(account(record, f'a{counts["a"]}'))
            continue
        prefix = 'r' if record.get('role') == 'reply' else 'p'
        counts[prefix] += 1
        label = f'{prefix}{counts[prefix]}'
        whole = command == 'post' and record.get('role') == 'post'
        lines.append(post(record, label, labels, None if whole else limit))
        if record.get('id'):
            labels[record['id']] = label
    return lines
