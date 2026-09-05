"""Schema fields come from the same to_dict interface as emitted records."""
import types
from typing import get_args, get_origin, get_type_hints
from ._entities import User, List, Community, Trend
from ._models import Tweet, Media

MEANINGS = {
    'id': 'Stable X rest_id; join and deduplicate by this field, never by handle.',
    'author': 'Author of this row; for reposts this is the reposter.',
    'text': 'Full text, note_tweet preferred; reposts display the original text.',
    'url': 'Next-hop URL; for reposts points to the original post.',
    'created_at': 'ISO-8601 UTC timestamp of the row, or null if unknown.',
    'quoted_tweet_id': 'Quoted post ID even when X omitted its embedded body.',
    'retweeted_tweet': 'Original post behind a repost row.',
    'is_blue_verified': 'Paid subscription marker, not an identity verification claim.',
    'in_reply_to_id': 'Immediate parent post ID, which may be absent from this page.',
    'community': 'Community metadata supplied by X.',
}


def json_type(annotation):
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin is types.UnionType:
        return {'anyOf': [json_type(item) for item in arguments]}
    if origin is list or annotation is list:
        return {'type': 'array', 'items': json_type(arguments[0]) if arguments else {}}
    if origin is dict or annotation is dict:
        return {'type': 'object'}
    if annotation in (str, int, bool, float, type(None)):
        return {'type': {str: 'string', int: 'integer', bool: 'boolean', float: 'number', type(None): 'null'}[annotation]}
    return {'$ref': '#/$defs/' + annotation.__name__}


def schema():
    objects = {}
    for cls in (Tweet, User, Media, List, Community, Trend):
        values = cls().to_dict()
        hints = get_type_hints(cls)
        objects[cls.__name__] = {'type': 'object', 'properties': {
            key: {'description': MEANINGS.get(key, key.replace('_', ' ').capitalize() + ' as observed from X; missing values are null.'),
                  **json_type(hints[key])} for key in values}, 'required': list(values)}
    return dict(ok=True, results=[objects], schema={'$schema': 'https://json-schema.org/draft/2020-12/schema', '$defs': objects, 'anyOf': [{'$ref': '#/$defs/' + name} for name in objects]}, stop_reason='not_paginable', code=0)
