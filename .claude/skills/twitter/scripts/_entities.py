"""Pure normalized cards for the current X user and place node shapes."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def timestamp(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00')) if 'T' in value and '-' in value else parsedate_to_datetime(value)
        return date.replace(tzinfo=date.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


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
