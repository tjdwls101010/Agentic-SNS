"""t5 (community), rule, t2 (user), moderator and wiki → the skill's records."""
from reddit.reddit_web.records.common import BASE, fullname, number, optional, text, timestamp


def community(data):
    name = text(data.get('display_name'))
    return {'kind': 'subreddit', 'id': fullname(data, 't5'), 'name': name, 'url': f'{BASE}/r/{name}/',
            'title': text(data.get('title')), 'text': text(data.get('public_description')),
            'description': text(data.get('description')), 'subscribers': number(data.get('subscribers')),
            'active': number(data.get('accounts_active')), 'created_at': timestamp(data.get('created_utc')),
            'nsfw': data.get('over18') is True, 'visibility': text(data.get('subreddit_type'))}


def rule(data):
    return {'name': text(data.get('short_name')), 'text': text(data.get('description')),
            'applies_to': text(data.get('kind'))}


def user(data):
    name = text(data.get('name'))
    profile = data.get('subreddit') if isinstance(data.get('subreddit'), dict) else {}
    return {'kind': 'user', 'id': 't2_' + text(data.get('id')), 'name': name, 'url': f'{BASE}/user/{name}/',
            'post_karma': number(data.get('link_karma')), 'comment_karma': number(data.get('comment_karma')),
            'created_at': timestamp(data.get('created_utc')), 'text': text(profile.get('public_description')),
            'moderator': data.get('is_mod') is True, 'admin': data.get('is_employee') is True,
            'verified': data.get('verified') is True}


def moderator(data):
    name = text(data.get('name'))
    return {'kind': 'moderator', 'id': text(data.get('id')), 'name': name, 'url': f'{BASE}/user/{name}/',
            'flair': optional(data.get('author_flair_text')), 'since': timestamp(data.get('date'))}


def wiki_page(sub, page, data):
    by = data.get('revision_by') if isinstance(data.get('revision_by'), dict) else {}
    revision = text(data.get('revision_id'))
    return {'kind': 'wiki_page', 'id': f'wiki:{sub}/{page}@{revision}', 'subreddit': sub, 'page': page,
            'text': text(data.get('content_md')), 'revised_at': timestamp(data.get('revision_date')),
            'revised_by': text((by.get('data') or {}).get('name')) or None, 'reason': optional(data.get('reason')),
            'url': f'{BASE}/r/{sub}/wiki/{page}'}


def wiki_index(sub, names):
    """Article pages apart from the settings pages (config/...), which hold the sidebar and rules text."""
    return {'kind': 'wiki_index', 'id': f'wiki:{sub}', 'subreddit': sub,
            'pages': [n for n in names if not n.startswith('config/')],
            'settings_pages': [n for n in names if n.startswith('config/')], 'url': f'{BASE}/r/{sub}/wiki/pages'}
