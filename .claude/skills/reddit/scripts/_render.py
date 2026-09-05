"""Dense display only; JSON retains the received text and media."""
import html
import json
import re
import unicodedata


def normalize_text(value):
    value = html.unescape(str(value or ''))
    value = ''.join(c for c in value if unicodedata.category(c) != 'Cf' and not '\ufe00' <= c <= '\ufe0f')
    value = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', r'\1 (\2)', value)
    value = re.sub(r'(?m)^[ \t]*>[ \t]?', '', value)
    value = re.sub(r'(?m)^\s*\|?\s*[-:]+(?:\s*\|\s*[-:]+)+\s*\|?\s*$', '', value)
    value = re.sub(r'\*{1,3}|~~|`{1,3}|\^', '', value)
    paragraphs = [' '.join(part.split()) for part in re.split(r'\n\s*\n', value)]
    value = ' ⏎ '.join(p for p in paragraphs if p)
    seen = set()
    def once(match):
        address = match[0]
        if address in seen:
            return ''
        seen.add(address)
        return address
    return ' '.join(re.sub(r'https?://[^\s)]+', once, value).split())


def quote(value):
    return json.dumps(value, ensure_ascii=False)


def count(value):
    return '?' if value is None else str(value)


def render_item(item, index, chars=180, full=False):
    kind = item['kind']
    if kind == 'comment' and item.get('context'):
        return f'[c{index} shown earlier] u/{item.get("author", "[deleted]")}: {quote(normalize_text(item.get("text"))[:chars])}'
    labels = [key for key in ('nsfw', 'spoiler', 'locked', 'pinned', 'undated', 'admin', 'moderator') if item.get(key)]
    if item.get('window_excluded') and item['window_excluded'] not in labels:
        labels.append(item['window_excluded'])
    if item.get('edited_at'):
        labels.append('edited')
    suffix = (' · ' + ' · '.join(labels)) if labels else ''
    lines = []
    if kind == 'post':
        ratio = item.get('upvote_ratio')
        extra = f' ({ratio:.0%})' if ratio is not None else ''
        lines.append(f'[p{index}] r/{item.get("subreddit", "")} · u/{item.get("author", "[deleted]")} · {item.get("created_at") or "undated"} · {item.get("post_type", "link")} · score={count(item.get("score"))}{extra} · comments={count(item.get("num_comments"))}{suffix}')
        lines.append('     title: ' + quote(normalize_text(item.get('title'))))
        if item.get('flair'):
            lines.append('     flair: ' + quote(normalize_text(item['flair'])))
        for media in item.get('media', []):
            lines.append('     media: ' + quote(media.get('url', '')) + (' caption: ' + quote(normalize_text(media['caption'])) if media.get('caption') else ''))
        for option in item.get('poll', {}).get('options', []):
            lines.append(f'     option: {quote(normalize_text(option.get("text")))} · votes={count(option.get("vote_count"))}')
        original = item.get('crosspost')
        if original:
            lines.append(f'     original: r/{original.get("subreddit")} · u/{original.get("author")} · {quote(normalize_text(original.get("title")))} · {quote(original.get("url"))}')
        if item.get('link_url') and item.get('post_type') == 'link':
            lines.append(f'     link: {quote(item["link_url"])} · {item.get("domain", "")}')
    elif kind == 'comment':
        score = 'hidden' if item.get('score_hidden') else count(item.get('score'))
        parent = f' reply-to={item["parent"]}' if item.get('parent', '').startswith('t1_') else ''
        marker = ' anchor' if item.get('anchor') else ''
        orphan = ' orphan' if item.get('orphan') else ''
        earlier = ' shown earlier' if item.get('context') or item.get('context_only') or item.get('shown_earlier') else ''
        lines.append(f'[c{index}{parent}{marker}{orphan}{earlier}] {item.get("author", "[deleted]") if item.get("author") == "[deleted]" else "u/" + item.get("author", "")} · {item.get("created_at") or "undated"} · score={score}{suffix}')
    elif kind == 'subreddit':
        lines.append(f'[s{index}] r/{item.get("name")} · {count(item.get("subscribers"))} subscribers · {item.get("visibility", "")} · nsfw={"yes" if item.get("nsfw") else "no"}')
    elif kind == 'user':
        lines.append(f'[u{index}] u/{item.get("name")} · karma post={count(item.get("post_karma"))} comment={count(item.get("comment_karma"))} · since {item.get("created_at") or "?"}{suffix}')
    body = normalize_text(item.get('text') or item.get('description'))
    if body:
        shown = body if full else body[:chars]
        lines.append(f'     text[{"full" if full else str(len(shown)) + "/" + str(len(body)) + " chars"}]: {quote(shown)}')
    for number, rule in enumerate(item.get('rules', []), 1):
        lines.append(f'     rule {number}: {quote(normalize_text(rule.get("name")))} · {quote(normalize_text(rule.get("text")))}')
    if item.get('url'):
        lines.append('     url: ' + quote(item['url']))
    indent = '  ' * min(item.get('depth', 0), 20) if kind == 'comment' else ''
    return '\n'.join(indent + line for line in lines)
