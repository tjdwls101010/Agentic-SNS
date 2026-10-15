"""Decoded GraphQL chunks → the skill's records. Pure: no request, `captured_at` comes from the caller."""
from dataclasses import dataclass, field

from facebook.graphql.records import posts
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


SCHEMAS = {
    'post': {'object': 'post', 'description': 'A post from feed, profile, group, search or post.', 'fields': posts.FIELDS},
}
