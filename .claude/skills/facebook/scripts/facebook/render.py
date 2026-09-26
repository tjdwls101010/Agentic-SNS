"""Dense text presentation; all clipping, labels and local time formatting live here."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def _data(value):
    if hasattr(value, 'shared_post'):
        return vars(value).copy()  # Keep the share chain shallow for iterative rendering.
    return value.to_dict() if hasattr(value, 'to_dict') else value


def _line(value) -> str:
    return str(value).replace('\r\n', '⏎').replace('\n', '⏎').replace('\r', '⏎').replace('\u2028', '⏎').replace('\u2029', '⏎')


def _quote(value) -> str:
    return json.dumps(_line(value), ensure_ascii=False)


def _handle(value) -> str:
    return _quote(value) if value else 'unavailable'


def _count(value) -> str:
    return '?' if value is None else str(value)


def _time(value, timezone=None) -> str:
    if not value:
        return 'undated'
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    zone = ZoneInfo(timezone) if isinstance(timezone, str) else timezone
    return value.astimezone(zone).isoformat(timespec='minutes')


def _text(data, chars) -> str:
    if chars is not None and chars < 0:
        raise ValueError('chars must be non-negative or None for full text')
    text = data.get('text') or ''
    shown = text if chars is None else text[:chars]
    state = 'truncated' if data.get('text_truncated') and not data.get('text_resolved') else 'complete'
    suffix = '…' if len(shown) < len(text) else ''
    return f'text[{len(shown)}/{len(text)} chars, {state}]: {_quote(shown + suffix)}'


def render_post(post, *, index=1, chars=180, timezone=None) -> str:
    data = _data(post)
    labels = [_line(data.get('author_name') or 'unavailable')]
    if data.get('created_at') or not data.get('sponsored'):
        labels.append(_time(data.get('created_at'), timezone))
    for flag in ('sponsored', 'pinned', 'incomplete'):
        if data.get(flag):
            labels.append(flag)
    labels += [data.get('type', 'unknown'),
               f'reactions={_count(data.get("reaction_count"))} comments={_count(data.get("comment_count"))} shares={_count(data.get("share_count"))}']
    lines = [f'[p{index}] ' + ' · '.join(labels), '     ' + _text(data, chars)]
    shared = data.get('shared_post')
    seen = {id(post)}
    depth = 1
    while shared is not None:
        if id(shared) in seen:
            lines.append('     shared-from: incomplete (cycle)')
            break
        seen.add(id(shared))
        shared_data = _data(shared)
        label = 'shared-from' if depth == 1 else f'shared-from[{depth}]'
        state = ' · incomplete' if shared_data.get('incomplete') else ''
        lines.append('     ' + label + ': ' + _line(shared_data.get('author_name') or 'unavailable')
                     + ' · ' + _time(shared_data.get('created_at'), timezone) + state
                     + ' · url: ' + _handle(shared_data.get('url')) + ' · ' + _text(shared_data, chars))
        shared = shared_data.get('shared_post')
        depth += 1
    lines.append(f'     url: {_handle(data.get("url"))}   author: {_handle(data.get("author_url"))}')
    return '\n'.join(lines)


def render_posts(posts, *, chars=180, timezone=None) -> str:
    return '\n'.join(render_post(post, index=i, chars=chars, timezone=timezone)
                     for i, post in enumerate(posts, 1))


def render_comment(comment, *, index=1, parent_label=None, chars=180, timezone=None) -> str:
    data = _data(comment)
    indent = '  ' * min(max(data.get('depth', 0), 0), 20)
    parent = f' reply-to={parent_label or "unavailable"}' if data.get('depth') else ''
    kinds = ','.join(_line(a.get('kind')) for a in data.get('attachments') or [])
    attached = f' · attachment={kinds}' if kinds else ''
    return (f'{indent}[c{index}{parent}] {_line(data.get("author_name") or "unavailable")} · '
            f'{_time(data.get("created_at"), timezone)} · reactions={_count(data.get("reaction_count"))} '
            f'replies={_count(data.get("reply_count"))}\n{indent}     {_text(data, chars)}{attached}\n'
            f'{indent}     author: {_handle(data.get("author_url"))}')


def render_comments(comments, *, chars=180, timezone=None) -> str:
    comments = [_data(c) for c in comments]
    labels = {c['id']: f'c{i}' for i, c in enumerate(comments, 1)}
    return '\n'.join(render_comment(c, index=i, parent_label=labels.get(c.get('parent_id')),
                                    chars=chars, timezone=timezone)
                     for i, c in enumerate(comments, 1))


def render_entity(entity, *, index=1) -> str:
    data = _data(entity)
    verified = {True: 'verified', False: 'unverified', None: 'verified=?'}[data.get('verified')]
    return (f'[e{index}] {_line(data["kind"])} id={_line(data["id"])} · '
            f'{_line(data.get("name") or "unavailable")} · {verified} · url: {_handle(data.get("url"))}')


def render_entities(entities) -> str:
    return '\n'.join(render_entity(entity, index=i) for i, entity in enumerate(entities, 1))


def render_about(fields) -> str:
    return '\n'.join(f'{_line(data["section"])}: {_line(data["text"])}'
                     + (f' ({_quote(data["url"])})' if data.get('url') else '')
                     for field in fields for data in [_data(field)])


def render_page(envelope, *, chars=180, timezone=None) -> str:
    """The text page of one result: a header naming scope and cost, the window, records, coverage, more:.

    ``chars=None`` shows full received text. Omitted timezone uses the machine's local zone.
    """
    results = [_data(result) for result in envelope['results']]
    header = [_line(envelope['command'])]
    header += [f'{key}={_line(envelope[key])}' for key in ('sort', 'type', 'section') if envelope.get(key) is not None]
    header.append(f'{len(results)} shown')
    if 'sponsored_skipped' in envelope:
        header.append(f'sponsored_skipped={envelope["sponsored_skipped"]}')
    header += [f'stopped={_line(envelope["stop_reason"])}',
               f'requests={envelope["request_count"]}/{envelope["max_requests"]}']
    lines = [' · '.join(header)]
    window = envelope.get('window')
    if window:
        lines.append(f'window {window.get("since") or ""}..{window.get("until") or ""} · {_line(window["coverage"])}')
    comments = [r for r in results if 'post_id' in r]
    labels = {c['id']: f'c{i}' for i, c in enumerate(comments, 1)}
    counts = {'p': 0, 'c': 0, 'e': 0}
    for data in results:
        if 'post_id' in data:
            counts['c'] += 1
            lines.append(render_comment(data, index=counts['c'], parent_label=labels.get(data.get('parent_id')),
                                        chars=chars, timezone=timezone))
        elif 'section' in data:
            lines.append(render_about([data]))
        elif data.get('kind') in {'person', 'page', 'group'}:
            counts['e'] += 1
            lines.append(render_entity(data, index=counts['e']))
        else:
            counts['p'] += 1
            lines.append(render_post(data, index=counts['p'], chars=chars, timezone=timezone))
    lines += ['coverage: ' + _line(note) for note in envelope.get('coverage') or []]
    if envelope.get('error'):
        lines.append(f'coverage: incomplete — {_line(envelope["message"])} fix: {_line(envelope["fix"])}')
    if envelope.get('next'):
        lines.append('more: ' + envelope['next'])  # executable: printed exactly as it runs
    return '\n'.join(lines)
