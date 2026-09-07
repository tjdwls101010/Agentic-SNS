"""Blogs, categories, neighbours and topics — the things a post hangs from."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ._models import clean, number, stamp


@dataclass
class Blog:
    id: str | None = None
    blog_id: str | None = None
    blog_no: str | None = None
    name: str | None = None
    nickname: str | None = None
    description: str | None = None
    url: str | None = None
    buddy_count: int | None = None
    today_visitors: int | None = None
    total_visitors: int | None = None
    post_count: int | None = None
    directory: str | None = None
    official: bool = False
    market: bool = False
    # How the viewer stands to this blog, when Naver said: neighbour, mutual, or neither.
    relation: str | None = None
    labels: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def build_blog(raw):
    if not isinstance(raw, dict):
        return None
    blog_id = raw.get('blogId')
    if not blog_id:
        return None
    blog_id = str(blog_id)
    relation = None
    if raw.get('bothNeighbor'):
        relation = 'mutual-neighbor'
    elif raw.get('neighbor'):
        relation = 'neighbor'
    labels = []
    if raw.get('block'):
        labels.append('blocked')
    if raw.get('powerBlog'):
        labels.append('power-blog')
    blog_no = raw.get('blogNo')
    return Blog(
        id=f'blog:{blog_id}', blog_id=blog_id, blog_no=None if blog_no is None else str(blog_no),
        # blogNameWithTag is the highlighted copy; the plain field is the real name.
        name=clean(raw.get('blogName')), nickname=clean(raw.get('nickName') or raw.get('nickname')),
        description=clean(raw.get('blogDesc')), url=f'https://blog.naver.com/{blog_id}',
        buddy_count=number(raw.get('subscriberCount') if 'subscriberCount' in raw else raw.get('buddyCount')),
        today_visitors=number(raw.get('dayVisitorCount')), total_visitors=number(raw.get('totalVisitorCount')),
        post_count=number(raw.get('mylogPostCount')), directory=clean(raw.get('blogDirectoryName')),
        official=bool(raw.get('officialBlog')), market=bool(raw.get('isMarketBlog')),
        relation=relation, labels=labels)


@dataclass
class Category:
    id: str | None = None
    blog_id: str | None = None
    category_no: str | None = None
    name: str | None = None
    parent_no: str | None = None
    depth: int = 0
    post_count: int | None = None
    open: bool = True

    def to_dict(self):
        return asdict(self)


def build_categories(rows, blog_id):
    """A divider is a layout row, not a category; children are nested under their parent."""
    categories = []
    for raw in rows or []:
        if not isinstance(raw, dict) or raw.get('divisionLine') or raw.get('categoryType') == 'S':
            continue
        number_of = raw.get('categoryNo')
        if number_of is None:
            continue
        parent = raw.get('parentCategoryNo')
        parent = None if parent in (None, '', 0, '0') else str(parent)
        categories.append(Category(
            id=f'category:{blog_id}/{number_of}', blog_id=blog_id, category_no=str(number_of),
            name=clean(raw.get('categoryName')), parent_no=parent,
            post_count=number(raw.get('postCnt')), open=raw.get('openYN') != 'N'))
    by_number = {category.category_no: category for category in categories}
    for category in categories:
        depth, cursor = 0, category
        while cursor.parent_no and cursor.parent_no in by_number and depth < 10:
            cursor = by_number[cursor.parent_no]
            depth += 1
        category.depth = depth
    return categories


@dataclass
class Buddy:
    id: str | None = None
    blog_id: str | None = None
    name: str | None = None
    nickname: str | None = None
    url: str | None = None
    mutual: bool = False
    official: bool = False
    updated_at: str | None = None
    group_id: str | None = None

    def to_dict(self):
        return asdict(self)


def build_buddy(raw):
    if not isinstance(raw, dict) or not raw.get('blogId'):
        return None
    blog_id = str(raw['blogId'])
    group = raw.get('groupId')
    return Buddy(id=f'buddy:{blog_id}', blog_id=blog_id, name=clean(raw.get('blogName')),
                 nickname=clean(raw.get('nickName')), url=f'https://blog.naver.com/{blog_id}',
                 mutual=bool(raw.get('bothNeighbor')), official=bool(raw.get('officialBlog')),
                 updated_at=stamp(raw.get('updateTime') or raw.get('recentlyUpdate')),
                 group_id=None if group in (None, '', 0, '0') else str(group))


@dataclass
class Topic:
    id: str | None = None
    seq: str | None = None
    name: str | None = None
    group: str | None = None

    def to_dict(self):
        return asdict(self)


def build_topics(groups):
    """The directory is four groups of topics; a topic is addressed by its seq."""
    topics = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        for raw in group.get('directoryList') or []:
            if isinstance(raw, dict) and raw.get('seq') is not None:
                topics.append(Topic(id=f'topic:{raw["seq"]}', seq=str(raw['seq']),
                                    name=clean(raw.get('name')), group=clean(group.get('name'))))
    return topics
