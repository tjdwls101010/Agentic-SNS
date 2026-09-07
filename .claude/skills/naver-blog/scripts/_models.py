"""Six post surfaces, one Post; three date formats, one timestamp.

Naver names the same value differently on every surface — commentCnt here, commentCount
there, contents versus briefContents versus content — so a reader that branches per
surface would carry that inconsistency into every command. It is normalized once, here.

A field is null when Naver said there is nothing, and "unknown" when this reader could
not find out. Those are different answers and collapsing them would make a missing tag
list read as a post with no tags.
"""
from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
UNKNOWN = 'unknown'
# Two highlight markups, one per search surface; the plain field is preferred when it exists.
HIGHLIGHT = re.compile(r'</?(?:em|strong)\b[^>]*>', re.I)
TAGS = re.compile(r'<[^>]+>')
# A lone surrogate is what remains when Naver truncates a summary mid-emoji.
LONE_SURROGATE = re.compile('[\ud800-\udfff]')


def clean(value):
    """Strip highlight markup and entities; a half-emoji left by truncation is removed."""
    if value is None:
        return None
    text = HIGHLIGHT.sub('', str(value))
    text = TAGS.sub('', text)
    text = html.unescape(text)
    text = LONE_SURROGATE.sub('', text)
    return re.sub(r'[​-‍﻿]', '', text).strip()


def stamp(value):
    """epoch milliseconds, ISO with +0900, or nothing; all three become one KST timestamp."""
    if value in (None, ''):
        return None
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        value = int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            # Naver's list surfaces are milliseconds; a seconds value would land in 1970.
            return datetime.fromtimestamp(value / 1000, KST).isoformat(timespec='minutes')
        except (ValueError, OSError, OverflowError):
            return None
    try:
        moment = datetime.fromisoformat(str(value).replace('+0900', '+09:00'))
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
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        return int(value)
    return None


def first(raw, *names):
    for name in names:
        if name in raw and raw[name] not in (None, ''):
            return raw[name]
    return None


@dataclass
class Post:
    id: str | None = None
    blog_id: str | None = None
    log_no: str | None = None
    url: str | None = None
    title: str = ''
    summary: str = ''
    created_at: str | None = None
    blog_name: str | None = None
    nickname: str | None = None
    category_no: str | None = None
    category_name: str | None = None
    like_count: int | str | None = None
    comment_count: int | None = None
    view_count: int | None = None
    tags: list | str = field(default_factory=list)
    labels: list = field(default_factory=list)
    # Only a post read fills this; a list surface carries summary instead.
    body: dict | None = None

    def to_dict(self):
        return asdict(self)


def build_post(raw, *, blog_id=None, blog_name=None, nickname=None):
    """One builder for search, tag search, post lists, popular, notices, related and the feed."""
    if not isinstance(raw, dict):
        return None
    log_no = first(raw, 'logNo')
    # Topic listings name the blog domainIdOrBlogId; everywhere else it is blogId.
    blog = first(raw, 'blogId', 'domainIdOrBlogId') or blog_id
    if log_no is None or blog is None:
        return None
    log_no, blog = str(log_no), str(blog)
    labels = []
    # allOpenPost false means the post exists but this reader may not see its body.
    if raw.get('allOpenPost') is False:
        labels.append('buddy-only' if raw.get('buddyOpen') else 'private')
    if raw.get('notOpen'):
        labels.append('private')
    if raw.get('postBlocked'):
        labels.append('blocked')
    if raw.get('isBuyWithMyOwnMoney'):
        labels.append('buy-with-own-money')
    category = first(raw, 'categoryNo')
    return Post(
        id=f'post:{blog}/{log_no}', blog_id=blog, log_no=log_no,
        url=f'https://blog.naver.com/{blog}/{log_no}',
        # titleWithInspectMessage carries a moderation note; the plain title is preferred.
        title=clean(first(raw, 'title', 'titleWithInspectMessage')) or '',
        summary=clean(first(raw, 'briefContents', 'contents', 'content')) or '',
        created_at=stamp(first(raw, 'addDate', 'regDate')),
        blog_name=clean(first(raw, 'blogName')) or blog_name,
        nickname=clean(first(raw, 'nickname', 'nickName')) or nickname,
        category_no=None if category is None else str(category),
        category_name=clean(first(raw, 'categoryName')),
        like_count=number(first(raw, 'sympathyCount', 'sympathyCnt')),
        comment_count=number(first(raw, 'commentCount', 'commentCnt')),
        # viewCount comes only from popular posts. readCount is a real number only on the
        # viewer's own blog and a constant 0 everywhere else, so a zero there is dropped
        # rather than reported as "nobody read this".
        view_count=number(first(raw, 'viewCount')) if 'viewCount' in raw
        else (number(raw.get('readCount')) or None),
        labels=sorted(set(labels)))


@dataclass
class Comment:
    id: str | None = None
    comment_no: str | None = None
    parent_comment_no: str | None = None
    reply_level: int = 1
    author: str | None = None
    author_blog_id: str | None = None
    created_at: str | None = None
    text: str = ''
    like_count: int | None = None
    reply_count: int | None = None
    labels: list = field(default_factory=list)
    parent_shown: bool = True

    def to_dict(self):
        return asdict(self)


def build_comment(raw):
    """Replies arrive flat at replyLevel 2; replyList is always null, so nesting is rebuilt here."""
    if not isinstance(raw, dict):
        return None
    comment_no = first(raw, 'commentNo')
    if comment_no is None:
        return None
    comment_no = str(comment_no)
    # Only a real boolean counts: the string "false" is truthy in Python and would blank a
    # comment that Naver never deleted.
    def flag(*names):
        return any(raw.get(name) is True for name in names)

    labels = []
    if flag('deleted'):
        labels.append('deleted')
    if flag('blind', 'hiddenByCleanbot'):
        labels.append('blinded')
    if flag('secret'):
        labels.append('secret')
    status = raw.get('status')
    # A status this reader does not recognize is shown rather than acted on; hiding a comment
    # on a guess costs more than showing an unfamiliar word next to it.
    if status not in (None, 0, '0', '') and not labels:
        labels.append(f'status={status}')
    parent = first(raw, 'parentCommentNo')
    # Naver points a top-level comment at itself rather than at nothing. Repeating that
    # would show every comment as a reply to itself.
    parent = None if parent in (None, '', '0', 0) or str(parent) == comment_no else str(parent)
    author_blog = first(raw, 'profileUserId')
    return Comment(
        id=f'comment:{comment_no}', comment_no=comment_no,
        parent_comment_no=parent,
        reply_level=number(raw.get('replyLevel')) or 1,
        author=clean(first(raw, 'userName', 'maskedUserName')),
        author_blog_id=str(author_blog) if author_blog else None,
        created_at=stamp(first(raw, 'regTime')),
        text='' if 'deleted' in labels else clean(first(raw, 'contents')) or '',
        like_count=number(raw.get('sympathyCount')), reply_count=number(raw.get('replyCount')),
        labels=labels)


def link_replies(comments):
    """Mark a reply whose parent is not on this page, so an indent never implies a missing quote."""
    present = {comment.comment_no for comment in comments}
    for comment in comments:
        comment.parent_shown = comment.parent_comment_no is None or comment.parent_comment_no in present
    return comments
