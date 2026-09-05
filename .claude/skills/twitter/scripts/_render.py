"""Dense human-readable output; normalization and truncation live here alone."""
import json
import time
from datetime import datetime


def number(value):
    if value is None:
        return '?'
    value = int(value)
    for divisor, suffix in ((1000000, 'M'), (1000, 'K')):
        if value >= divisor:
            return f'{value / divisor:.1f}'.rstrip('0').rstrip('.') + suffix
    return str(value)


def _text(row, chars=280):
    value = row.get('text', row.get('description', '')) or ''
    for link in row.get('entities', {}).get('urls', []):
        if link.get('url'):
            value = value.replace(link['url'], link.get('expanded_url') or link['url'])
    for media in row.get('entities', {}).get('media', []):
        if media.get('url'):
            value = value.replace(media['url'], '')
    value = ' ⏎ '.join(' '.join(part.split()) for part in value.splitlines())
    return value[:chars] + '…' if chars and len(value) > chars else value


def badge(user):
    kind = user.get('verified_type')
    return ' ✓gov' if kind == 'Government' else ' ✓business' if kind == 'Business' else ' ✓blue' if user.get('is_blue_verified') else ''


def user_card(user):
    pieces = [f'@{user.get("screen_name", "?")} ({user.get("name") or ""}{badge(user)})',
              f'followers {number(user.get("followers_count"))}', f'following {number(user.get("following_count"))}',
              f'posts {number(user.get("tweet_count"))}']
    if user.get('created_at'):
        pieces.append('joined ' + user['created_at'][:7])
    for key, label in (('is_protected', 'private'), ('following', 'you follow'), ('followed_by', 'follows you')):
        if user.get(key):
            pieces.append(label)
    if user.get('description'):
        pieces.append('bio: ' + json.dumps(_text(user), ensure_ascii=False))
    affiliate = user.get('affiliate', {}).get('label', {})
    if affiliate:
        pieces.append('affiliate ' + str(affiliate.get('description', affiliate.get('url', {}).get('url', ''))))
    if user.get('role'):
        pieces.append(user['role'])
    pieces.append('url: ' + json.dumps(user.get('profile_url')))
    return ' · '.join(pieces)


def local_time(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone().isoformat(timespec='minutes')
    except (ValueError, AttributeError):
        return '?'


def tweet_lines(row, index, chars, labels):
    author = row.get('author') or {}
    role = row.get('role')
    prefix = 'r' if role == 'reply' else 't'
    label = prefix + str(index)
    parent = row.get('in_reply_to_id')
    extra = f' reply-to={labels.get(parent, parent)}' if parent and role == 'reply' else ''
    labels[row['id']] = label
    tags = (' [pinned]' if row.get('is_pinned') else '') + (' [parent]' if role == 'parent' else '')
    if 'Reply' in row.get('limited_actions', []):
        tags += ' [limited: replies]'
    stats = ' '.join(label + '=' + number(row.get(key)) for key, label in [('like_count', 'likes'), ('retweet_count', 'reposts'), ('reply_count', 'replies'), ('quote_count', 'quotes'), ('view_count', 'views')] if row.get(key) is not None)
    first = f'[{label}{extra}] @{author.get("screen_name", "?")}{badge(author)} · {local_time(row.get("created_at"))}{tags} · {stats}'
    original = row.get('retweeted_tweet')
    if original:
        first += f' · repost of @{(original.get("author") or {}).get("screen_name", "?")}'
    full = role == 'focal'
    lines = [first, '     ' + ('text[full]: ' if full else '') + json.dumps(_text(row, None if full else chars), ensure_ascii=False)]
    if row.get('media'):
        lines[-1] += '   media: ' + ', '.join(m['kind'] for m in row['media'])
    quote = row.get('quoted_tweet')
    if quote:
        lines.append(f'     quoting @{(quote.get("author") or {}).get("screen_name", "?")}: ' + json.dumps(_text(quote, chars), ensure_ascii=False) + ' (' + str(quote.get('url')) + ')')
    elif row.get('quoted_tweet_id'):
        lines.append(f'     quoting https://x.com/i/web/status/{row["quoted_tweet_id"]} (open with post)')
    lines.append('     url: ' + json.dumps(row.get('url')))
    if row.get('community_url'):
        lines.append('     community: ' + str(row['community_url']))
    indent = '  ' * min(row.get('depth', 0), 12)
    return [indent + line for line in lines]


def render(result, args):
    if args.command in ('doctor', 'refresh', 'schema'):
        return result.get('summary') or json.dumps(result, ensure_ascii=False, indent=2)
    header = [args.command, f'operation={result.get("operation", "?")}', f'{len(result.get("results", []))} shown']
    if result.get('stored') is not None:
        header.append(f'{result["stored"]} stored')
    if args.sort:
        header.append('sort=' + args.sort)
    header.extend([f'stopped={result.get("stop_reason")}', f'fetched {result.get("fetched_bytes", 0) / 1048576:.2f}MB'])
    if 'direct_shown' in result:
        header.append(f'replies: {result["direct_shown"]} direct shown of {result.get("reported")} reported · +{result["nested_shown"]} nested · hidden branches {result["hidden_branches"]}')
    if args.command == 'trends':
        header.append(f'other items {result.get("other_items", 0)} · promoted excluded {result.get("promoted", 0)}')
    budget = result.get('budget', {})
    for name, bucket in budget.get('operations', {}).items():
        if bucket:
            header.append(f'budget {name} {bucket.get("remaining")} of {bucket.get("limit")} (resets in {max(0, round((bucket.get("reset_at", 0) - time.time()) / 60))}m)')
    header.append(f'window {budget.get("window", 0)}/200')
    if result.get('warnings'):
        header.append(f'warnings={len(result["warnings"])}')
    if result.get('viewer_changed'):
        header.append('viewer changed')
    lines, labels = [' · '.join(header)], {}
    if card := result.get('card'):
        lines.append(user_card(card) if card['kind'] == 'user' else place_card(card))
    for index, row in enumerate(result.get('results', []), 1):
        kind = row.get('kind')
        if kind == 'tweet':
            lines.extend(tweet_lines(row, index, args.chars, labels))
        elif kind == 'user':
            lines.append(user_card(row))
        elif kind in ('list', 'community'):
            lines.append(place_card(row))
        else:
            lines.append(f'[{"event" if kind == "event" else index}] ' + ' · '.join(str(row[k]) for k in ('name', 'context', 'description', 'url') if row.get(k)))
    if result.get('unresolved'):
        lines.append('unresolved: ' + ', '.join('@' + h for h in result['unresolved']))
    if result.get('next'):
        lines.append('more: ' + result['next'])
    if result.get('error'):
        lines.append('stopped: ' + result['error'] + ' · ' + result.get('fix', ''))
    return '\n'.join(lines)


def place_card(row):
    return ' · '.join(str(row[k]) for k in ('name', 'description') if row.get(k)) + ' · ' + ' · '.join(f'{k}={row[k]}' for k in ('member_count', 'subscriber_count', 'mode', 'join_policy', 'is_nsfw') if row.get(k) is not None) + ' · url: ' + json.dumps(row.get('url'))
