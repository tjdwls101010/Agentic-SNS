"""Schema derives its field surface from the same dataclasses as to_dict."""
from dataclasses import fields
from types import UnionType
from typing import get_args, get_origin
from ._models import Post, Comment
from ._entities import Subreddit, User, Rule

_DESCRIPTIONS = {
    'fullname': 'Stable identity including the Reddit kind prefix; t1 and t3 with the same base id are distinct.',
    'url': 'Canonical navigation handle; pass comment URLs to comments and post URLs to post.',
    'parent': 'Parent fullname, t1 for a comment or t3 for the post.',
    'text': 'Received body text; the terminal display normalizes formatting separately.',
    'score': 'Observed score; null means unavailable. score_hidden overrides display for comments.',
    'created_at': 'UTC ISO-8601 timestamp, or null when absent.',
    'num_comments': 'Reddit total including deleted comments; not the parsed comment count.',
    'depth': 'Comment depth, root=0. Display limits do not change the cached depth.',
    'poll': 'Received poll options and nullable vote counts.',
    'media': 'Media URLs and gallery captions; nothing is downloaded.',
    'crosspost': 'Normalized original post metadata.',
}


def field_type(annotation):
    if get_origin(annotation) in (UnionType,):
        types = list(dict.fromkeys(field_type(part)['type'] for part in get_args(annotation)))
        if 'integer' in types and 'number' in types:
            types.remove('integer')
        return {'type': types}
    return {'type': {str: 'string', int: 'integer', float: 'number', bool: 'boolean', list: 'array', dict: 'object', type(None): 'null'}[annotation]}


def schema():
    return {model.__name__: {'type': 'object', 'properties': {
        field.name: {**field_type(field.type), 'description': _DESCRIPTIONS.get(field.name, field.name.replace('_', ' ') + '.')}
        for field in fields(model)}, 'additionalProperties': False}
        for model in (Post, Comment, Subreddit, User, Rule)}
