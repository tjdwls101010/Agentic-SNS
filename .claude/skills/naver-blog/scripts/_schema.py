"""The field inventory is derived from the objects themselves, not written down twice.

A hand-kept list of fields is a copy that drifts the first time a dataclass gains one, and
the drift is silent: schema keeps describing a field nobody returns any more.
"""
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from ._entities import Blog, Buddy, Category, Topic
from ._models import Comment, Post

CLASSES = {'Post': Post, 'Comment': Comment, 'Blog': Blog, 'Category': Category,
           'Buddy': Buddy, 'Topic': Topic}

NOTES = {
    'id': 'Namespaced identity (post:<blogId>/<logNo>, blog:<blogId>, comment:<commentNo>); '
          'this is what --out deduplicates and resumes on.',
    'blog_id': 'The blog id in its URL, which may be digits only, and is not the numeric blogNo.',
    'blog_no': "The blog's internal number; the comment box is keyed by this, not by blog_id.",
    'log_no': 'Post number as a string; Naver has never fixed its width.',
    'url': 'Canonical blog.naver.com URL; pass it straight back to post or blog.',
    'created_at': 'KST timestamp. Naver sends epoch milliseconds on lists and +0900 strings '
                  'on comments; both arrive here as one format.',
    'summary': "Naver's own excerpt, which can be cut mid-character; a broken half-emoji is dropped.",
    'like_count': 'Sympathy count when Naver supplied one. "unknown" means it was not determined, '
                  'which is not the same as zero.',
    'view_count': 'Only popular posts carry a view count, and only your own blog carries a read count.',
    'tags': 'Post tags. "unknown" means the post page did not carry the tag variable at all, '
            'which is not the same as a post with no tags.',
    'labels': 'What Naver said about this item: private, buddy-only, blocked, buy-with-own-money.',
    'category_no': 'Category number; the argument --category takes.',
    'parent_comment_no': "The parent's own number, so it can be looked for even off this page.",
    'parent_shown': 'False when the parent of this reply is not on the page being displayed.',
    'reply_level': 'Replies arrive flat at level 2; Naver never nests them.',
    'author_blog_id': "A commenter's blog id when Naver supplied one; it is the next hop.",
    'buddy_count': 'Neighbour count from the card. The public neighbour list is usually empty '
                   'because private is the default, so this number and that list rarely agree.',
    'post_count': "The category list's own total, which is the only post total Naver reports honestly.",
    'relation': 'How the logged-in viewer stands to this blog: neighbor, mutual-neighbor, or nothing.',
    'open': 'False for a closed category; its posts are counted but not listed.',
    'mutual': 'True when the neighbour relationship goes both ways.',
    'seq': 'Topic number; the argument the topic command takes.',
}

STOP_REASONS = {
    'limit_reached': 'The display limit was reached; more: continues.',
    'exhausted': 'Naver returned a short page well away from any ceiling.',
    'window_reached': 'A newest-first surface passed below --since; only these two mean nothing was missed.',
    'budget': "This command's local request cap was reached.",
    'blocked': 'Blocked locally or by Naver; the next command will fail too.',
    'query_failure': 'A page failed partway; what came before it is still here.',
    'query_restricted': 'Naver restricted the query. Whatever arrived is included; it is not an empty result.',
    'not_paginable': 'This surface serves one page and Naver offers no second one.',
    'server_capped': "Naver stopped serving at its own ceiling; narrow the window or the keyword to see more.",
    'pagination_stalled': 'A page repeated, so asking again cannot be told apart from the end.',
}


def field_type(annotation):
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        return {'anyOf': [field_type(argument) for argument in arguments]}
    if origin is list or annotation is list:
        return {'type': 'array', 'items': field_type(arguments[0]) if arguments else {}}
    if origin is dict or annotation is dict:
        return {'type': 'object'}
    return {'type': {str: 'string', int: 'integer', bool: 'boolean', type(None): 'null'}[annotation]}


def schema():
    definitions = {}
    for name, cls in CLASSES.items():
        sample = cls().to_dict()
        annotations = get_type_hints(cls)
        properties = {}
        for key in sample:
            note = NOTES.get(key, key.replace('_', ' ') + '; null means Naver supplied nothing.')
            properties[key] = field_type(annotations[key]) | {'description': note}
        definitions[name] = {'type': 'object', 'properties': properties,
                             'required': list(sample), 'additionalProperties': False}
    definitions['ReadResult'] = {
        'type': 'object',
        'required': ['ok', 'command', 'stop_reason', 'next', 'budget', 'fetched_bytes'],
        'properties': {
            'ok': {'type': 'boolean'},
            'results': {'type': 'array', 'items': {'anyOf': [{'$ref': '#/$defs/' + name} for name in CLASSES]}},
            'sections': {'type': 'array', 'description':
                         'A composite command answers in sections; a failed one keeps its error '
                         'beside the ones that succeeded.'},
            'stop_reason': {'enum': list(STOP_REASONS)},
            'next': {'type': ['string', 'null'], 'description':
                     'The continuation command. Naver resumes by page number, so posts added since '
                     'the first read can shift the boundary.'},
            'reported_total': {'type': ['integer', 'null'], 'description':
                               "Naver's own figure. It drifts between pages and becomes 0 past the "
                               'search ceiling, so it is shown and never used to decide anything.'},
            'budget': {'type': 'object', 'description':
                       "This tool's own count of requests made, not an allowance Naver granted."},
            'fetched_bytes': {'type': 'integer'},
        }}
    return {'ok': True, '$schema': 'https://json-schema.org/draft/2020-12/schema', '$defs': definitions,
            'stop_reasons': STOP_REASONS,
            'unknown': 'A field reading "unknown" was not determined by this reader; a field reading '
                       'null is one Naver said nothing about. A summary may not treat them alike.'}
