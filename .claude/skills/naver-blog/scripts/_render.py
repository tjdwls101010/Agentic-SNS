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


def head_line(parts):
    """A header is one line: any value that carries a newline is folded like body text."""
    return ' · '.join(text(part, 0) for part in parts if part)


def post_lines(post, label, chars):
    head = [tagged(label, str(post.get('id') or '').removeprefix('post:')),
            post.get('nickname') or post.get('blog_name'), stamp(post.get('created_at')),
            post.get('category_name')]
    tags = post.get('tags')
    if tags:
        head.append('tags: ' + (', '.join(tags) if isinstance(tags, list) else str(tags)))
    head += counts(post, [('like_count', 'likes'), ('comment_count', 'comments'), ('view_count', 'views')])
    head += post.get('labels') or []
    lines = [head_line(head)]
    if post.get('title'):
        lines.append('     ' + quote(post['title']))
    body = post.get('body')
    if body:
        # The coverage label rides on the body line, where a summary is actually being written.
        coverage = body.get('coverage') or {}
        reduced = (coverage.get('partial', 0) + coverage.get('empty', 0))
        marker = ('text[legacy]' if not coverage.get('components') else
                  'text[full]' if not reduced else
                  f'text[partial: {reduced} of {coverage["components"]} components reduced]')
        lines.append('     ' + marker + ': ' + quote(body.get('text')))
        if coverage.get('unhandled'):
            lines.append('     unhandled: ' + ', '.join(coverage['unhandled']))
    else:
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
    lines = [head_line(head)]
    if blog.get('description'):
        lines.append('     ' + quote(blog['description']))
    if blog.get('url'):
        lines.append('     url: ' + quote(blog['url']))
    return lines


def comment_lines(comment, label, chars, shown=None):
    indent = '  ' if comment.get('reply_level', 1) > 1 else ''
    parent = comment.get('parent_comment_no')
    # Its own number always stays: a reply is something a reader may want to point at too.
    tag = f'{label} #{comment.get("comment_no")}'
    if parent:
        # Naming the parent's number lets a reader ask for it, and saying it is absent keeps
        # an indent from implying a quote that is not in front of the reader.
        here = parent in shown if shown is not None else comment.get('parent_shown', True)
        tag += f' reply-to=#{parent}' + ('' if here else ' (parent not shown)')
    head = [tagged(tag, comment.get('author'))]
    if comment.get('author_blog_id'):
        head.append('blog: ' + comment['author_blog_id'])
    head.append(stamp(comment.get('created_at')))
    head += counts(comment, [('like_count', 'likes'), ('reply_count', 'replies')])
    head += comment.get('labels') or []
    lines = [indent + head_line(head)]
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
    return [head_line(head)]


def category_lines(category):
    head = ['  ' * min(category.get('depth', 0), 6)
            + tagged(category.get('category_no'), category.get('name'))]
    if category.get('post_count') is not None:
        head.append(f'{category["post_count"]} posts')
    if not category.get('open', True):
        head.append('closed')
    return [head_line(head)]


def record_lines(record, label, chars, shown=None):
    """Dispatch on the namespaced id, so one renderer serves every listing."""
    kind = str(record.get('id') or '').split(':', 1)[0]
    if kind == 'post':
        return post_lines(record, label, chars)
    if kind == 'blog':
        return blog_lines(record, label)
    if kind == 'comment':
        return comment_lines(record, label, chars, shown)
    if kind == 'buddy':
        return buddy_lines(record, label)
    if kind == 'category':
        return category_lines(record)
    if kind == 'topic':
        return [head_line([tagged(record.get('seq'), record.get('name')), record.get('group')])]
    return [f'[{label}] ' + quote(record.get('name') or record.get('title') or record.get('id'))]


def header(result, args):
    budget = result.get('budget') or {}
    parts = [args.command]
    # A context value is a label, not a flag: "True" in a header tells the reader nothing.
    parts += [str(value) for value in (result.get('context') or {}).values()
              if value is not None and not isinstance(value, bool)]
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
    coverage = result.get('coverage')
    if coverage:
        parts.append(f'{coverage["components"]} components ({coverage["full"]} full)')
        parts.append(f'{len(result.get("images") or [])} images' if result.get('images') else None)
        parts = [part for part in parts if part]
    parts.append(f'fetched {result.get("fetched_bytes", 0) / 1000:.0f}KB')
    parts.append(f'local budget {budget.get("used", 0)} of {budget.get("limit", 0)}'
                 f' (window {budget.get("window_used", 0)}/{budget.get("window_limit", 120)})')
    return head_line(parts)


def render(result, args):
    lines = [header(result, args)]
    for note in result.get('warnings') or []:
        lines.append(text(note, 0))
    for section in result.get('sections') or []:
        lines.extend(section_lines(section, args))
    records = result.get('results') or []
    # "Parent not shown" is about this page of output, not about what the server returned.
    shown = {record.get('comment_no') for record in records if record.get('comment_no')}
    for index, record in enumerate(records, 1):
        lines.extend(record_lines(record, result.get('label_prefix', 'p') + str(index),
                                  args.chars, shown))
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
    shown = {record.get('comment_no') for record in records if record.get('comment_no')}
    for index, record in enumerate(records, 1):
        lines.extend('  ' + line for line in
                     record_lines(record, section.get('prefix', 's') + str(index), args.chars, shown))
    return lines
