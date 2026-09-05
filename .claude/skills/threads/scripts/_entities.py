"""Profile cards retain unknown counts rather than inventing zero."""
from dataclasses import asdict, dataclass, field

from ._media import _integer, _node_identifier


@dataclass
class User:
    id: str = ''
    username: str = ''
    full_name: str | None = None
    is_verified: bool | None = None
    private: bool | None = None
    follower_count: int | None = None
    bio: str | None = None
    bio_links: list = field(default_factory=list)
    friendship_status: dict = field(default_factory=dict)
    profile_pic_url: str | None = None
    url: str | None = None
    counts: dict | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Counts:
    followers: int | None = None
    following: int | None = None
    mutuals: int | None = None

    def to_dict(self):
        return asdict(self)


def build_user(raw):
    if not isinstance(raw, dict) or _node_identifier(raw) is None:
        return None
    name = raw.get('username') or ''
    return User(id=_node_identifier(raw), username=name, full_name=raw.get('full_name'),
        is_verified=raw.get('is_verified', raw.get('text_post_app_is_verified')),
        private=raw.get('text_post_app_is_private'), follower_count=_integer(raw.get('follower_count')),
        bio=raw.get('biography'), bio_links=[x['url'] for x in raw.get('bio_links') or [] if isinstance(x, dict) and x.get('url')],
        friendship_status=raw.get('friendship_status') or {}, profile_pic_url=raw.get('profile_pic_url'),
        url='https://www.threads.com/@' + name if name else None)


def build_counts(raw):
    raw = raw if isinstance(raw, dict) else {}
    return Counts(*(_integer(raw.get(key)) for key in ('followers', 'following', 'mutuals')))
