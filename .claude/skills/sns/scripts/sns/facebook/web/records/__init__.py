"""Decoded GraphQL chunks → the skill's records. Pure: no request, `captured_at` comes from the caller.

Every record carries the head keys kind, id, url and created_at (the shared machinery reads them); a Facebook record
also says where it was read from (a post: source) or what it belongs to (a comment: post_id).
"""
from dataclasses import dataclass, field

from sns.facebook.web.records import about, comments, groups, posts, search
from sns.facebook.web.records.parse import find_page_info, has_items


@dataclass
class Batch:
    """One answer of a connection: records in server order, its page_info, whether it had items, response issues, and
    (comments) what expands each record's replies."""
    records: list
    page_info: dict | None
    has_items: bool = False
    issues: list = field(default_factory=list)
    handles: dict = field(default_factory=dict)


def posts_page(chunks, *, source, connection_key, captured_at):
    """The top-level posts of one feed, timeline, group or search page."""
    records, issues = posts.top_level(chunks, source=source, captured_at=captured_at)
    return Batch(records, find_page_info(chunks, connection_key), has_items(chunks, connection_key), issues)


def permalink_post(chunks, *, captured_at):
    """(the permalink's own post or None, response issues)."""
    return posts.permalink(chunks, captured_at=captured_at)


def comments_page(chunks, *, post_id, captured_at):
    """A post's parent comments in server order, with each one's reply handle in .handles."""
    records, handles, info = comments.parents(chunks, post_id=post_id, captured_at=captured_at)
    return Batch(records, info, has_items(chunks, 'comments'), comments.issues(chunks), handles)


def replies_page(chunks, *, post_id, parent_id, captured_at, depth=1):
    """One batch of replies to `parent_id` (at `depth`), with each reply's own reply handle in .handles."""
    records, handles, info = comments.replies(chunks, post_id=post_id, parent_id=parent_id, captured_at=captured_at,
                                              depth=depth)
    return Batch(records, info, has_items(chunks, 'replies_connection'), comments.issues(chunks), handles)


def search_page(chunks, *, vertical, captured_at):
    """One page of search results (top, posts, people, pages or groups) in the connection's order."""
    records, issues = search.results(chunks, vertical=vertical, captured_at=captured_at)
    return Batch(records, find_page_info(chunks, 'results'), has_items(chunks, 'results'), issues)


def about_collections(chunks):
    """The About tabs the overview lists, as [{name, id}]."""
    return about.collections(chunks)


def about_fields(bodies, *, profile_id, collection_names, captured_at):
    """(About field records from the overview and collection responses, response issues)."""
    return about.fields(bodies, profile_id=profile_id, collection_names=collection_names, captured_at=captured_at)


def group_card(chunks, *, group_id, captured_at):
    """(the group's card from its header, or None; response issues)."""
    return groups.card(chunks, group_id=group_id, captured_at=captured_at)


def group_about(chunks):
    """(description, privacy explanation, activity, creation time, exact member text and rules from a group's About
    screen, or None; response issues)."""
    return groups.about(chunks)


DOCTOR = {
    'object': 'doctor',
    'description': 'What Facebook adds to doctor\'s results[0] (the fields every platform has are in schema result): '
                   'the dedicated tab and which read queries the page has loaded. doctor opens the tab when none is '
                   'open (about 30 requests the page makes itself while it loads, measured) and otherwise makes no '
                   'request; with --unblock it makes one more, a feed read, whose answer decides.',
    'fields': {
        'tab': 'object — {target_id, opened_now}: the dedicated www.facebook.com tab and whether this command opened '
               'it (a recorded tab that was gone or emptied to about:blank is replaced by a new one)',
        'queries': 'object — each read query the skill sends: "live in the tab" when the page has loaded it (its id '
                   'and provider values are used), or "stored" (the id an earlier read learned, else the bundled '
                   'snapshot, is sent)',
    },
}

SCHEMAS = {
    'post': {'object': 'post', 'description': 'A post from feed, profile, group, search or post.', 'fields': posts.FIELDS},
    'entity': {'object': 'entity', 'description': 'A person, page or group from search.', 'fields': search.FIELDS},
    'about': {'object': 'about', 'description': 'One visible About field from about.', 'fields': about.FIELDS},
    'group': {'object': 'group', 'description': 'A group\'s card from about <group URL>.', 'fields': groups.FIELDS},
    'comment': {'object': 'comment', 'description': 'A comment or reply from post, comments or replies.',
                'fields': comments.FIELDS},
    'doctor': DOCTOR,
}
