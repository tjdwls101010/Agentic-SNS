"""Pure community, user and rule objects."""
from dataclasses import asdict, dataclass, field
from ._models import BASE, text, number, timestamp, fullname


@dataclass
class Subreddit:
    fullname: str
    name: str
    url: str
    title: str = ''
    text: str = ''
    description: str = ''
    subscribers: int | float | None = None
    active: int | float | None = None
    created_at: str | None = None
    nsfw: bool = False
    visibility: str = ''
    kind: str = 'subreddit'
    rules: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class User:
    fullname: str
    name: str
    url: str
    post_karma: int | float | None = None
    comment_karma: int | float | None = None
    created_at: str | None = None
    text: str = ''
    moderator: bool = False
    admin: bool = False
    verified: bool = False
    kind: str = 'user'

    def to_dict(self):
        return asdict(self)


@dataclass
class Rule:
    name: str
    text: str
    applies_to: str = ''

    def to_dict(self):
        return asdict(self)


def build_subreddit(data):
    name = text(data.get('display_name'))
    return Subreddit(fullname(data, 't5'), name, f'{BASE}/r/{name}/',
                     title=text(data.get('title')), text=text(data.get('public_description')),
                     description=text(data.get('description')), subscribers=number(data.get('subscribers')),
                     active=number(data.get('accounts_active')), created_at=timestamp(data.get('created_utc')),
                     nsfw=data.get('over18') is True, visibility=text(data.get('subreddit_type')))


def build_user(data):
    name = text(data.get('name'))
    return User('t2_' + text(data.get('id')), name, f'{BASE}/user/{name}/',
                post_karma=number(data.get('link_karma')), comment_karma=number(data.get('comment_karma')),
                created_at=timestamp(data.get('created_utc')),
                text=text((data.get('subreddit') or {}).get('public_description')),
                moderator=data.get('is_mod') is True, admin=data.get('is_employee') is True,
                verified=data.get('verified') is True)


def build_rule(data):
    return Rule(text(data.get('short_name')), text(data.get('description')), text(data.get('kind')))
