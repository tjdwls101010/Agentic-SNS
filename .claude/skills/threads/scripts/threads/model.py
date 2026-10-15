"""The records a read returns; their fields are the public contract that schema describes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Media:
    kind: str
    url: str
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None

    def to_dict(self):
        return asdict(self)


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
    counts: Counts | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Counts:
    followers: int | None = None
    following: int | None = None
    mutuals: int | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Post:
    id: str | None = None
    code: str | None = None
    url: str | None = None
    created_at: str | None = None
    text: str = ''
    author: User | None = None
    like_count: int | None = None
    reply_count: int | None = None
    repost_count: int | None = None
    quote_count: int | None = None
    media_type: str = 'text'
    media: list[Media] = field(default_factory=list)
    is_reply: bool = False
    reply_to_id: str | None = None
    root_post_id: str | None = None
    quoted_post: Post | None = None
    reposted_post: Post | None = None
    link_preview: dict | None = None
    is_pinned: bool = False
    unavailable: bool = False
    unavailable_reason: str | None = None
    role: str = 'post'
    depth: int = 0
    relation: str | None = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Completeness:
    reported_direct: int | None = None
    received_direct: int = 0
    shown_direct: int = 0
    shown_descendants: int = 0
    unshown_received: int = 0
    unavailable: int = 0
    unfetched: int | None = None
    unfetched_is_estimate: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass
class Page:
    records: list = field(default_factory=list)
    cursor: str | None = None
    has_next: bool = False
    stop: str = 'exhausted'
    groups: list = field(default_factory=list)
    reported_total: int | None = None
    restarted: bool = False
    state_updates: dict = field(default_factory=dict)
