"""The dense text page: a header naming scope and cost, the window, records, coverage, more:.

All clipping, labels, markdown flattening and local-time formatting live here; the records themselves are never
shortened (--json and --out keep the received text).
"""
import html
import json
import re
import unicodedata
from datetime import datetime, timezone

DEFAULT_CHARS = 180
_URL = re.compile(r'(\()?(https?://[^\s)\]]+)(?(1)\))')


def _line(value):
    return str(value).replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ').replace(' ', ' ')\
        .replace(' ', ' ')


def _quote(value):
    return json.dumps(_line(value), ensure_ascii=False)


def _count(value):
    return '?' if value is None else (str(int(value)) if float(value).is_integer() else str(value))


def _time(value):
    if not value:
        return 'undated'
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().isoformat(timespec='minutes')


def _paragraph(lines):
    """One paragraph's lines → text, with > quote runs kept apart as ❝…❞ (a > line starts a quote that runs until the
    next blank line, as Reddit's markdown reads it)."""
    parts, quote, own = [], [], []
    for line in lines:
        if re.match(r'^[ \t]*>', line):
            if own:
                parts.append(' '.join(own))
                own = []
            quote.append(re.sub(r'^[ \t]*(?:>[ \t]?)+', '', line))
        elif quote:
            quote.append(line)  # lazy continuation of the quote
        else:
            own.append(line)
    if own:
        parts.append(' '.join(own))
    if quote:
        parts.append('❝' + ' '.join(' '.join(quote).split()) + '❞')
    return ' '.join(' '.join(part.split()) for part in parts if part.strip())


def flatten(value):
    """Reddit markdown → one dense line: entities decoded, format characters dropped, [text](url) as text (url) (the
    address alone when the text is the address), table rules and emphasis marks dropped, paragraphs joined with ⏎,
    quotes as ❝…❞, each address once."""
    value = html.unescape(str(value or ''))
    value = ''.join(c for c in value if unicodedata.category(c) != 'Cf' and not '︀' <= c <= '️')

    def link(match):
        label, address = match[1], match[2]
        return address if label.strip() == address else f'{label} ({address})'
    value = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', link, value)
    value = re.sub(r'(?m)^\s*\|?\s*[-:]+(?:\s*\|\s*[-:]+)+\s*\|?\s*$', '', value)
    value = re.sub(r'\*{1,3}|~~|`{1,3}|\^', '', value)
    paragraphs = [_paragraph(part.split('\n')) for part in re.split(r'\n\s*\n', value.replace('\r\n', '\n'))]
    value = ' ⏎ '.join(p for p in paragraphs if p)
    seen = set()

    def once(match):
        if match[2] in seen:
            return ''  # a repeated address goes, with the parentheses a link put around it
        seen.add(match[2])
        return match[0]
    value = _URL.sub(once, value)
    return ' '.join(value.split())


def _text(text, chars, label='text'):
    """text[N of M chars shown]: "…" """
    text = flatten(text)
    shown = text if not chars else text[:chars]
    suffix = '…' if len(shown) < len(text) else ''
    return f'{label}[{len(shown)} of {len(text)} chars shown]: {_quote(shown + suffix)}'


def _markers(record):
    marks = []
    if record.get('is_op'):
        marks.append('OP')
    if record.get('distinguished') in ('moderator', 'admin'):
        marks.append({'moderator': 'mod', 'admin': 'admin'}[record['distinguished']])
    for key in ('pinned', 'nsfw', 'spoiler', 'locked', 'archived', 'collapsed', 'controversial'):
        if record.get(key):
            marks.append(key)
    if record.get('collapsed_reason') == 'LOW_SCORE':
        marks.append('low score')
    if record.get('removed'):
        marks.append('deleted' if record['removed'] == 'deleted' else f'removed ({record["removed"]})'
                     if record['kind'] == 'post' and record['removed'] != 'removed' else 'removed')
    if record.get('edited_at'):
        marks.append('edited')
    if record.get('contest_mode'):
        marks.append('contest mode (random order, scores hidden)')
    return marks


def post(record, label, chars, full=False):
    head = [f'r/{record.get("subreddit")}', f'u/{record.get("author")}', _time(record.get('created_at')),
            record.get('post_type', 'link'),
            f'score={_count(record.get("score"))}' + (f' ({record["upvote_ratio"]:.0%})'
                                                      if record.get('upvote_ratio') is not None else ''),
            f'comments={_count(record.get("num_comments"))}']
    if record.get('flair'):
        head.append(f'flair={_quote(record["flair"])}')
    head += _markers(record)
    if record.get('num_crossposts'):
        head.append(f'crossposts={record["num_crossposts"]}')
    lines = [f'[{label}] ' + ' · '.join(head), '     title: ' + _quote(flatten(record.get('title')))]
    if record.get('text'):
        lines.append('     ' + _text(record['text'], None if full else chars))
    for media in record.get('media') or []:
        lines.append('     media: ' + _quote(media.get('url', '')) + (' caption: ' + _quote(flatten(media['caption']))
                                                                     if media.get('caption') else ''))
    poll = record.get('poll')
    if poll:
        lines.append('     poll: ' + ' · '.join(f'{_quote(o["text"])}={_count(o.get("vote_count"))}'
                                                for o in poll.get('options') or [])
                     + f' · total={_count(poll.get("total_vote_count"))}')
    original = record.get('crosspost')
    if original:
        lines.append(f'     crosspost of: r/{original.get("subreddit")} · u/{original.get("author")} · '
                     f'{_quote(flatten(original.get("title")))} · {original.get("url")}')
    if record.get('post_type') not in ('self', 'crosspost', 'gallery', 'poll') and record.get('link_url') \
            and record.get('link_url') != record.get('url'):
        lines.append(f'     link: {record["link_url"]} · {record.get("domain", "")}')
    lines.append(f'     url: {record.get("url")}')
    return '\n'.join(lines)


def comment(record, label, chars, labels, context=False):
    indent = '  ' * min(max(record.get('depth') or 0, 0), 20)
    score = 'score hidden' if record.get('score_hidden') else f'score={_count(record.get("score"))}'
    head = [f'u/{record.get("author")}' if record.get('author') != '[deleted]' else '[deleted]',
            _time(record.get('created_at')), score]
    if record.get('author_flair'):
        head.append(f'flair={_quote(record["author_flair"])}')
    head += _markers(record)
    parent = labels.get(record.get('parent_id'))
    if parent:
        head.append(f'reply-to={parent}')
    if context:
        head.append('context')
    if record.get('anchor'):
        head.append('linked')
    lines = [f'{indent}[{label}] ' + ' · '.join(head), f'{indent}     ' + _text(record.get('text'), chars)]
    for media in record.get('media') or []:
        lines.append(f'{indent}     media: ' + _quote(media.get('url', '')))
    lines.append(f'{indent}     url: {record.get("url")}')
    return '\n'.join(lines)


def community(record, label, chars):
    head = [f'r/{record.get("name")}', f'{_count(record.get("subscribers"))} subscribers',
            f'{_count(record.get("active"))} active', record.get('visibility') or '?']
    if record.get('nsfw'):
        head.append('nsfw')
    if record.get('created_at'):
        head.append('since ' + record['created_at'][:10])
    lines = [f'[{label}] ' + ' · '.join(head)]
    if record.get('title'):
        lines.append('     title: ' + _quote(flatten(record['title'])))
    if record.get('text'):
        lines.append('     ' + _text(record['text'], chars))
    if record.get('description') and 'rules' in record:
        lines.append('     ' + _text(record['description'], chars, 'sidebar'))
    for number, rule in enumerate(record.get('rules') or [], 1):
        lines.append(f'     rule {number}: {_quote(flatten(rule.get("name")))} · '
                     + _text(rule.get('text'), chars, 'text') + (f' · applies to {rule["applies_to"]}'
                                                                 if rule.get('applies_to') else ''))
    lines.append(f'     url: {record.get("url")}')
    return '\n'.join(lines)


def user(record, label, chars):
    head = [f'u/{record.get("name")}', f'post_karma={_count(record.get("post_karma"))}',
            f'comment_karma={_count(record.get("comment_karma"))}',
            'since ' + (record.get('created_at') or '?')[:10]]
    head += [key for key in ('moderator', 'admin', 'verified') if record.get(key)]
    lines = [f'[{label}] ' + ' · '.join(head)]
    if record.get('text'):
        lines.append('     ' + _text(record['text'], chars, 'profile'))
    lines.append(f'     url: {record.get("url")}')
    return '\n'.join(lines)


def _header(envelope, command, shown):
    header = [_line(envelope.get('command') or command or '')]
    header += [f'{key}={_line(envelope[key])}' for key in ('sort', 'time', 'type', 'collection', 'within')
               if envelope.get(key) is not None]
    if shown is not None:
        header.append(f'{shown} shown')
    header += [f'stopped={_line(envelope.get("stop_reason"))}',
               f'requests={envelope.get("request_count", 0)}/{envelope.get("max_requests", 0)}']
    for name, bucket in sorted((envelope.get('reddit_window') or {}).items()):
        label = 'reddit window' if name == 'general' else f'reddit {name} window'
        if bucket.get('status') == 'known':
            header.append(f'{label} {_count(bucket["remaining"])}/{_count(bucket["limit"])}, resets in '
                          f'{bucket["resets_in"]}s')
        elif bucket.get('status') == 'unmetered':
            header.append(f'{label} not reported')
    if envelope.get('slowed'):
        header.append(f'slowed: Reddit\'s window is running low, requests were spaced up to {envelope["slowed"]}s '
                      'apart')
    account = envelope.get('account')
    if account and not account.get('checked'):
        header.append(f'read earlier as u/{account["observed"]}' if account.get('observed') else 'account not checked')
    return header


def _thread_line(thread):
    return (f'thread: {_count(thread.get("reported"))} comments reported (deleted and removed included) · '
            f'{thread.get("received", 0)} received · {thread.get("shown_now", 0)} shown now '
            f'({thread.get("shown", 0)} shown so far) · {thread.get("hidden_by_depth", 0)} received but deeper than '
            f'--depth · {thread.get("unexpanded", 0)} not yet expanded (at least {thread.get("min_requests", 0)} '
            f'requests) · {thread.get("missing", 0)} asked for but never sent · sort={thread.get("sort")} (the order '
            'within each batch, not across batches)'
            + (f' · suggested_sort={thread["suggested_sort"]}' if thread.get('suggested_sort') else '')
            + (' · contest mode: random order, scores hidden' if thread.get('contest_mode') else '')
            + f' · read {thread.get("observed_at", "?")}'
            + (f', expanded {thread["expanded_at"]}' if thread.get('expanded_at') else ''))


def render_page(envelope, *, chars=None, command=None):
    """The text page of one result. chars None: the default; 0: everything received."""
    limit = DEFAULT_CHARS if chars is None else (None if chars == 0 else chars)
    results = envelope.get('results') or []
    thread = envelope.get('thread')
    shown = sum(1 for r in results if r.get('kind') == 'comment' and not r.get('context')) if thread else len(results)
    lines = [' · '.join(_header(envelope, command, shown))]
    window = envelope.get('window')
    if window:
        lines.append(f'window {window.get("since") or ""}..{window.get("until") or ""} {window.get("tz") or ""} · '
                     f'{_line(window["coverage"])}')
    if thread:
        lines.append(_thread_line(thread))
    labels, counts = {}, {'p': 0, 'c': 0, 's': 0, 'u': 0}
    for record in results:
        kind = record.get('kind')
        prefix = {'post': 'p', 'comment': 'c', 'subreddit': 's', 'user': 'u'}.get(kind, 'p')
        counts[prefix] += 1
        label = f'{prefix}{counts[prefix]}'
        if kind == 'comment':
            lines.append(comment(record, label, limit, labels, context=bool(record.get('context'))))
        elif kind == 'subreddit':
            lines.append(community(record, label, limit))
        elif kind == 'user':
            lines.append(user(record, label, limit))
        else:
            lines.append(post(record, label, limit, full=command in ('post', 'comments')))
        labels[record.get('id')] = label
    lines += ['coverage: ' + _line(note) for note in envelope.get('coverage') or []]
    if envelope.get('error'):
        lines.append(f'coverage: incomplete — {_line(envelope.get("message"))} fix: {_line(envelope.get("fix"))}')
    elif envelope.get('message') and envelope.get('stop_reason') in ('budget', 'window_spent', 'probe_pending'):
        lines.append(f'coverage: stopped — {_line(envelope["message"])}')
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
    if envelope.get('thread'):
        parts.append(_thread_line(envelope['thread']))
    if envelope.get('coverage'):
        parts.append('coverage: ' + '; '.join(_line(c) for c in envelope['coverage']))
    if envelope.get('next'):
        parts.append('resume: ' + envelope['next'])
    if envelope.get('error'):
        parts.append(f'error={envelope["error"]} fix={_line(envelope.get("fix"))}')
    return ' · '.join(parts)
