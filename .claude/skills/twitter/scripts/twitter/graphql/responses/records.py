"""Normalized records for X users, places, trends and posts; a repost keeps the reposter identity and the original content."""
from dataclasses import asdict, dataclass, field

from ...dates import timestamp


class Record:
    def to_dict(self):
        return asdict(self)


@dataclass
class User(Record):
    id: str = ''
    screen_name: str = ''
    name: str | None = None
    created_at: str | None = None
    followers_count: int | None = None
    following_count: int | None = None
    tweet_count: int | None = None
    media_count: int | None = None
    favorites_count: int | None = None
    is_blue_verified: bool = False
    is_verified: bool = False
    verified_type: str | None = None
    is_protected: bool = False
    description: str | None = None
    location: str | None = None
    url: str | None = None
    profile_url: str | None = None
    avatar_url: str | None = None
    banner_url: str | None = None
    following: bool | None = None
    followed_by: bool | None = None
    blocking: bool | None = None
    muting: bool | None = None
    follow_request_sent: bool = False
    affiliate: dict = field(default_factory=dict)
    professional: dict = field(default_factory=dict)
    pinned_ids: list = field(default_factory=list)
    kind: str = 'user'


def build_user(node):
    core, legacy = node.get('core', {}), node.get('legacy', {})
    counts, perspectives = node.get('relationship_counts', {}), node.get('relationship_perspectives', {})
    handle = core.get('screen_name', legacy.get('screen_name', ''))
    return User(id=node.get('rest_id', ''), screen_name=handle, name=core.get('name', legacy.get('name')),
                created_at=timestamp(core.get('created_at', legacy.get('created_at'))),
                followers_count=counts.get('followers', legacy.get('followers_count')),
                following_count=counts.get('following', legacy.get('friends_count')),
                tweet_count=node.get('tweet_counts', {}).get('tweets', legacy.get('statuses_count')),
                media_count=node.get('tweet_counts', {}).get('media_tweets'),
                favorites_count=node.get('action_counts', {}).get('favorites_count'),
                is_blue_verified=node.get('is_blue_verified', False), is_verified=node.get('verification', {}).get('verified', False),
                verified_type=node.get('verification', {}).get('verified_type'), is_protected=node.get('privacy', {}).get('protected', False),
                description=node.get('profile_bio', {}).get('description', legacy.get('description')),
                location=node.get('location', {}).get('location'), url=node.get('website', {}).get('url'),
                profile_url=f'https://x.com/{handle}', avatar_url=node.get('avatar', {}).get('image_url'),
                banner_url=node.get('banner', {}).get('image_url'),
                **{k: perspectives.get(k) for k in ('following', 'followed_by', 'blocking', 'muting')},
                follow_request_sent=node.get('follow_request_sent', False), affiliate=node.get('affiliates_highlighted_label', {}),
                professional=node.get('professional', {}), pinned_ids=node.get('pinned_items', {}).get('tweet_ids_str', []))


@dataclass
class List(Record):
    id: str = ''
    name: str | None = None
    description: str | None = None
    member_count: int | None = None
    subscriber_count: int | None = None
    mode: str | None = None
    url: str | None = None
    kind: str = 'list'


@dataclass
class Community(Record):
    id: str = ''
    name: str | None = None
    description: str | None = None
    member_count: int | None = None
    moderator_count: int | None = None
    join_policy: str | None = None
    is_nsfw: bool = False
    role: str | None = None
    rules: list = field(default_factory=list)
    url: str | None = None
    kind: str = 'community'


def build_place(node, kind):
    cls = List if kind == 'list' else Community
    identity = str(node.get('rest_id') or node.get('id_str') or node.get('id', ''))
    values = {key: node[key] for key in cls.__dataclass_fields__ if key in node and key not in ('kind', 'id', 'url')}
    return cls(id=identity, url=f'https://x.com/i/{"lists" if kind == "list" else "communities"}/{identity}', **values)


@dataclass
class Trend(Record):
    id: str = ''
    name: str = ''
    context: str | None = None
    description: str | None = None
    url: str | None = None
    promoted: bool = False
    kind: str = 'trend'


def build_trend(node, identity, event=False):
    metadata = node.get('trendMetadata', node.get('trend_metadata', {}))
    return Trend(id=identity, name=node.get('name', node.get('title', '')),
                 context=metadata.get('domainContext', metadata.get('domain_context')),
                 description=metadata.get('metaDescription', metadata.get('meta_description', node.get('subtitle'))),
                 url=node.get('url', {}).get('url') if isinstance(node.get('url'), dict) else node.get('url'),
                 promoted=bool(node.get('promotedMetadata') or node.get('promoted_metadata')),
                 kind='event' if event else 'trend')


@dataclass
class Media(Record):
    kind: str = 'photo'
    url: str = ''
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None


@dataclass
class Tweet(Record):
    id: str = ''
    url: str | None = None
    created_at: str | None = None
    text: str = ''
    lang: str | None = None
    author: User | None = None
    is_reply: bool = False
    in_reply_to_id: str | None = None
    in_reply_to_screen_name: str | None = None
    conversation_id: str | None = None
    reply_count: int | None = None
    retweet_count: int | None = None
    quote_count: int | None = None
    like_count: int | None = None
    bookmark_count: int | None = None
    view_count: int | None = None
    media: list[Media] = field(default_factory=list)
    urls: list = field(default_factory=list)
    entities: dict = field(default_factory=dict)
    hashtags: list = field(default_factory=list)
    is_note_tweet: bool = False
    is_pinned: bool = False
    retweeted_tweet: 'Tweet | None' = None
    quoted_tweet: 'Tweet | None' = None
    quoted_tweet_id: str | None = None
    limited_actions: list = field(default_factory=list)
    is_restricted: bool = False
    community: dict | None = None
    kind: str = 'tweet'


def build_tweet(node, pinned=False, _depth=0):
    if not isinstance(node, dict) or _depth > 5 or node.get('__typename') == 'TweetTombstone':
        return None
    limited = node.get('limitedActionResults', {}).get('limited_actions', [])
    restricted = node.get('__typename') == 'TweetWithVisibilityResults'
    if restricted:
        node = node.get('tweet', {})
    if not node.get('rest_id'):
        return None
    legacy = node.get('legacy', {})
    author_node = node.get('core', {}).get('user_results', {}).get('result')
    author = build_user(author_node) if author_node else None
    original = build_tweet(legacy.get('retweeted_status_result', {}).get('result'), _depth=_depth + 1)
    quote = build_tweet(node.get('quoted_status_result', {}).get('result'), _depth=_depth + 1)
    note = node.get('note_tweet', {}).get('note_tweet_results', {}).get('result', {})
    entities = note.get('entity_set') or legacy.get('entities', {})
    media = []
    for item in legacy.get('extended_entities', {}).get('media', []):
        variants = [v for v in item.get('video_info', {}).get('variants', []) if v.get('content_type') == 'video/mp4']
        url = max(variants, key=lambda v: v.get('bitrate', 0))['url'] if variants else item.get('media_url_https', '')
        size = item.get('original_info', {})
        media.append(Media(item.get('type', 'photo'), url, size.get('width'), size.get('height'), item.get('ext_alt_text')))
    result = Tweet(id=node['rest_id'], url=f'https://x.com/{author.screen_name if author else "i/web"}/status/{node["rest_id"]}',
                   created_at=timestamp(legacy.get('created_at')), text=note.get('text', legacy.get('full_text', '')),
                   lang=legacy.get('lang'), author=author, is_reply=bool(legacy.get('in_reply_to_status_id_str')),
                   in_reply_to_id=legacy.get('in_reply_to_status_id_str'), in_reply_to_screen_name=legacy.get('in_reply_to_screen_name'),
                   conversation_id=legacy.get('conversation_id_str'),
                   **{key: legacy.get(source) for key, source in [('reply_count', 'reply_count'), ('retweet_count', 'retweet_count'), ('quote_count', 'quote_count'), ('like_count', 'favorite_count'), ('bookmark_count', 'bookmark_count')]},
                   view_count=int(node['views']['count']) if str(node.get('views', {}).get('count', '')).isdigit() else None,
                   media=media, entities=entities, urls=[u.get('expanded_url', u.get('url')) for u in entities.get('urls', [])],
                   hashtags=[h.get('text') for h in entities.get('hashtags', [])], is_note_tweet=bool(note.get('text')),
                   is_pinned=pinned, retweeted_tweet=original, quoted_tweet=quote, quoted_tweet_id=legacy.get('quoted_status_id_str'),
                   limited_actions=[a.get('action') for a in limited], is_restricted=restricted,
                   community=node.get('community_results', {}).get('result'))
    if original:
        for key in ('url', 'text', 'media', 'urls', 'entities', 'hashtags', 'lang', 'reply_count', 'retweet_count', 'quote_count', 'like_count', 'bookmark_count', 'view_count', 'is_note_tweet'):
            setattr(result, key, getattr(original, key))
    return result
