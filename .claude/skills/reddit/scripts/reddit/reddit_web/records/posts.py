"""A t3 (post) → the skill's post record."""
from reddit.reddit_web.records.common import BASE, absolute, fullname, images, number, optional, text, timestamp


def _content(data):
    """(post_type, media, poll, crosspost) of a post."""
    media, poll, crosspost = [], None, None
    if data.get('is_gallery'):
        items = [item for item in (data.get('gallery_data') or {}).get('items') or []
                 if isinstance(item, dict) and not item.get('is_deleted')]
        return 'gallery', images(data.get('media_metadata'), [(i.get('media_id'), i.get('caption')) for i in items]), \
            poll, crosspost
    if isinstance(data.get('poll_data'), dict):
        raw = data['poll_data']
        poll = {'options': [{'text': text(o.get('text')), 'vote_count': number(o.get('vote_count'))}
                            for o in raw.get('options') or [] if isinstance(o, dict)],
                'total_vote_count': number(raw.get('total_vote_count')),
                'voting_ends_at': timestamp(number(raw.get('voting_end_timestamp')) / 1000
                                            if number(raw.get('voting_end_timestamp')) is not None else None)}
        return 'poll', media, poll, crosspost
    if isinstance(data.get('crosspost_parent_list'), list) and data['crosspost_parent_list']:
        original = data['crosspost_parent_list'][0]
        if isinstance(original, dict):
            crosspost = post({key: value for key, value in original.items() if key != 'crosspost_parent_list'})
        return 'crosspost', media, poll, crosspost
    if data.get('is_video') or data.get('post_hint') in ('rich:video', 'hosted:video'):
        video = (data.get('secure_media') or data.get('media') or {}).get('reddit_video') or {}
        return 'video', [{'url': text(video.get('fallback_url') or data.get('url')), 'caption': ''}], poll, crosspost
    if data.get('is_self'):
        return 'self', media, poll, crosspost
    kind = text(data.get('post_hint')) or 'link'
    if kind == 'image':
        media = [{'url': text(data.get('url')), 'caption': ''}]
    return kind, media, poll, crosspost


def post(data):
    kind, media, poll, crosspost = _content(data)
    identity = fullname(data, 't3')
    return {
        'kind': 'post', 'id': identity, 'url': absolute(data.get('permalink')) or f'{BASE}/comments/{identity[3:]}/',
        'title': text(data.get('title')), 'text': text(data.get('selftext')), 'subreddit': text(data.get('subreddit')),
        'author': text(data.get('author')) or '[deleted]', 'created_at': timestamp(data.get('created_utc')),
        'score': number(data.get('score')), 'upvote_ratio': number(data.get('upvote_ratio')),
        'num_comments': number(data.get('num_comments')), 'post_type': kind, 'link_url': absolute(data.get('url')),
        'domain': text(data.get('domain')), 'flair': optional(data.get('link_flair_text')),
        'nsfw': data.get('over_18') is True, 'spoiler': data.get('spoiler') is True, 'locked': data.get('locked') is True,
        'archived': data.get('archived') is True,
        'pinned': data.get('stickied') is True or data.get('pinned') is True,
        'distinguished': optional(data.get('distinguished')), 'edited_at': timestamp(data.get('edited')),
        'removed': optional(data.get('removed_by_category')), 'contest_mode': data.get('contest_mode') is True,
        'suggested_sort': optional(data.get('suggested_sort')), 'num_crossposts': number(data.get('num_crossposts')),
        'num_duplicates': number(data.get('num_duplicates')), 'media': media, 'poll': poll, 'crosspost': crosspost,
    }
