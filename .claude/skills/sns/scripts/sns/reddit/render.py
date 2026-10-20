"""Reddit's record lines for the shared text page: markdown flattened to one dense line, posts, comments (indented by
depth), communities, users and wiki pages, and the thread: line. The records themselves are never shortened (--json and
--out keep the received text); the page's frame (first line, window, coverage, more:) is the shared render's.
"""
import html
import re
import unicodedata

from sns.text import count, limit_of, quote, shown, time

_URL = re.compile(r'(\()?(https?://[^\s)\]]+)(?(1)\))')


def _paragraph(lines):
    """One paragraph's lines → text, with > quote runs kept apart as ❝…❞ (a > line starts a quote that runs until the
    next blank line, as Reddit's markdown reads it)."""
    parts, quoted, own = [], [], []
    for line in lines:
        if re.match(r'^[ \t]*>', line):
            if own:
                parts.append(' '.join(own))
                own = []
            quoted.append(re.sub(r'^[ \t]*(?:>[ \t]?)+', '', line))
        elif quoted:
            quoted.append(line)  # lazy continuation of the quote
        else:
            own.append(line)
    if own:
        parts.append(' '.join(own))
    if quoted:
        parts.append('❝' + ' '.join(' '.join(quoted).split()) + '❞')
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


def _text(value, chars, label='text'):
    """text[N of M chars shown]: "…" over the flattened text."""
    return shown(flatten(value), chars, label)


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


def _media(item, indent=''):
    """One media line: its number, kind and size, the picture (or a video's poster) and the clip."""
    size = f' {item["width"]:g}x{item["height"]:g}' if item.get('width') and item.get('height') else ''
    parts = [f'{indent}     media {item.get("n")}: {item.get("kind")}{size}']
    if item.get('image_url'):
        parts.append('image: ' + quote(item['image_url']))
    if item.get('video_url'):
        parts.append('video: ' + quote(item['video_url']))
    if item.get('alt'):
        parts.append('caption: ' + quote(flatten(item['alt'])))
    return ' '.join(parts)


def post(record, label, chars, full=False):
    head = [f'r/{record.get("subreddit")}', f'u/{record.get("author")}', time(record.get('created_at')),
            record.get('post_type', 'link'),
            f'score={count(record.get("score"))}' + (f' ({record["upvote_ratio"]:.0%})'
                                                     if record.get('upvote_ratio') is not None else ''),
            f'comments={count(record.get("num_comments"))}']
    if record.get('flair'):
        head.append(f'flair={quote(record["flair"])}')
    head += _markers(record)
    if record.get('num_crossposts'):
        head.append(f'crossposts={record["num_crossposts"]}')
    lines = [f'[{label}] ' + ' · '.join(head), '     title: ' + quote(flatten(record.get('title')))]
    if record.get('text'):
        lines.append('     ' + _text(record['text'], None if full else chars))
    lines += [_media(item) for item in record.get('media') or []]
    poll = record.get('poll')
    if poll:
        lines.append('     poll: ' + ' · '.join(f'{quote(o["text"])}={count(o.get("vote_count"))}'
                                                for o in poll.get('options') or [])
                     + f' · total={count(poll.get("total_vote_count"))}')
    original = record.get('crosspost')
    if original:
        lines.append(f'     crosspost of: r/{original.get("subreddit")} · u/{original.get("author")} · '
                     f'{quote(flatten(original.get("title")))} · {original.get("url")}')
    if record.get('post_type') not in ('self', 'crosspost', 'gallery', 'poll') and record.get('link_url') \
            and record.get('link_url') != record.get('url'):
        lines.append(f'     link: {record["link_url"]} · {record.get("domain", "")}')
    lines.append(f'     url: {record.get("url")}')
    return '\n'.join(lines)


def comment(record, label, chars, labels, context=False):
    indent = '  ' * min(max(record.get('depth') or 0, 0), 20)
    score = 'score hidden' if record.get('score_hidden') else f'score={count(record.get("score"))}'
    head = [f'u/{record.get("author")}' if record.get('author') != '[deleted]' else '[deleted]',
            time(record.get('created_at')), score]
    if record.get('author_flair'):
        head.append(f'flair={quote(record["author_flair"])}')
    head += _markers(record)
    parent = labels.get(record.get('parent_id'))
    if parent:
        head.append(f'reply-to={parent}')
    if context:
        head.append('context')
    if record.get('anchor'):
        head.append('linked')
    lines = [f'{indent}[{label}] ' + ' · '.join(head), f'{indent}     ' + _text(record.get('text'), chars)]
    lines += [_media(item, indent) for item in record.get('media') or []]
    lines.append(f'{indent}     url: {record.get("url")}')
    return '\n'.join(lines)


def community(record, label, chars):
    head = [f'r/{record.get("name")}', f'{count(record.get("subscribers"))} subscribers',
            f'{count(record.get("active"))} active', record.get('visibility') or '?']
    if record.get('nsfw'):
        head.append('nsfw')
    if record.get('created_at'):
        head.append('since ' + record['created_at'][:10])
    lines = [f'[{label}] ' + ' · '.join(head)]
    if record.get('title'):
        lines.append('     title: ' + quote(flatten(record['title'])))
    if record.get('text'):
        lines.append('     ' + _text(record['text'], chars))
    if record.get('description') and 'rules' in record:
        lines.append('     ' + _text(record['description'], chars, 'sidebar'))
    for number, rule in enumerate(record.get('rules') or [], 1):
        lines.append(f'     rule {number}: {quote(flatten(rule.get("name")))} · '
                     + _text(rule.get('text'), chars, 'text') + (f' · applies to {rule["applies_to"]}'
                                                                 if rule.get('applies_to') else ''))
    if record.get('moderators') is not None:
        mods = record['moderators']
        lines.append('     moderators: ' + (', '.join(f'u/{m["name"]}' + (f' (flair={quote(m["flair"])})'
                                                                         if m.get('flair') else '') for m in mods)
                                            or 'none listed'))
    for pinned in record.get('pinned') or []:
        lines.append(f'     pinned: {quote(flatten(pinned.get("title")))} · {time(pinned.get("created_at"))} · '
                     f'u/{pinned.get("author")} · {pinned.get("url")}')
    lines.append(f'     url: {record.get("url")}')
    return '\n'.join(lines)


def wiki(record, label, chars):
    if record.get('kind') == 'wiki_index':
        lines = [f'[{label}] r/{record.get("subreddit")} wiki',
                 '     pages: ' + (', '.join(record.get('pages') or []) or 'none')]
        if record.get('settings_pages'):
            lines.append('     settings pages: ' + ', '.join(record['settings_pages']))
        lines.append(f'     url: {record.get("url")}')
        return '\n'.join(lines)
    head = [f'r/{record.get("subreddit")} wiki {record.get("page")}', f'revised {time(record.get("created_at"))}']
    if record.get('revised_by'):
        head[-1] += f' by u/{record["revised_by"]}'
    if record.get('reason'):
        head.append(f'note={quote(record["reason"])}')
    return '\n'.join([f'[{label}] ' + ' · '.join(head), '     ' + _text(record.get('text'), chars),
                      f'     url: {record.get("url")}'])


def user(record, label, chars):
    head = [f'u/{record.get("name")}', f'post_karma={count(record.get("post_karma"))}',
            f'comment_karma={count(record.get("comment_karma"))}',
            'since ' + (record.get('created_at') or '?')[:10]]
    head += [key for key in ('moderator', 'admin', 'verified') if record.get(key)]
    lines = [f'[{label}] ' + ' · '.join(head)]
    if record.get('text'):
        lines.append('     ' + _text(record['text'], chars, 'profile'))
    lines.append(f'     url: {record.get("url")}')
    return '\n'.join(lines)


def _thread_line(thread):
    return (f'thread: {count(thread.get("reported"))} comments reported (deleted and removed included) · '
            f'{thread.get("received", 0)} received · {thread.get("shown_now", 0)} shown now '
            f'({thread.get("shown", 0)} shown so far) · {thread.get("hidden_by_depth", 0)} received but deeper than '
            f'--depth · {thread.get("unexpanded", 0)} not yet expanded (at least {thread.get("min_requests", 0)} '
            f'requests) · {thread.get("missing", 0)} asked for but never sent · sort={thread.get("sort")} (the order '
            'within each batch, not across batches)'
            + (f' · suggested_sort={thread["suggested_sort"]}' if thread.get('suggested_sort') else '')
            + (' · contest mode: random order, scores hidden' if thread.get('contest_mode') else '')
            + f' · read {time(thread.get("observed_at"))}'
            + (f', expanded {time(thread["expanded_at"])}' if thread.get('expanded_at') else ''))


_LABELS = {'post': 'p', 'comment': 'c', 'subreddit': 's', 'user': 'u', 'wiki_page': 'w', 'wiki_index': 'w', 'reply': 'r'}


def reply(record, label, chars):
    head = [f'u/{record.get("author")}' if record.get('author') != '[deleted]' else '[deleted]',
            f'r/{record.get("subreddit")}', time(record.get('created_at')), (record.get('type') or '').replace('_', ' ')]
    if record.get('unread'):
        head.append('unread')
    return '\n'.join([f'[{label}] ' + ' · '.join(head), f'     on: {quote(record.get("post_title") or "")}',
                      '     ' + _text(record.get('text'), chars), f'     url: {record.get("url")}'])


def render(envelope, chars, command):
    """The record lines of a text page (preceded by the thread: line of a post or comments read). chars None: the
    default length; 0: everything received."""
    limit = limit_of(chars)
    lines = [_thread_line(envelope['thread'])] if envelope.get('thread') else []
    labels, counts = {}, {prefix: 0 for prefix in 'pcsuwr'}
    for record in envelope.get('results') or []:
        kind = record.get('kind')
        prefix = _LABELS.get(kind, 'p')
        counts[prefix] += 1
        label = f'{prefix}{counts[prefix]}'
        if kind == 'comment':
            full = record.get('anchor') and chars is None  # a comment link opens that comment in full
            lines.append(comment(record, label, None if full else limit, labels, context=bool(record.get('context'))))
        elif kind == 'subreddit':
            lines.append(community(record, label, limit))
        elif kind == 'user':
            lines.append(user(record, label, limit))
        elif kind == 'reply':
            lines.append(reply(record, label, limit))
        elif kind in ('wiki_page', 'wiki_index'):
            lines.append(wiki(record, label, None if chars is None else limit))
        else:
            lines.append(post(record, label, limit, full=command in ('post', 'comments')))
        labels[record.get('id')] = label
    return lines
