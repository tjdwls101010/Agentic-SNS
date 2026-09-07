"""One presentation boundary: whitespace, clipping, labels and next-hop handles.

What the reader pays for is tokens, so an item is a few lines, an empty field has no line
at all, and every line that could be the next command's argument carries a usable handle.
A field that is absent is silence; a field this reader could not determine says "unknown",
because those are different and the difference changes what a summary may claim.
"""
import json
import re

NEWLINE = '⏎'


def text(value, chars=180):
    """Fold a value onto one line; a folded newline stays visible as ⏎ rather than vanishing."""
    value = str(value if value is not None else '').replace('\r\n', '\n').replace('\r', '\n')
    value = re.sub(r'[​-‍﻿]', '', value)
    value = NEWLINE.join(re.sub(r'[^\S\n]+', ' ', line).strip() for line in value.split('\n'))
    value = re.sub(NEWLINE + r'{3,}', NEWLINE, value).strip(NEWLINE + ' ')
    return value[:chars] + '…' if chars and len(value) > chars else value


def quote(value):
    return json.dumps(text(value, 0), ensure_ascii=False)


def stamp(value):
    return value or 'undated'


def counts(record, pairs):
    """Only the counts Naver actually supplied; a missing count is not a zero."""
    return [f'{label}={record[key]}' for key, label in pairs if record.get(key) is not None]


def thousands(value):
    return f'{value:,}' if isinstance(value, int) else str(value)


def tagged(label, first):
    """The label sits against the handle, so the first column reads as one thing."""
    return f'[{label}] {first}' if label and first else (f'[{label}]' if label else first)


def post_lines(post, label, chars):
    head = [tagged(label, str(post.get('id') or '').removeprefix('post:')),
            post.get('nickname') or post.get('blog_name'), stamp(post.get('created_at')),
            post.get('category_name')]
    head += counts(post, [('like_count', 'likes'), ('comment_count', 'comments'), ('view_count', 'views')])
    head += post.get('labels') or []
    lines = [' · '.join(part for part in head if part)]
    if post.get('title'):
        lines.append('     ' + quote(post['title']))
    summary = text(post.get('summary'), chars)
    if summary:
        lines.append('     ' + quote(summary))
    if post.get('url'):
        lines.append('     url: ' + quote(post['url']))
    return lines


def blog_lines(blog, label=None):
    head = [tagged(label, blog.get('blog_id')), blog.get('name'), blog.get('nickname')]
    head += counts(blog, [('buddy_count', 'buddies'), ('today_visitors', 'today'),
                          ('total_visitors', 'visits'), ('post_count', 'posts')])
    if blog.get('official'):
        head.append('official')
    if blog.get('market'):
        head.append('market')
    if blog.get('relation'):
        head.append(blog['relation'])
    head += blog.get('labels') or []
    if blog.get('directory'):
        head.append(blog['directory'])
    lines = [' · '.join(part for part in head if part)]
    if blog.get('description'):
        lines.append('     ' + quote(blog['description']))
    if blog.get('url'):
        lines.append('     url: ' + quote(blog['url']))
    return lines


def comment_lines(comment, label, chars):
    indent = '  ' if comment.get('reply_level', 1) > 1 else ''
    parent = comment.get('parent_comment_no')
    tag = f'{label} #{comment.get("comment_no")}'
    if parent:
        # Naming the parent's own number lets a reader ask for it; saying it is absent
        # keeps an indent from implying a quote that is not on this page.
        tag = f'{label} reply-to=#{parent}' + ('' if comment.get('parent_shown') else ' (parent not shown)')
    head = [tagged(tag, comment.get('author'))]
    if comment.get('author_blog_id'):
        head.append('blog: ' + comment['author_blog_id'])
    head.append(stamp(comment.get('created_at')))
    head += counts(comment, [('like_count', 'likes'), ('reply_count', 'replies')])
    head += comment.get('labels') or []
    lines = [indent + ' · '.join(part for part in head if part)]
    body = text(comment.get('text'), chars)
    if body:
        lines.append(indent + '     ' + quote(body))
    return lines


def buddy_lines(buddy, label):
    head = [tagged(label, buddy.get('blog_id')), buddy.get('nickname') or buddy.get('name')]
    if buddy.get('mutual'):
        head.append('mutual')
    if buddy.get('official'):
        head.append('official')
    if buddy.get('updated_at'):
        head.append('updated ' + buddy['updated_at'])
    return [' · '.join(part for part in head if part)]


def category_lines(category):
    head = ['  ' * min(category.get('depth', 0), 6)
            + tagged(category.get('category_no'), category.get('name'))]
    if category.get('post_count') is not None:
        head.append(f'{category["post_count"]} posts')
    if not category.get('open', True):
        head.append('closed')
    return [' · '.join(part for part in head if part)]


def record_lines(record, label, chars):
    """Dispatch on the namespaced id, so one renderer serves every listing."""
    kind = str(record.get('id') or '').split(':', 1)[0]
    if kind == 'post':
        return post_lines(record, label, chars)
    if kind == 'blog':
        return blog_lines(record, label)
    if kind == 'comment':
        return comment_lines(record, label, chars)
    if kind == 'buddy':
        return buddy_lines(record, label)
    if kind == 'category':
        return category_lines(record)
    if kind == 'topic':
        return [' · '.join(part for part in [tagged(record.get('seq'), record.get('name')),
                                             record.get('group')] if part)]
    return [f'[{label}] ' + quote(record.get('name') or record.get('title') or record.get('id'))]


def header(result, args):
    budget = result.get('budget') or {}
    parts = [args.command]
    parts += [str(value) for value in (result.get('context') or {}).values() if value]
    sections = result.get('sections')
    if sections:
        # A composite command's answer is its sections, so a record count would say nothing.
        failed = [entry['name'] for entry in sections if not entry.get('ok')]
        parts.append(f'{len(sections)} sections' + (f', {len(failed)} unavailable' if failed else ''))
    else:
        shown = len(result.get('results') or [])
        total = result.get('shown_of')
        parts.append(f'{shown} of {total} shown' if total else f'{shown} shown')
    parts.append('stopped=' + str(result.get('stop_reason')))
    reported = result.get('reported_total')
    if reported is not None:
        # Naver's totals drift page to page and go to zero past the ceiling; say so where it is read.
        parts.append(f'reported≈{thousands(reported)}'
                     + (' (server figure, drifts)' if result.get('reported_is_unreliable', True) else ''))
    parts.append(f'fetched {result.get("fetched_bytes", 0) / 1000:.0f}KB')
    parts.append(f'local budget {budget.get("used", 0)} of {budget.get("limit", 0)}'
                 f' (window {budget.get("window_used", 0)}/{budget.get("window_limit", 120)})')
    return ' · '.join(parts)


def render(result, args):
    lines = [header(result, args)]
    for note in result.get('warnings') or []:
        lines.append(text(note, 0))
    for section in result.get('sections') or []:
        lines.extend(section_lines(section, args))
    for index, record in enumerate(result.get('results') or [], 1):
        lines.extend(record_lines(record, result.get('label_prefix', 'p') + str(index), args.chars))
    if result.get('out'):
        lines.append(f'{result.get("saved", 0)} saved · ' + quote(result['out'])
                     + (' · already complete' if result.get('already_complete') else ''))
    if result.get('next'):
        lines.append('more: ' + result['next'])
    if result.get('hops'):
        lines.append(' · '.join(result['hops']))
    if result.get('message'):
        lines.append(text(result['message'], 0) + ' · fix: ' + text(result.get('fix'), 0))
    return '\n'.join(lines)


def section_lines(section, args):
    """A composite command shows every section, including the ones that failed."""
    title = section['name']
    if not section.get('ok'):
        error = section.get('error') or {}
        return [f'{title}: unavailable — ' + text(error.get('message'), 0)]
    records = section.get('data') or []
    if isinstance(records, dict):
        records = [records]
    if not records:
        return [f'{title}: none']
    lines = [f'{title}:']
    for index, record in enumerate(records, 1):
        lines.extend('  ' + line for line in
                     record_lines(record, section.get('prefix', 's') + str(index), args.chars))
    return lines
