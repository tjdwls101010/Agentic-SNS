"""One presentation boundary for whitespace, clipping, counts and next-hop handles."""
import json
import re
from datetime import datetime


def text(value, chars=180):
    value = str(value or '').replace('\r\n', '\n').replace('\r', '\n')
    value = re.sub(r'[\u200b-\u200d\ufeff]', '', value)
    value = re.sub(r'\[([^]]+)\]\((https?://[^)]+)\)', r'\1 (\2)', value)
    value = re.sub(r'\*\*|__|`', '', value)
    value = '⏎'.join(re.sub(r'\s+', ' ', line).strip() for line in value.splitlines()).strip('⏎ ')
    return value[:chars] + '…' if chars and len(value) > chars else value


def quote(value):
    return json.dumps(text(value, 0), ensure_ascii=False)


def person(user):
    user = user or {}
    return '@' + user.get('username', 'unavailable') + (' (' + text(user['full_name'], 0) + ')' if user.get('full_name') else '') + (' ✓' if user.get('is_verified') else '') + (' · private' if user.get('private') else '')


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone().isoformat(timespec='minutes') if value else 'undated'


def post_lines(post, label, chars, full=False):
    indent = '  ' * min(post.get('depth', 0), 20)
    if post.get('unavailable'):
        return [indent + f'[{label}] [unavailable] ' + text(post.get('unavailable_reason'), 0)]
    flags = [person(post.get('author')), stamp(post.get('created_at'))]
    media = post.get('media_type', 'text')
    flags.append(media + (f'({len(post["media"])})' if media in ('image', 'carousel') and post.get('media') else ''))
    flags.extend(f'{label}={post[key]}' for key, label in [('like_count', 'likes'), ('reply_count', 'replies'),
                 ('repost_count', 'reposts'), ('quote_count', 'quotes')] if post.get(key) is not None)
    if post.get('relation'):
        flags.append(post['relation'])
    if post.get('is_pinned'):
        flags.append('pinned')
    lines = [indent + f'[{label}] ' + ' · '.join(flags)]
    content = text(post.get('text'), 0 if full else chars)
    if content:
        lines.append(indent + '     ' + ('text[full]: ' if full else '') + quote(content))
    for key, prefix in [('quoted_post', 'quoting'), ('reposted_post', 'repost of')]:
        nested = post.get(key)
        if nested:
            lines.append(indent + '     ' + prefix + ': ' + ('[unavailable]' if nested.get('unavailable') else
                person(nested.get('author')) + ': ' + quote(text(nested.get('text'), chars)) + ' (url: ' + quote(nested.get('url')) + ')'))
    preview = post.get('link_preview')
    if preview:
        lines.append(indent + '     link: ' + quote(preview.get('title')) + ' (' + text(preview.get('url'), 0) + ')')
    lines.append(indent + '     url: ' + quote(post.get('url')))
    return lines


def render(result, args):
    budget = result.get('budget', {})
    header = f'{args.command} · {len(result.get("results", []))} shown · stopped={result.get("stop_reason")} · '
    ctx = result.get('context', {})
    header += ''.join(f'{key}={ctx[key]} · ' for key in ('feed', 'tab', 'sort') if key in ctx)
    header += f'fetched {result.get("fetched_bytes", 0) / 1000000:.1f}MB · local budget {budget.get("remaining", 0)} of {budget.get("limit", 0)} (window {budget.get("window_used", 0)}/{budget.get("window_limit", 120)})'
    lines = [header]
    completeness = result.get('completeness')
    if completeness:
        c = completeness
        estimate = f'≈{c["unfetched"]}, estimate' if c.get('unfetched') is not None else 'unknown'
        lines.append(f'replies: {c["received_direct"]} of ~{c["reported_direct"]} direct received (unfetched {estimate}) · '
                     f'{c["shown_direct"]} shown · +{c["shown_descendants"]} descendants · {c["unshown_received"]} received but not shown · {c["unavailable"]} unavailable')
    for index, record in enumerate(result.get('results', []), 1):
        if 'author' in record:
            label = 'parent' if record.get('role') == 'parent' else ('r' if record.get('role') == 'reply' else 'p') + str(index)
            lines.extend(post_lines(record, label, args.chars, full=args.command == 'post' and record.get('role') == 'post'))
        else:
            counts = record.get('counts') or {'followers': record.get('follower_count')}
            fields = [person(record)] + [f'{key}={"unknown" if value is None else value}' for key, value in counts.items()]
            if record.get('bio'):
                fields.append('bio: ' + quote(record['bio']))
            if record.get('bio_links'):
                fields.append('links: ' + ', '.join(map(quote, record['bio_links'])))
            lines.extend([' · '.join(fields), '     url: ' + quote(record.get('url'))])
    if result.get('out'):
        lines.append(f'{result["count"]} saved · ' + quote(result['out']) + (' · already complete' if result.get('already_complete') else ''))
    if result.get('reported_total') is not None:
        lines.append(f'reported_total: {result["reported_total"]} · server sample, not the whole graph')
    if result.get('next'):
        lines.append('more: ' + result['next'])
    if args.command == 'post':
        lines.append('open a reply: post <reply url> (shows what is under it; missing siblings stay missing) · newest first: --sort recent (may overlap)')
    else:
        lines.append('open: post <url> · person: user @name / about @name / graph @name followers')
    if result.get('message'):
        lines.append(text(result['message'], 0) + ' · fix: ' + text(result.get('fix'), 0))
    return '\n'.join(lines)
