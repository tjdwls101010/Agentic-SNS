"""Field inventory comes from serialized objects, including nested contracts."""
from ._entities import Counts, User
from ._models import Media, Post


def schema():
    samples = {'Post': Post().to_dict(), 'User': User().to_dict(), 'Counts': Counts().to_dict(), 'Media': Media('image', '').to_dict()}
    notes = {'id': 'Stable numeric Threads identity, not the display handle.',
             'url': 'Composable Threads or media URL; media query signatures are sensitive.',
             'created_at': 'UTC ISO timestamp, null if not supplied.',
             'unavailable': 'This object is a tombstone; an outer quote remains readable.',
             'reply_to_id': 'Only an explicit server relationship; never inferred from array position.',
             'following': 'Relationship dialog count; null is unknown, zero is an actual count.'}
    definitions = {}
    for name, sample in samples.items():
        properties = {}
        for key, value in sample.items():
            kind = 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'array' if isinstance(value, list) else 'object' if isinstance(value, dict) else 'string'
            properties[key] = {'description': notes.get(key, key.replace('_', ' ') + '; null means unavailable when nullable.')}
            if value is not None:
                properties[key]['type'] = kind
        definitions[name] = {'type': 'object', 'properties': properties, 'required': list(sample), 'additionalProperties': False}
    return {'ok': True, '$schema': 'https://json-schema.org/draft/2020-12/schema', '$defs': definitions,
            'coverage': 'Post reads expose reported_direct, received_direct, shown_direct, shown_descendants, unshown_received, unavailable and estimated unfetched; not_paginable is not exhaustion.'}
