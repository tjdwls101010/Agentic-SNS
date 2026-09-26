"""Facebook GraphQL responses → exported records. These names are the whole public surface of this package.

Every function is pure: it makes no request and takes `captured_at` from the caller, so the same response always
yields the same records. Records are `to_dict()` output; reply expansion handles are returned beside them.
"""
from dataclasses import dataclass, field

from facebook.graphql.records import about as _about
from facebook.graphql.records import comment as _comment
from facebook.graphql.records import entity as _entity
from facebook.graphql.records import post as _post
from facebook.graphql.records.connection import connection_has_items, find_page_info, search_records
from facebook.graphql.records.parse import iter_json_objects, parse_story_nodes


@dataclass
class Page:
    records: list
    page_info: dict | None
    has_items: bool = False
    issues: list = field(default_factory=list)
    handles: dict = field(default_factory=dict)


def post_page(raw, *, source, connection_key, captured_at):
    """Top-level posts of one feed, timeline, group or search page, in server order."""
    parsed = parse_story_nodes([raw])
    records = [_post.build_post(parsed.stories[key], source=source, captured_at=captured_at).to_dict()
               for key in parsed.top_level_ids()]
    return Page(records, find_page_info(raw, connection_key), connection_has_items(raw, connection_key),
                list(parsed.incomplete_reasons))


def post_story(raw):
    """The permalink's requested root story (None when absent) and the response's decode issues."""
    return _post.requested_story(raw), list(parse_story_nodes([raw]).incomplete_reasons)


def post_record(story, *, source, captured_at):
    return _post.build_post(story, source=source, captured_at=captured_at).to_dict()


def comment_page(raw, *, post_id, captured_at, parents_only):
    """Comments of one page; with parents_only, depth-0 parents and their reply expansion handles."""
    issues = []
    list(iter_json_objects([raw], issues=issues))
    if parents_only:
        records, handles = [], {}
        for node in _comment.iter_comment_nodes([raw]):
            comment = _comment.build_comment(node, post_id=post_id, captured_at=captured_at)
            if comment.depth != 0:
                continue
            records.append(comment.to_dict())
            handles[comment.id] = {'feedback_id': _comment.feedback_id(node),
                                   'expansion_token': _comment.expansion_token(node)}
    else:
        records = [c.to_dict() for c in _comment.build_comments([raw], post_id=post_id, captured_at=captured_at)]
        handles = {}
    return Page(records, find_page_info(raw, 'comments'), connection_has_items(raw, 'comments'), issues, handles)


def reply_page(raw, *, post_id, parent_id, captured_at):
    """Replies to one parent from its expansion response; a reply without a parent link belongs to `parent_id`."""
    replies = []
    for reply in _comment.build_comments([raw], post_id=post_id, captured_at=captured_at):
        if reply.depth <= 0:
            continue
        data = reply.to_dict()
        data['parent_id'] = data['parent_id'] or parent_id
        if data['parent_id'] == parent_id:
            replies.append(data)
    return Page(replies, find_page_info(raw, 'replies_connection'))


def search_page(raw, *, search_type, captured_at, connection_key='results'):
    """One search page: posts and people, pages or groups, in the connection's index order."""
    return Page(search_records(raw, search_type, captured_at), find_page_info(raw, connection_key),
                connection_has_items(raw, connection_key))


def about_collections(raw):
    """The About overview's collections as [{id, name}], in response order."""
    return _about.iter_collections([raw])


def about_fields(bodies, *, profile_id, collection_names, captured_at):
    return [f.to_dict() for f in _about.build_fields(bodies, profile_id=profile_id,
                                                     collection_names=collection_names, captured_at=captured_at)]


SCHEMAS = {'post': _post.json_schema(), 'comment': _comment.json_schema(),
           'entity': _entity.json_schema(), 'about': _about.json_schema()}
