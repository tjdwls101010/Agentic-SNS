"""The dense text page: a header naming scope and cost, the window, records, coverage, more:.

All clipping, labels and local-time formatting live here; the records themselves are never shortened.
"""
import json
from datetime import UTC, datetime

DEFAULT_CHARS = 180


def _line(value):
    return (str(value).replace('\r\n', '⏎').replace('\n', '⏎').replace('\r', '⏎').replace(' ', '⏎')
            .replace(' ', '⏎'))


def _quote(value):
    return json.dumps(_line(value), ensure_ascii=False)


def _handle(value):
    return _quote(value) if value else 'unavailable'


def _count(value):
    return '?' if value is None else str(value)


def _time(value):
    if not value:
        return 'undated'
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone().isoformat(timespec='minutes')


def _text(record, chars):
    """text[N of M chars shown]: "…" """
    text = record.get('text') or ''
    shown = text if not chars else text[:chars]
    suffix = '…' if len(shown) < len(text) else ''
    return f'text[{len(shown)} of {len(text)} chars shown]: {_quote(shown + suffix)}'


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
        if item.get('alt_text'):
            part += ' alt=' + _quote(item['alt_text'])
        parts.append(part)
    return ' · '.join(parts)


def _nested(label, record, chars):
    if record.get('unavailable'):
        return f'     {label}: unavailable — {_line(record.get("unavailable_reason") or "")}'
    return (f'     {label}: {_who(record.get("author"))} · {_time(record.get("created_at"))} · {_text(record, chars)} · '
            f'url: {_handle(record.get("url"))}')


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
    if record.get('is_pinned'):
        flags.append('pinned')
    lines = [f'{indent}[{label}] ' + ' · '.join(flags), f'{indent}     {_text(record, chars)}']
    if record.get('quoted_post'):
        lines.append(indent + _nested('quoting', record['quoted_post'], chars))
    if record.get('reposted_post'):
        lines.append(indent + _nested('repost of', record['reposted_post'], chars))
    if record.get('media'):
        lines.append(f'{indent}     media: ' + _media(record))
    link = record.get('link_preview')
    if link:
        lines.append(f'{indent}     link: {_quote(link.get("title") or "")} ({_line(link.get("url") or "")})')
    tail = f'{indent}     url: {_handle(record.get("url"))}   author: {_handle((record.get("author") or {}).get("username"))}'
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
            f'{replies.get("unshown_received", 0)} received but not shown · {replies.get("unavailable", 0)} unavailable')


def _header(envelope, command, shown):
    header = [_line(envelope.get('command') or command or '')]
    header += [f'{key}={_line(envelope[key])}' for key in ('feed', 'sort', 'tab', 'type', 'relation', 'collection')
               if envelope.get(key) is not None]
    if shown is not None:
        header.append(f'{shown} shown')
    tab = envelope.get('tab_opened_requests') or 0
    header += [f'stopped={_line(envelope.get("stop_reason"))}',
               f'requests={envelope.get("request_count", 0) - tab}/{envelope.get("max_requests", 0)}']
    if tab:
        header.append(f'tab opened (+{tab} requests)')
    if envelope.get('unwatched_requests'):
        header.append(f'unwatched={envelope["unwatched_requests"]}')
    return header


def render_page(envelope, *, chars=None, command=None):
    """The text page of one result. chars None: the default; 0: everything received."""
    limit = DEFAULT_CHARS if chars is None else (None if chars == 0 else chars)
    results = envelope.get('results') or []
    lines = [' · '.join(_header(envelope, command, len(results)))]
    window = envelope.get('window')
    if window:
        lines.append(f'window {window.get("since") or ""}..{window.get("until") or ""} · {_line(window["coverage"])}')
    if envelope.get('replies'):
        lines.append(_replies_line(envelope['replies']))
    if envelope.get('reported_total') is not None:
        lines.append(f'reported_total={envelope["reported_total"]} · Threads\' own sample, not the whole list')
    labels, counts = {}, {'p': 0, 'r': 0, 'a': 0}
    for record in results:
        if 'username' in record and 'code' not in record:
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
    lines += ['coverage: ' + _line(note) for note in envelope.get('coverage') or []]
    if envelope.get('error'):
        lines.append(f'coverage: incomplete — {_line(envelope.get("message"))} fix: {_line(envelope.get("fix"))}')
    if envelope.get('next'):
        lines.append('more: ' + envelope['next'])
    return '\n'.join(lines)


def render_summary(envelope):
    """The one line --out prints."""
    parts = _header(envelope, None, None)
    parts.insert(1, f'{envelope.get("count", 0)} saved to {json.dumps(envelope.get("out"), ensure_ascii=False)}')
    if envelope.get('already_complete'):
        parts.append('already complete')
    if envelope.get('window'):
        parts.append(f'window {envelope["window"].get("since") or ""}..{envelope["window"].get("until") or ""} · '
                     f'{envelope["window"]["coverage"]}')
    if envelope.get('coverage'):
        parts.append('coverage: ' + '; '.join(_line(c) for c in envelope['coverage']))
    if envelope.get('next'):
        parts.append('resume: ' + envelope['next'])
    if envelope.get('error'):
        parts.append(f'error={envelope["error"]} fix={_line(envelope.get("fix"))}')
    return ' · '.join(parts)
