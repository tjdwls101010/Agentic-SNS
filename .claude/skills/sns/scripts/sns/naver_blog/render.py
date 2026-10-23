"""Naver Blog's record lines for the shared text page: posts (a list item, or read in full), comments, blogs, neighbors,
categories, topics, clips, keywords, groups, resolved links and saved pictures, and the sections of a composite
command. All clipping lives here; records are never shortened (--json and --out keep everything). An absent field is
silence; a field this reader could not determine says unknown. The page's frame (first line, window, coverage, more:)
is the shared render's.
"""
from sns.render import image as image_line
from sns.text import limit_of, line, quote

# The label of each kind: [p1] posts, [c1] comments, [b1] blogs and neighbors, [k1] keywords ...
PREFIX = {'post': 'p', 'comment': 'c', 'blog': 'b', 'buddy': 'b', 'topic': 't', 'clip': 'v', 'keyword': 'k',
          'group': 'g', 'image': 'i', 'link': 'l'}


def _clip(value, chars):
    text = line(value if value is not None else '')
    return text[:chars] + '…' if chars and len(text) > chars else text


def _counts(record, pairs):
    return [f'{label}={record[key]}' for key, label in pairs if record.get(key) is not None]


def _join(parts):
    return ' · '.join(line(part) for part in parts if part not in (None, '', []))


def post_lines(post, label, chars):
    head = [f'[{label}] {post.get("blog_id")}/{post.get("log_no")}', post.get('nickname') or post.get('blog_name'),
            post.get('created_at') or 'undated', post.get('category_name')]
    head += _counts(post, [('like_count', 'likes'), ('comment_count', 'comments'), ('view_count', 'views')])
    head += post.get('labels') or []
    lines = [_join(head)]
    if post.get('title'):
        lines.append('     ' + quote(post['title']))
    if post.get('summary'):
        lines.append('     excerpt (Naver\'s, cut by length): ' + quote(_clip(post['summary'], chars)))
    lines.append('     url: ' + post['url'])
    return lines


def post_read_lines(post, label):
    """One post read in full: its head, flags, the whole body, its links."""
    likes = None
    if post.get('like_count') is not None:
        reactions = post.get('reactions') or {}
        likes = f'likes={post["like_count"]}' + (' (' + ' · '.join(f'{k} {v}' for k, v in reactions.items()) + ')'
                                                if len(reactions) > 1 else '')
    head = [f'[{label}] {post.get("blog_id")}/{post.get("log_no")}', post.get('created_at') or 'undated',
            post.get('category_name'), likes,
            f'comments={post["comment_count"]}' if post.get('comment_count') is not None else None]
    lines = [_join(head)]
    if post.get('title'):
        lines.append('     ' + quote(post['title']))
    tags = post.get('tags')
    flags = ['tags: ' + (', '.join(tags) if tags else 'none') if tags != 'unknown' else 'tags: unknown (the page did '
                                                                                       'not say)']
    if post.get('own_money') is not None:
        cards = post.get('own_money_cards') or []
        flags.append(('Naver 내돈내산 인증 card: ' + '; '.join(' '.join(v for v in (c.get('category'), c.get('date')) if v)
                                                         for c in cards)) if cards else 'no Naver 내돈내산 인증 card')
    if post.get('has_product'):
        flags.append(f'product cards: {post.get("product_count") or "yes"}')
    lines.append('     ' + _join(flags))
    coverage = post.get('coverage') or {}
    lines.append('     ' + coverage.get('label', 'text[legacy]') + ':' + (
        f' (unhandled: {", ".join(coverage["unhandled"])})' if coverage.get('unhandled') else ''))
    for block in post.get('lines') or []:
        lines += ['       ' + part for part in str(block).split('\n') if part.strip()]
    if post.get('links'):
        lines.append('     links:')
        for link in post['links']:
            where = link.get('host') or '?'
            if link.get('link_id'):
                where += f', id {link["link_id"]}'
            lines.append(f'       {link["url"]} ({where})' + (f' {quote(link["text"])}' if link.get('text') else ''))
    lines.append('     url: ' + post['url'])
    return lines


def comment_lines(comment, label, chars):
    indent = '  ' * min(comment.get('depth') or 0, 3)
    tag = f'[{label}] #{comment.get("comment_no")}'
    if comment.get('parent_comment_no'):
        tag += f' reply-to=#{comment["parent_comment_no"]}' + ('' if comment.get('parent_shown', True)
                                                               else ' (parent not shown)')
    head = [tag, comment.get('author'), f'blog: {comment["author_blog_id"]}' if comment.get('author_blog_id') else None,
            comment.get('created_at') or 'undated']
    head += _counts(comment, [('like_count', 'likes'), ('reply_count', 'replies')]) + (comment.get('labels') or [])
    lines = [indent + _join(head)]
    if comment.get('text'):
        lines.append(indent + '     ' + quote(_clip(comment['text'], chars)))
    return lines


def blog_lines(blog, label):
    head = [f'[{label}] {blog.get("blog_id")}', blog.get('name'), blog.get('nickname')]
    head += _counts(blog, [('buddy_count', 'neighbors'), ('today_visitors', 'today'), ('total_visitors', 'visits'),
                           ('post_count', 'posts'), ('clip_count', 'clips')])
    head += ['official' if blog.get('official') else None, 'market' if blog.get('market') else None,
             blog.get('relation'), *(blog.get('labels') or []), blog.get('directory')]
    lines = [_join(head)]
    if blog.get('description'):
        lines.append('     ' + quote(blog['description']))
    lines.append('     url: ' + blog['url'])
    return lines


def buddy_lines(buddy, label):
    return [_join([f'[{label}] {buddy.get("blog_id")}', buddy.get('nickname') or buddy.get('name'),
                   'mutual' if buddy.get('mutual') else None, 'official' if buddy.get('official') else None,
                   f'group {buddy["group_id"]}' if buddy.get('group_id') else None,
                   f'updated {buddy["updated_at"]}' if buddy.get('updated_at') else None])]


def category_lines(category):
    return ['  ' * min(category.get('depth') or 0, 6) + _join([
        f'[{category.get("category_no")}] {category.get("name")}',
        f'{category["post_count"]} posts' if category.get('post_count') is not None else None,
        None if category.get('open', True) else 'closed'])]


def link_lines(record, label):
    where = record.get('destination')
    text = f'[{label}] {record.get("link")} → HTTP {record.get("status")}'
    if where:
        text += f' {where["url"]} ({where["host"]}' + (f', id {where["link_id"]}' if where.get('link_id') else '') + ')'
    else:
        text += ' (no destination)'
    return [text] + ([f'     post {record["post"]}'] if record.get('post') else [])


def record_lines(record, label, chars):
    kind = record.get('kind')
    if kind == 'post':
        return post_read_lines(record, label) if 'lines' in record else post_lines(record, label, chars)
    if kind == 'comment':
        return comment_lines(record, label, chars)
    if kind == 'blog':
        return blog_lines(record, label)
    if kind == 'buddy':
        return buddy_lines(record, label)
    if kind == 'category':
        return category_lines(record)
    if kind == 'clip':
        return [_join([f'[{label}] {record.get("blog_id")}/clip/{record.get("doc_no")}', record.get('nickname'),
                       record.get('created_at') or 'undated',
                       f'{record["play_seconds"]}s' if record.get('play_seconds') is not None else None]),
                '     ' + quote(record.get('title')), '     url: ' + record['url']]
    if kind == 'keyword':
        return [f'[{label}] {record.get("keyword")}']
    if kind == 'group':
        return [_join([f'[{label}] group {record.get("group_id")}', record.get('name')])]
    if kind == 'link':
        return link_lines(record, label)
    if kind == 'image':
        return image_line(record, label).split('\n')
    if kind == 'topic':
        return [_join([f'[{record.get("seq")}] {record.get("name")}', record.get('group')])]
    return [f'[{label}] ' + _join(str(value) for key, value in record.items() if key != 'id' and value not in (None, ''))]


def records_lines(records, chars, indent=''):
    lines, counters = [], {}
    for record in records:
        prefix = PREFIX.get(record.get('kind'), 'r')
        counters[prefix] = counters.get(prefix, 0) + 1
        lines += [indent + text for text in record_lines(record, f'{prefix}{counters[prefix]}', chars)]
    return lines


def section_lines(section, chars):
    """One section of a composite command: its records, 'none', or why it is unavailable. A section that read nothing
    for the page (its data is null) draws nothing."""
    if not section.get('ok'):
        return [f'{section["name"]}: unavailable — {line(section["error"]["message"])}']
    if section.get('data') is None:
        return []
    if not section['data']:
        return [f'{section["name"]}: none']
    return [f'{section["name"]}:'] + records_lines(section['data'], chars, '  ')


def render(envelope, chars, command):
    """The record lines of a text page, and the number of records they draw. chars None: the default length; 0: all."""
    limit = limit_of(chars)
    sections = envelope.get('sections')
    if sections is None:
        return records_lines(envelope.get('results') or [], limit)
    lines = []
    for section in sections:
        lines += section_lines(section, limit)
    return lines, sum(len(s.get('data') or []) for s in sections if s.get('ok'))
