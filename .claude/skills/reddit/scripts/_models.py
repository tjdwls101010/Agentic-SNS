"""Pure Reddit post/comment normalization; identity is always a fullname."""
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import math

BASE = 'https://www.reddit.com'


def text(value):
    return value if isinstance(value, str) else ''


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def timestamp(value):
    if number(value) is None:
        return None
    try:
        return datetime.fromtimestamp(value, UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def fullname(data, kind):
    name = text(data.get('name'))
    return name if name.startswith(kind + '_') else kind + '_' + text(data.get('id'))


def url(value):
    value = text(value)
    return BASE + value if value.startswith('/') and not value.startswith('//') else value


@dataclass
class Post:
    fullname: str
    url: str
    title: str = ''
    text: str = ''
    subreddit: str = ''
    author: str = '[deleted]'
    created_at: str | None = None
    score: int | float | None = None
    num_comments: int | float | None = None
    upvote_ratio: int | float | None = None
    kind: str = 'post'
    post_type: str = 'link'
    link_url: str = ''
    domain: str = ''
    flair: str = ''
    nsfw: bool = False
    spoiler: bool = False
    locked: bool = False
    pinned: bool = False
    edited_at: str | None = None
    media: list = field(default_factory=list)
    poll: dict = field(default_factory=dict)
    crosspost: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class Comment:
    fullname: str
    url: str
    parent: str = ''
    link_id: str = ''
    text: str = ''
    author: str = '[deleted]'
    subreddit: str = ''
    created_at: str | None = None
    score: int | float | None = None
    score_hidden: bool = False
    kind: str = 'comment'
    depth: int = 0
    pinned: bool = False
    locked: bool = False
    edited_at: str | None = None
    distinguished: str = ''

    def to_dict(self):
        return asdict(self)


def post_content(data):
    media, poll, crosspost = [], {}, {}
    if data.get('is_gallery'):
        kind = 'gallery'
        metadata = data.get('media_metadata') or {}
        for item in (data.get('gallery_data') or {}).get('items', []):
            source = (metadata.get(item.get('media_id')) or {}).get('s') or {}
            media.append({'url': text(source.get('u') or source.get('gif')), 'caption': text(item.get('caption'))})
    elif isinstance(data.get('poll_data'), dict):
        kind, poll = 'poll', data['poll_data']
    elif data.get('crosspost_parent_list'):
        kind = 'crosspost'
        original = data['crosspost_parent_list'][0]
        crosspost = build_post({key: value for key, value in original.items() if key != 'crosspost_parent_list'}).to_dict()
    elif data.get('is_video') or data.get('post_hint') in ('rich:video', 'hosted:video'):
        kind = 'video'
        video = (data.get('secure_media') or data.get('media') or {}).get('reddit_video') or {}
        media = [{'url': text(video.get('fallback_url') or data.get('url')), 'caption': ''}]
    elif data.get('is_self'):
        kind = 'self'
    else:
        kind = text(data.get('post_hint')) or 'link'
        if kind == 'image':
            media = [{'url': text(data.get('url')), 'caption': ''}]
    return kind, media, poll, crosspost


def build_post(data):
    kind, media, poll, crosspost = post_content(data)
    identity = fullname(data, 't3')
    return Post(
        fullname=identity, url=url(data.get('permalink')) or f'{BASE}/comments/{identity[3:]}/',
        title=text(data.get('title')), text=text(data.get('selftext')), subreddit=text(data.get('subreddit')),
        author=text(data.get('author')) or '[deleted]', created_at=timestamp(data.get('created_utc')),
        score=number(data.get('score')), num_comments=number(data.get('num_comments')),
        upvote_ratio=number(data.get('upvote_ratio')), link_url=url(data.get('url')),
        domain=text(data.get('domain')), flair=text(data.get('link_flair_text')),
        nsfw=data.get('over_18') is True, spoiler=data.get('spoiler') is True,
        locked=data.get('locked') is True, pinned=data.get('stickied') is True or data.get('pinned') is True,
        edited_at=timestamp(data.get('edited')), post_type=kind, media=media, poll=poll, crosspost=crosspost,
    )


def build_comment(data):
    identity = fullname(data, 't1')
    link_id = text(data.get('link_id'))
    return Comment(
        fullname=identity, url=url(data.get('permalink')) or f'{BASE}/comments/{link_id[3:]}/_/{identity[3:]}/',
        parent=text(data.get('parent_id')), link_id=link_id, text=text(data.get('body')),
        author=text(data.get('author')) or '[deleted]', subreddit=text(data.get('subreddit')),
        created_at=timestamp(data.get('created_utc')), score=number(data.get('score')),
        score_hidden=data.get('score_hidden') is True, depth=int(number(data.get('depth')) or 0),
        pinned=data.get('stickied') is True, locked=data.get('locked') is True,
        edited_at=timestamp(data.get('edited')), distinguished=text(data.get('distinguished')),
    )
