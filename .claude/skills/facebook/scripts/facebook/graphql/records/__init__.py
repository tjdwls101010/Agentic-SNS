"""Decoded GraphQL chunks → the skill's records. Pure: no request, `captured_at` comes from the caller."""
from dataclasses import dataclass, field

from facebook.graphql.records import comments, posts, search
from facebook.graphql.records.parse import find_page_info, has_items


@dataclass
class Page:
    """One page of a connection: records in server order, its page_info, whether it had items, response issues."""
    records: list
    page_info: dict | None
    has_items: bool = False
    issues: list = field(default_factory=list)
    handles: dict = field(default_factory=dict)


def posts_page(chunks, *, source, connection_key, captured_at):
    """The top-level posts of one feed, timeline, group or search page."""
    records, issues = posts.top_level(chunks, source=source, captured_at=captured_at)
    return Page(records, find_page_info(chunks, connection_key), has_items(chunks, connection_key), issues)


def permalink_post(chunks, *, captured_at):
    """(the permalink's own post or None, response issues)."""
    return posts.permalink(chunks, captured_at=captured_at)


def comments_page(chunks, *, post_id, captured_at):
    """A post's parent comments in server order, with each one's reply handle in .handles."""
    records, handles, info = comments.parents(chunks, post_id=post_id, captured_at=captured_at)
    return Page(records, info, has_items(chunks, 'comments'), comments.issues(chunks), handles)


def replies_page(chunks, *, post_id, parent_id, captured_at):
    """One batch of replies to `parent_id`, with each reply's own reply handle in .handles."""
    records, handles, info = comments.replies(chunks, post_id=post_id, parent_id=parent_id, captured_at=captured_at)
    return Page(records, info, has_items(chunks, 'replies_connection'), comments.issues(chunks), handles)


def search_page(chunks, *, vertical, captured_at):
    """One page of search results (top, posts, people, pages or groups) in the connection's order."""
    records, issues = search.results(chunks, vertical=vertical, captured_at=captured_at)
    return Page(records, find_page_info(chunks, 'results'), has_items(chunks, 'results'), issues)


SCHEMAS = {
    'post': {'object': 'post', 'description': 'A post from feed, profile, group, search or post.', 'fields': posts.FIELDS},
    'entity': {'object': 'entity', 'description': 'A person, page or group from search.', 'fields': search.FIELDS},
    'comment': {'object': 'comment', 'description': 'A comment or reply from post, comments or replies.',
                'fields': comments.FIELDS},
}
