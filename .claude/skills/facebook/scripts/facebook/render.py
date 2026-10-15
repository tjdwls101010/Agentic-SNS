"""The dense text page: a header naming scope and cost, the window, records, coverage, detail:, more:.

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
    """text[N of M chars shown, complete|truncated]: "…" — and whether --chars cut it."""
    text = record.get('text') or ''
    shown = text if not chars else text[:chars]
    state = 'truncated' if record.get('text_truncated') else 'complete'
    suffix = '…' if len(shown) < len(text) else ''
    return f'text[{len(shown)} of {len(text)} chars shown, {state}]: {_quote(shown + suffix)}', len(shown) < len(text)


def _media(record):
    parts = []
    for item in record.get('media') or []:
        part = item.get('kind', 'image')
        if item.get('alt'):
            part += ' alt=' + _quote(item['alt'])
        parts.append(part)
    return ' · '.join(parts)


def post(record, index, chars):
    labels = [_line(record.get('author_name') or 'unavailable')]
    if record.get('created_at') or not record.get('sponsored'):
        labels.append(_time(record.get('created_at')))
    labels += [flag for flag in ('sponsored', 'pinned', 'incomplete') if record.get(flag)]
    labels += [record.get('type', 'unknown'), f'reactions={_count(record.get("reaction_count"))} '
                                              f'comments={_count(record.get("comment_count"))} '
                                              f'shares={_count(record.get("share_count"))}']
    lines = [f'[p{index}] ' + ' · '.join(labels), '     ' + _text(record, chars)[0]]
    shared, depth, seen = record.get('shared_post'), 1, {id(record)}
    while shared is not None and id(shared) not in seen:
        seen.add(id(shared))
        label = 'shared-from' if depth == 1 else f'shared-from[{depth}]'
        state = ' · incomplete' if shared.get('incomplete') else ''
        lines.append(f'     {label}: {_line(shared.get("author_name") or "unavailable")} · {_time(shared.get("created_at"))}'
                     f'{state} · url: {_handle(shared.get("url"))} · author: {_handle(shared.get("author_url"))} · '
                     f'{_text(shared, chars)[0]}')
        shared, depth = shared.get('shared_post'), depth + 1
    if record.get('media'):
        lines.append('     media: ' + _media(record))
    lines.append(f'     url: {_handle(record.get("url"))}   author: {_handle(record.get("author_url"))}')
    return '\n'.join(lines), False


def comment(record, index, parent_label, chars):
    depth = record.get('depth') or 0
    indent = '  ' * min(max(depth, 0), 10)
    parent = f' reply-to={parent_label or "unavailable"}' if depth else ''
    kinds = ','.join(_line(a.get('kind')) for a in record.get('attachments') or [])
    text, cut = _text(record, chars)
    tail = f'   replies {record["replies_handle"]}' if record.get('replies_handle') else ''
    return (f'{indent}[c{index}{parent}] {_line(record.get("author_name") or "unavailable")} · '
            f'{_time(record.get("created_at"))} · reactions={_count(record.get("reaction_count"))} '
            f'replies={_count(record.get("reply_count"))}\n'
            f'{indent}     {text}' + (f' · attachment={kinds}' if kinds else '') + '\n'
            f'{indent}     author: {_handle(record.get("author_url"))}{tail}'), cut


def entity(record, index):
    verified = {True: 'verified', False: 'unverified', None: 'verified=?'}[record.get('verified')]
    return (f'[e{index}] {_line(record["kind"])} id={_line(record["id"])} · {_line(record.get("name") or "unavailable")} '
            f'· {verified} · url: {_handle(record.get("url"))}'), False


def about(record):
    return f'{_line(record["section"])}: {_line(record["text"])}' + (f' ({_quote(record["url"])})' if record.get('url') else ''), False


def render_page(envelope, *, chars=None, command=None):
    """The text page of one result. chars None: the default; 0: everything received."""
    limit = DEFAULT_CHARS if chars is None else (None if chars == 0 else chars)
    results = envelope.get('results') or []
    header = [_line(envelope.get('command') or command or '')]
    header += [f'{key}={_line(envelope[key])}' for key in ('sort', 'type') if envelope.get(key) is not None]
    header.append(f'{len(results)} shown')
    if envelope.get('sponsored_skipped'):
        header.append(f'sponsored_skipped={envelope["sponsored_skipped"]}')
    header += [f'stopped={_line(envelope.get("stop_reason"))}',
               f'requests={envelope.get("request_count", 0)}/{envelope.get("max_requests", 0)}']
    lines = [' · '.join(header)]
    window = envelope.get('window')
    if window:
        lines.append(f'window {window.get("since") or ""}..{window.get("until") or ""} · {_line(window["coverage"])}')
    labels = {r['id']: f'c{i}' for i, r in enumerate((r for r in results if 'post_id' in r), 1)}
    counts, cut = {'p': 0, 'c': 0, 'e': 0}, False
    for record in results:
        if 'post_id' in record:
            counts['c'] += 1
            text, was_cut = comment(record, counts['c'], labels.get(record.get('parent_id')), limit)
            cut |= was_cut
        elif 'section' in record:
            text, _ = about(record)
        elif record.get('kind') in ('person', 'page', 'group'):
            counts['e'] += 1
            text, _ = entity(record, counts['e'])
        else:
            counts['p'] += 1
            post_limit = None if command == 'post' else limit
            text, _ = post(record, counts['p'], post_limit)
        lines.append(text)
    lines += ['coverage: ' + _line(note) for note in envelope.get('coverage') or []]
    if envelope.get('error'):
        lines.append(f'coverage: incomplete — {_line(envelope.get("message"))} fix: {_line(envelope.get("fix"))}')
    if cut and envelope.get('detail'):
        lines.append('detail: ' + envelope['detail'])
    if envelope.get('next'):
        lines.append('more: ' + envelope['next'])
    return '\n'.join(lines)


def render_summary(envelope):
    """The one line --out prints."""
    parts = [_line(envelope.get('command') or ''), f'{envelope.get("count", 0)} saved to {json.dumps(envelope.get("out"), ensure_ascii=False)}']
    if 'sponsored_skipped' in envelope:
        parts.append(f'sponsored_skipped={envelope["sponsored_skipped"]}')
    parts += [f'stopped={envelope.get("stop_reason")}', f'requests={envelope.get("request_count", 0)}/{envelope.get("max_requests", 0)}']
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
