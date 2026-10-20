"""Records in the skill's terms, one builder per kind for every surface that sends it.

Naver names the same value differently on every surface — commentCnt here, commentCount there, contents versus
briefContents versus content — so each is normalized once, here. A field is None when Naver said nothing; "unknown"
is reserved for what this reader could not find out (a post's tags, see body.py). Those are different answers.
Every record starts with the head all platforms' records share: kind, id, url (what the command that opens it alone
takes, or None) and created_at (an ISO time with its offset, or None).
"""
from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from sns.clock import KST

UNKNOWN = 'unknown'
_TAGS = re.compile(r'<[^>]+>')
_LONE_SURROGATE = re.compile('[\ud800-\udfff]')   # what is left when Naver cuts a summary mid-emoji
_ZERO_WIDTH = re.compile('[​-‍﻿]')


def clean(value):
    """Text without highlight markup, tags, entities, zero-width marks or a half emoji; None stays None."""
    if value is None:
        return None
    text = html.unescape(_TAGS.sub('', str(value)))
    return _ZERO_WIDTH.sub('', _LONE_SURROGATE.sub('', text)).strip()


def stamp(value):
    """epoch milliseconds, an ISO time with +0900 or +09:00, a zone-less time (KST) or nothing → one KST minute."""
    if value in (None, '') or isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        value = int(value)
    if isinstance(value, (int, float)):
        try:   # list surfaces send milliseconds; a seconds value would land in 1970
            return datetime.fromtimestamp(value / 1000, KST).isoformat(timespec='minutes')
        except (ValueError, OSError, OverflowError):
            return None
    text = re.sub(r'([+-]\d\d)(\d\d)$', r'\1:\2', str(value).strip()).replace('Z', '+00:00')
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KST)
    return moment.astimezone(KST).isoformat(timespec='minutes')


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def first(raw, *names):
    for name in names:
        if raw.get(name) not in (None, ''):
            return raw[name]
    return None


def _id(value):
    return None if value in (None, '', 0, '0') else str(value)


class Record:
    """What every record shares: to_dict()."""

    def to_dict(self):
        return asdict(self)


@dataclass
class Post(Record):
    kind: str = 'post'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    blog_id: str | None = None
    log_no: str | None = None
    title: str = ''
    summary: str = ''
    blog_name: str | None = None
    nickname: str | None = None
    category_no: str | None = None
    category_name: str | None = None
    like_count: int | None = None
    comment_count: int | None = None
    view_count: int | None = None
    labels: list = field(default_factory=list)
    blog_no: str | None = None


def visibility(raw):
    """The app's own visibility label: notOpen → private, else buddyOpen → buddy-only, else bothBuddyOpen →
    mutual-only. postBlocked is not one (it is true on every blogs-of-the-month post)."""
    if raw.get('notOpen') is True:
        return ['private']
    if raw.get('buddyOpen') is True:
        return ['buddy-only']
    if raw.get('bothBuddyOpen') is True:
        return ['mutual-only']
    return []


def post_record(raw, *, blog_id=None, blog_name=None):
    """A post from any list surface (search, tags, a blog's lists, popular, notices, related, feed, topics)."""
    if not isinstance(raw, dict):
        return None
    log_no, blog = first(raw, 'logNo'), first(raw, 'blogId', 'domainIdOrBlogId') or blog_id
    if log_no is None or blog is None:
        return None
    log_no, blog = str(log_no), str(blog)
    labels = visibility(raw)
    if raw.get('isBuyWithMyOwnMoney') is True or raw.get('buyWithMyOwnMoney') is True:
        labels.append('own-money')   # Naver's 내돈내산 인증 card is on the post; a title or tag saying 내돈내산 is not it
    view = number(raw.get('viewCount')) if 'viewCount' in raw else (number(raw.get('readCount')) or None)
    return Post(id=f'post:{blog}/{log_no}', blog_id=blog, log_no=log_no, url=f'https://blog.naver.com/{blog}/{log_no}',
                title=clean(first(raw, 'title', 'titleWithInspectMessage')) or '',
                summary=clean(first(raw, 'briefContents', 'contents', 'content')) or '',
                created_at=stamp(first(raw, 'addDate', 'regDate', 'adddate')),
                blog_name=clean(first(raw, 'blogName')) or blog_name, nickname=clean(first(raw, 'nickname', 'nickName')),
                category_no=_id(raw.get('categoryNo')),
                category_name=clean(first(raw, 'categoryName')),
                like_count=number(first(raw, 'sympathyCount', 'sympathyCnt', 'likeCount')),
                comment_count=number(first(raw, 'commentCount', 'commentCnt')), view_count=view,
                labels=sorted(set(labels)), blog_no=_id(first(raw, 'blogNo')))


@dataclass
class Comment(Record):
    kind: str = 'comment'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    comment_no: str | None = None
    parent_comment_no: str | None = None
    reply_level: int = 1
    author: str | None = None
    author_blog_id: str | None = None
    text: str = ''
    like_count: int | None = None
    reply_count: int | None = None
    labels: list = field(default_factory=list)
    depth: int = 0
    parent_shown: bool = True


def comment_record(raw, *, post_url=None):
    """One row of the comment box (post_url: the post it belongs to, the only address a comment has). Only a real
    true counts as a flag: the string "false" is not a deletion."""
    if not isinstance(raw, dict) or first(raw, 'commentNo') is None:
        return None
    number_ = str(raw['commentNo'])
    labels = []
    if raw.get('deleted') is True:
        labels.append('deleted')
    if any(raw.get(key) is True for key in ('blind', 'hiddenByCleanbot', 'hiddenByKeyword')):
        labels.append('blinded')
    if raw.get('secret') is True:
        labels.append('secret')
    if raw.get('best') is True:
        labels.append('best')
    status = raw.get('status')
    if status not in (None, 0, '0', '') and not labels:
        labels.append(f'status={status}')   # shown, not acted on: hiding a comment on a guess costs more
    parent = first(raw, 'parentCommentNo')
    # A top-level comment points at itself; repeating that would show every comment as a reply to itself.
    parent = None if _id(parent) is None or str(parent) == number_ else str(parent)
    author_blog = first(raw, 'profileUserId')
    return Comment(id=f'comment:{number_}', url=post_url, comment_no=number_, parent_comment_no=parent,
                   reply_level=number(raw.get('replyLevel')) or 1, author=clean(first(raw, 'userName', 'maskedUserName')),
                   author_blog_id=str(author_blog) if author_blog else None, created_at=stamp(first(raw, 'regTime')),
                   text='' if 'deleted' in labels else clean(first(raw, 'contents')) or '',
                   like_count=number(raw.get('sympathyCount')),
                   reply_count=number(first(raw, 'replyAllCount', 'replyCount')), labels=labels)


def thread_comments(comments):
    """One page of comments in reading order: top-level comments as served (newest first), each followed by its
    replies oldest first, indented; a reply whose parent is not on this page goes last, marked parent not shown."""
    tops = [c for c in comments if c.parent_comment_no is None]
    present = {c.comment_no for c in tops}
    replies = {}
    orphans = []
    for comment in comments:
        if comment.parent_comment_no is None:
            continue
        comment.depth = 1
        if comment.parent_comment_no in present:
            replies.setdefault(comment.parent_comment_no, []).append(comment)
        else:
            comment.parent_shown = False
            orphans.append(comment)
    ordered = []
    for top in tops:
        ordered.append(top)
        ordered += sorted(replies.get(top.comment_no, []), key=lambda c: (c.created_at or '', int(c.comment_no)))
    return ordered + orphans


def comment_counts(count):
    """Naver's own figures for a post's comments (count beside commentList)."""
    count = count if isinstance(count, dict) else {}

    def total(*keys):
        values = [number(count.get(key)) for key in keys]
        return None if all(v is None for v in values) else sum(v or 0 for v in values)
    return {'comments': number(count.get('comment')), 'replies': number(count.get('reply')),
            'deleted': total('delCommentByUser', 'delCommentByMon'),
            'blinded': total('blindCommentByUser', 'blindReplyByUser'), 'total': number(count.get('total'))}


@dataclass
class Blog(Record):
    kind: str = 'blog'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    blog_id: str | None = None
    blog_no: str | None = None
    name: str | None = None
    nickname: str | None = None
    description: str | None = None
    buddy_count: int | None = None
    today_visitors: int | None = None
    total_visitors: int | None = None
    post_count: int | None = None
    clip_count: int | None = None
    directory: str | None = None
    official: bool = False
    market: bool = False
    relation: str | None = None
    labels: list = field(default_factory=list)


def blog_record(raw):
    """A blog from its card, blog search, or a blogs-of-the-month profile."""
    if not isinstance(raw, dict):
        return None
    blog_id = first(raw, 'blogId', 'domainIdOrBlogId')
    if not blog_id:
        return None
    blog_id = str(blog_id)
    relation = 'mutual-neighbor' if raw.get('bothNeighbor') is True else 'neighbor' if raw.get('neighbor') is True else None
    labels = [label for key, label in (('block', 'blocked'), ('powerBlog', 'power-blog')) if raw.get(key) is True]
    return Blog(id=f'blog:{blog_id}', blog_id=blog_id, blog_no=_id(raw.get('blogNo')), name=clean(raw.get('blogName')),
                nickname=clean(first(raw, 'nickName', 'nickname')), description=clean(first(raw, 'blogDesc', 'introduce')),
                url=f'https://blog.naver.com/{blog_id}',
                buddy_count=number(raw['subscriberCount'] if 'subscriberCount' in raw else raw.get('buddyCount')),
                today_visitors=number(raw.get('dayVisitorCount')), total_visitors=number(raw.get('totalVisitorCount')),
                post_count=number(raw.get('mylogPostCount')),
                directory=clean(first(raw, 'blogDirectoryName', 'subjectName')), official=raw.get('officialBlog') is True,
                market=raw.get('isMarketBlog') is True, relation=relation, labels=labels)


@dataclass
class Category(Record):
    kind: str = 'category'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    blog_id: str | None = None
    category_no: str | None = None
    name: str | None = None
    parent_no: str | None = None
    depth: int = 0
    post_count: int | None = None
    open: bool = True


def categories(rows, blog_id):
    """A blog's category tree: dividers are layout rows, not categories; depth follows the parents."""
    found = []
    for raw in rows or []:
        if not isinstance(raw, dict) or raw.get('divisionLine') is True or raw.get('categoryType') == 'S':
            continue
        if raw.get('categoryNo') is None:
            continue
        found.append(Category(id=f'category:{blog_id}/{raw["categoryNo"]}',
                              url=f'https://blog.naver.com/PostList.naver?blogId={blog_id}&categoryNo={raw["categoryNo"]}',
                              blog_id=blog_id, category_no=str(raw['categoryNo']), name=clean(raw.get('categoryName')),
                              parent_no=_id(raw.get('parentCategoryNo')), post_count=number(raw.get('postCnt')),
                              open=raw.get('openYN') not in ('N', False)))
    by_number = {category.category_no: category for category in found}
    for category in found:
        depth, cursor = 0, category
        while cursor.parent_no in by_number and depth < 10:
            cursor, depth = by_number[cursor.parent_no], depth + 1
        category.depth = depth
    return found


@dataclass
class Buddy(Record):
    kind: str = 'buddy'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    blog_id: str | None = None
    name: str | None = None
    nickname: str | None = None
    mutual: bool = False
    official: bool = False
    updated_at: str | None = None
    group_id: str | None = None


def buddy_record(raw):
    """A neighbor from any list (mine, public, the blogs that added me)."""
    if not isinstance(raw, dict) or not raw.get('blogId'):
        return None
    blog_id = str(raw['blogId'])
    # updateTime is a relative phrase on public lists ("3일 전"); only a real time is a date.
    return Buddy(id=f'buddy:{blog_id}', blog_id=blog_id, name=clean(raw.get('blogName')),
                 nickname=clean(raw.get('nickName')),
                 url=f'https://blog.naver.com/{blog_id}', mutual=raw.get('bothNeighbor') is True,
                 official=raw.get('officialBlog') is True,
                 updated_at=stamp(first(raw, 'updateTime')) or stamp(raw.get('recentlyUpdate')),
                 group_id=_id(raw.get('groupId')))


@dataclass
class Topic(Record):
    kind: str = 'topic'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    seq: str | None = None
    name: str | None = None
    group: str | None = None


def topics(groups):
    """The topic directory: groups of topics, each addressed by its seq."""
    found = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        for raw in group.get('directoryList') or []:
            if isinstance(raw, dict) and raw.get('seq') is not None:
                found.append(Topic(id=f'topic:{raw["seq"]}', seq=str(raw['seq']), name=clean(raw.get('name')),
                                   group=clean(group.get('name'))))
    return found


@dataclass
class Clip(Record):
    kind: str = 'clip'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    blog_id: str | None = None
    doc_no: str | None = None
    title: str = ''
    play_seconds: int | None = None
    nickname: str | None = None


def clip_record(raw):
    """A clip (a short video) from clip search; its page is m.blog.naver.com/<blogId>/clip/<docNo> (the app's route)."""
    if not isinstance(raw, dict) or not raw.get('blogId') or raw.get('docNo') in (None, ''):
        return None
    blog, doc = str(raw['blogId']), str(raw['docNo'])
    return Clip(id=f'clip:{blog}/{doc}', blog_id=blog, doc_no=doc, url=f'https://m.blog.naver.com/{blog}/clip/{doc}',
                title=clean(first(raw, 'originTitle', 'title')) or '', play_seconds=number(raw.get('playTime')),
                created_at=stamp(raw.get('addDate')), nickname=clean(raw.get('nickname')))


@dataclass
class Keyword(Record):
    kind: str = 'keyword'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    keyword: str | None = None
    rank: int | None = None


def keyword_records(values):
    """Keywords in Naver's order, ranked from 1: popular ones arrive as {keyword}, related ones as plain strings."""
    found = []
    for value in values or []:
        text = clean(value.get('keyword') if isinstance(value, dict) else value)
        if text:
            found.append(Keyword(id=f'keyword:{text}', keyword=text, rank=len(found) + 1))
    return found


@dataclass
class Group(Record):
    kind: str = 'group'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    group_id: str | None = None
    name: str | None = None


def group_record(raw):
    """One of the viewer's neighbor groups."""
    if not isinstance(raw, dict) or raw.get('groupId') is None:
        return None
    return Group(id=f'group:{raw["groupId"]}', group_id=str(raw['groupId']), name=clean(raw.get('groupName')))


@dataclass
class Resolved(Record):
    kind: str = 'link'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    link: str | None = None
    status: int | None = None
    destination: dict | None = None
    post: str | None = None


@dataclass
class Saved(Record):
    """One picture images saved: Read its path to look at it."""
    kind: str = 'image'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    n: int | None = None
    picture_kind: str | None = None
    caption: str | None = None
    path: str | None = None
    bytes: int = 0
    content_type: str | None = None


# What each field means to a reader, beside its type; schema prints these.
_HEAD = {'kind': 'the record type', 'created_at': 'an ISO time with its offset (KST), or null when there is none'}
NOTES = {
    'post': {'__doc__': 'A post from a list surface (search, a blog\'s lists, the feed, topics). Its summary is Naver\'s '
                        'excerpt, cut at a character count.',
             'id': 'post:<blogId>/<logNo>; what --out deduplicates and resumes on',
             'blog_id': 'the blog id in the URL (it can be digits only); not blog_no',
             'url': 'https://blog.naver.com/<blogId>/<logNo>; post <url> reads it in full',
             'summary': 'Naver\'s excerpt, cut at a character count: its ending is where the string stopped, not where '
                        'the writer did',
             'created_at': 'KST minute', 'like_count': 'the count this list surface sent (it can lag the post\'s own)',
             'view_count': 'only popular posts carry one (and the viewer\'s own blog); null elsewhere, never a zero',
             'labels': 'private, buddy-only, mutual-only (visibility, as the app labels it); own-money: the post carries '
                       'Naver\'s 내돈내산 인증 card — a purchase or visit Naver recorded and the writer attached (a title '
                       'or tag saying 내돈내산 is not it)',
             'blog_no': 'the blog\'s internal number (the comment box is keyed by it)'},
    'comment': {'__doc__': 'One comment or reply of a post, in reading order: top-level comments newest first, each '
                           'followed by its replies oldest first.',
                'id': 'comment:<commentNo>', 'url': 'the post it belongs to (comments <url> reads it); a comment has no '
                                                    'address of its own',
                'parent_comment_no': 'the comment this replies to; null for a top-level comment',
                'depth': '1 for a reply', 'parent_shown': 'false when the reply\'s parent is on another page',
                'author_blog_id': 'the commenter\'s blog: blog <id> is the next hop to a person',
                'labels': 'deleted (text emptied), blinded (hidden by Naver), secret, best, status=<raw>',
                'reply_count': 'replies Naver counts under it'},
    'blog': {'__doc__': 'A blog\'s card (blog), a blog search result, or a blogs-of-the-month profile.',
             'created_at': 'null: a card carries no creation time',
             'buddy_count': 'neighbor count from the card; the public neighbor list is private by default, so it '
                            'rarely matches that list',
             'post_count': 'the blog\'s own post total', 'clip_count': 'its clips (short videos)',
             'relation': 'how the logged-in viewer stands to it: neighbor, mutual-neighbor or null',
             'labels': 'blocked, power-blog'},
    'category': {'__doc__': 'One category of a blog\'s tree (dividers left out).',
                 'url': 'the category\'s list address; posts <url> reads it', 'created_at': 'null',
                 'category_no': 'what posts --category takes', 'open': 'false for a closed category (its posts are '
                                                                        'counted, not listed)'},
    'buddy': {'__doc__': 'A neighbor in a list (mine, a blog\'s public one, the blogs that added me).',
              'created_at': 'null: use updated_at', 'mutual': 'true for mutual neighbors (서로이웃)',
              'group_id': 'the viewer\'s neighbor group'},
    'topic': {'__doc__': 'A topic of the directory.', 'url': 'null: a topic is opened by its seq',
              'created_at': 'null', 'seq': 'what topic takes'},
    'clip': {'__doc__': 'A clip (short video) from search --type clips.', 'url': 'the clip\'s page',
             'play_seconds': 'its length in seconds', 'title': 'the clip\'s own title'},
    'keyword': {'__doc__': 'A keyword from keywords: Naver\'s popular blog searches of a day, or the searches related '
                           'to one keyword.', 'url': 'null', 'created_at': 'null',
                'rank': 'Naver\'s order, from 1; a ranking, not a share of searches'},
    'link': {'__doc__': 'Where one naver.me link leads (resolve), read without following it.',
             'url': 'the link as given', 'created_at': 'null',
             'destination': '{url, text, host, link_id} of the redirect target, or null when there is none',
             'post': 'blogId/logNo when the destination is a Naver Blog post'},
    'group': {'__doc__': 'One of the logged-in account\'s neighbor groups (buddies --groups).', 'url': 'null',
              'created_at': 'null', 'group_id': 'what buddies --group and feed --group take'},
    'image': {'__doc__': 'One picture images saved: other people\'s photos, removed 24 hours after saving.',
              'id': 'image:<blogId>/<logNo>#<n>', 'url': 'the post the picture is in', 'created_at': 'null',
              'n': 'the picture number post shows ([image N])',
              'picture_kind': 'photo, sticker, cover, thumbnail or map',
              'path': 'the local file; Read it to look at the picture'},
}


def _type(annotation):
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        return ' | '.join(_type(argument) for argument in arguments)
    if origin is list or annotation is list:
        return 'array'
    if origin is dict or annotation is dict:
        return 'object'
    return {str: 'string', int: 'integer', bool: 'boolean', type(None): 'null'}.get(annotation, 'object')


def record_schema(name, cls, notes, skip=()):
    """A record's fields from its dataclass, never from a hand-kept list that drifts."""
    hints = get_type_hints(cls)
    return {'object': name, 'description': notes.get('__doc__', name),
            'fields': {f.name: f'{_type(hints[f.name])} — ' + notes.get(f.name, _HEAD.get(f.name) or
                                                                      f.name.replace('_', ' ') +
                                                                      '; null when Naver sent nothing')
                       for f in fields(cls) if f.name not in skip}}
