"""Field inventory comes from serialized objects, including nested contracts."""
from ._entities import Counts, User
from ._models import Media, Post
from ._thread import Completeness
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints


def field_type(annotation):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        return {'anyOf': [field_type(arg) for arg in args]}
    if annotation in (Post, User, Counts, Media, Completeness):
        return {'$ref': '#/$defs/' + annotation.__name__}
    if origin is list or annotation is list:
        return {'type': 'array', 'items': field_type(args[0]) if args else {}}
    if origin is dict or annotation is dict:
        return {'type': 'object'}
    return {'type': {str: 'string', int: 'integer', bool: 'boolean', type(None): 'null'}[annotation]}


def schema():
    classes = {'Post': Post, 'User': User, 'Counts': Counts, 'Media': Media, 'Completeness': Completeness}
    samples = {name: cls().to_dict() if name != 'Media' else Media('image', '').to_dict() for name, cls in classes.items()}
    notes = {'id': 'Stable numeric Threads identity, not the display handle.',
             'url': 'Composable Threads or media URL; media query signatures are sensitive.',
             'created_at': 'UTC ISO timestamp, null if not supplied.',
             'unavailable': 'This object is a tombstone; an outer quote remains readable.',
             'reply_to_id': 'Only an explicit server relationship; never inferred from array position.',
             'following': 'Relationship dialog count; null is unknown, zero is an actual count.',
             'reported_direct': 'Threads server count of direct replies; null if unknown.',
             'received_direct': 'Readable direct reply groups received in SSR, before display limits.',
             'shown_direct': 'Readable direct replies displayed in this result.',
             'shown_descendants': 'Received descendant/continuation records displayed under the selected direct groups.',
             'unshown_received': 'Received direct replies omitted by the display limit; not unfetched replies.',
             ('Completeness', 'unavailable'): 'Unavailable direct reply groups; separate from readable received_direct.',
             'unfetched': 'Approximate max(reported_direct - received_direct - unavailable, 0); null when counts conflict or are unknown.',
             'unfetched_is_estimate': 'True only when unfetched is a numerical estimate, never proof of exact coverage.'}
    definitions = {}
    for name, sample in samples.items():
        properties = {}
        annotations = get_type_hints(classes[name])
        for key, value in sample.items():
            properties[key] = field_type(annotations[key]) | {'description': notes.get((name, key), notes.get(key, key.replace('_', ' ') + '; null means unavailable when nullable.'))}
        definitions[name] = {'type': 'object', 'properties': properties, 'required': list(sample), 'additionalProperties': False}
    definitions['ReadResult'] = {'type': 'object', 'required': ['ok', 'results', 'stop_reason', 'next', 'budget', 'fetched_bytes'],
        'properties': {'ok': {'type': 'boolean'}, 'results': {'type': 'array', 'items': {'anyOf': [{'$ref': '#/$defs/Post'}, {'$ref': '#/$defs/User'}]}},
            'stop_reason': {'enum': ['limit_reached', 'exhausted', 'window_reached', 'budget', 'blocked', 'query_failure', 'not_paginable', 'server_capped'],
                            'description': 'not_paginable and server_capped describe limited coverage, not exhaustion.'},
            'next': {'type': ['string', 'null'], 'description': 'Executable continuation command, including --out for file collection.'},
            'budget': {'type': 'object', 'description': 'Local used/limit/remaining and window_used/window_limit, not a server allowance.'},
            'fetched_bytes': {'type': 'integer'}, 'completeness': {'$ref': '#/$defs/Completeness'},
            'context': {'type': 'object', 'properties': {'sort': {'enum': ['top', 'recent'], 'description': 'Post reply or post search ordering; recent reply batches may overlap top.'}}}}}
    return {'ok': True, '$schema': 'https://json-schema.org/draft/2020-12/schema', '$defs': definitions,
            'coverage': 'Post reads expose reported_direct, received_direct, shown_direct, shown_descendants, unshown_received, unavailable and estimated unfetched; not_paginable is not exhaustion.'}
