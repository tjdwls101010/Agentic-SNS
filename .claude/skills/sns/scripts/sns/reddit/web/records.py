"""Pure conversions from Reddit's things to the skill's records: posts (t3), comments (t1), communities (t5), users (t2),
moderators, wiki pages, and a Listing page. Every record carries kind, id, url and created_at; media items follow the
skill's media contract (see media_items).

Reddit's loose types become strict ones or None: a flair made of a zero-width space is no flair, a non-finite number is
null, a relative address is made absolute.
"""
import math
import re
import unicodedata
from datetime import datetime, timezone

from sns.errors import SnsError

BASE = 'https://www.reddit.com'


# --- small readers -------------------------------------------------------------------------------------------------

def text(value):
    return value if isinstance(value, str) else ''


def optional(value):
    """A string with something visible in it, else None (Reddit sends flairs made of a zero-width space)."""
    if not isinstance(value, str):
        return None
    return value if any(not c.isspace() and unicodedata.category(c) != 'Cf' for c in value) else None


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def timestamp(value):
    if number(value) is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def absolute(value):
    value = text(value)
    return BASE + value if value.startswith('/') and not value.startswith('//') else value


def fullname(data, kind):
    name = text(data.get('name'))
    return name if name.startswith(kind + '_') else kind + '_' + text(data.get('id'))


# --- media ---------------------------------------------------------------------------------------------------------

def _item(n, kind, image_url, *, video_url=None, width=None, height=None, alt='', media_id=None):
    """One picture or clip of a record. n: its place in the record, from 1, in the order Reddit shows them (a gallery's
    own order). kind: photo, gif, sticker or video. image_url: the original picture, or a video's poster (null when
    Reddit sent none); video_url: the clip, if any. width and height are the original's in pixels; alt is the caption."""
    return {'n': n, 'kind': kind, 'image_url': image_url or None, 'video_url': video_url or None, 'width': width,
            'height': height, 'alt': alt, 'media_id': media_id}


def media_items(metadata, order=None):
    """The media of a record from a media_metadata map: in `order` ([(media_id, caption)]) when given, else as sent. An
    entry that is deleted, or has no source, is skipped and takes no number."""
    metadata = metadata if isinstance(metadata, dict) else {}
    keys = order if order is not None else [(key, '') for key in metadata]
    found = []
    for media_id, caption in keys:
        entry = metadata.get(media_id) if isinstance(metadata.get(media_id), dict) else {}
        source = entry.get('s') if isinstance(entry.get('s'), dict) else {}
        still, gif, clip = text(source.get('u')), text(source.get('gif')), text(source.get('mp4'))
        if not (still or gif or clip):
            continue
        kind = 'sticker' if text(media_id).startswith('emote|') else 'gif' if (gif or clip) else 'photo'
        found.append(_item(len(found) + 1, kind, still or gif, video_url=clip, width=number(source.get('x')),
                           height=number(source.get('y')), alt=text(caption), media_id=text(media_id) or None))
    return found


def _poster(data):
    """A post's preview picture {url, width, height} (a video's poster, a picture's size), or {}."""
    images = (data.get('preview') or {}).get('images') if isinstance(data.get('preview'), dict) else None
    first = images[0] if isinstance(images, list) and images and isinstance(images[0], dict) else {}
    source = first.get('source') if isinstance(first.get('source'), dict) else {}
    return {'url': text(source.get('url')), 'width': number(source.get('width')), 'height': number(source.get('height'))}


# --- posts ---------------------------------------------------------------------------------------------------------

def _content(data):
    """(post_type, media, poll, crosspost) of a post."""
    media, poll, crosspost = [], None, None
    if data.get('is_gallery'):
        items = [item for item in (data.get('gallery_data') or {}).get('items') or []
                 if isinstance(item, dict) and not item.get('is_deleted')]
        return 'gallery', media_items(data.get('media_metadata'), [(i.get('media_id'), i.get('caption'))
                                                                    for i in items]), poll, crosspost
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
        poster = _poster(data)
        return 'video', [_item(1, 'video', poster['url'], video_url=text(video.get('fallback_url') or data.get('url')),
                               width=number(video.get('width')) or poster['width'],
                               height=number(video.get('height')) or poster['height'])], poll, crosspost
    if data.get('is_self'):
        return 'self', media, poll, crosspost
    kind = text(data.get('post_hint')) or 'link'
    if kind == 'image':
        poster = _poster(data)
        media = [_item(1, 'photo', text(data.get('url')), width=poster['width'], height=poster['height'])]
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


# --- comments ------------------------------------------------------------------------------------------------------

def _removed(data):
    """'removed' when moderators or Reddit took the text away, 'deleted' when its author did, else None."""
    body = data.get('body')
    if body == '[removed]':
        return 'removed'
    if body == '[deleted]' and data.get('author') in (None, '[deleted]'):
        return 'deleted'
    return None


def comment(data, depth=None):
    """A t1 → the comment record (flat: the tree is kept by parent_id and depth, not nesting)."""
    identity = fullname(data, 't1')
    post_id = text(data.get('link_id'))
    sent_depth = number(data.get('depth'))
    return {
        'kind': 'comment', 'id': identity,
        'url': absolute(data.get('permalink')) or f'{BASE}/comments/{post_id[3:]}/_/{identity[3:]}/',
        'parent_id': text(data.get('parent_id')), 'post_id': post_id, 'text': text(data.get('body')),
        'author': text(data.get('author')) or '[deleted]', 'subreddit': text(data.get('subreddit')),
        'created_at': timestamp(data.get('created_utc')), 'score': number(data.get('score')),
        'score_hidden': data.get('score_hidden') is True,
        'depth': depth if depth is not None else int(sent_depth or 0),
        'is_op': data.get('is_submitter') is True, 'distinguished': optional(data.get('distinguished')),
        'author_flair': optional(data.get('author_flair_text')), 'pinned': data.get('stickied') is True,
        'locked': data.get('locked') is True, 'edited_at': timestamp(data.get('edited')),
        'collapsed': data.get('collapsed') is True, 'collapsed_reason': optional(data.get('collapsed_reason_code')),
        'controversial': data.get('controversiality') == 1, 'removed': _removed(data),
        'media': media_items(data.get('media_metadata')),
    }


# --- communities, users, moderators, wiki --------------------------------------------------------------------------

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
    """A moderator of a community; created_at is when they became one there."""
    name = text(data.get('name'))
    return {'kind': 'moderator', 'id': text(data.get('id')), 'name': name, 'url': f'{BASE}/user/{name}/',
            'flair': optional(data.get('author_flair_text')), 'created_at': timestamp(data.get('date'))}


def wiki_page(sub, page, data):
    """One wiki page at one revision; created_at is when that revision was made."""
    by = data.get('revision_by') if isinstance(data.get('revision_by'), dict) else {}
    revision = text(data.get('revision_id'))
    return {'kind': 'wiki_page', 'id': f'wiki:{sub}/{page}@{revision}', 'subreddit': sub, 'page': page,
            'text': text(data.get('content_md')), 'created_at': timestamp(data.get('revision_date')),
            'revised_by': text((by.get('data') or {}).get('name')) or None, 'reason': optional(data.get('reason')),
            'url': f'{BASE}/r/{sub}/wiki/{page}'}


def wiki_index(sub, names):
    """Article pages apart from the settings pages (config/...), which hold the sidebar and rules text."""
    return {'kind': 'wiki_index', 'id': f'wiki:{sub}', 'subreddit': sub,
            'pages': [n for n in names if not n.startswith('config/')],
            'settings_pages': [n for n in names if n.startswith('config/')], 'url': f'{BASE}/r/{sub}/wiki/pages',
            'created_at': None}


# --- a Listing page ------------------------------------------------------------------------------------------------

_BUILDERS = {'t3': post, 't1': comment, 't5': community, 't2': user}


def _malformed(what):
    return SnsError('failed', f'Reddit sent a listing this skill cannot read ({what}).',
                    'Retry once; if it persists, report it (Reddit may have changed its format).',
                    reason='shape_changed')


def page(listing):
    """(records, after): every child as a record in Reddit's order; after is the next page's fullname or None. An id
    that disagrees with its fullname or an after that is not a fullname is malformed."""
    data = listing['data']
    after = data.get('after')
    if after is not None and (not isinstance(after, str) or not re.fullmatch(r't[1235]_[a-z0-9]+', after)):
        raise _malformed('its next-page value')
    records = []
    for child in data['children']:
        kind, raw = child['kind'], child['data']
        if kind == 'more':
            continue
        if kind != 't2':
            name = raw.get('name', kind + '_' + str(raw.get('id', '')))
            if not isinstance(name, str) or not re.fullmatch(kind + r'_[a-z0-9]+', name) or \
                    (raw.get('id') is not None and raw['id'] != name[3:]):
                raise _malformed('an item\'s id')
        elif not isinstance(raw.get('id'), str) or not re.fullmatch(r'[a-z0-9]+', raw['id']):
            raise _malformed('an account\'s id')
        records.append(_BUILDERS[kind](raw))
    return records, after
