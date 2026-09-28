"""What rotates: each declared operation's current name, doc_id and flags, bundled and overridden by refresh.

The bundled registry.json and the cache override are both {"version": 2, "operations": {id: {name, doc_id, flags,
captured_at}}}. An override written before the catalogue (no version, keyed by Meta name, whole specs) is read through
the declarations' legacy names: its verified entries are kept, the retired post-page entries dropped, and a name no
declaration knows makes the override unreadable. The next save writes version 2.
"""
import copy
import json
from pathlib import Path

from ..errors import ThreadsError
from ..guard.state import account_lock, cache_dir, write_state
from .operations import OPERATIONS, REQUIRED, SSR_ONLY, by_legacy_name

BUNDLED = Path(__file__).with_name('registry.json')
FIELDS = ('name', 'doc_id', 'flags', 'captured_at')


class Unknown(ValueError):
    """The override names an operation this skill does not declare."""


def override_entries(data, bundled):
    """The override's entries by operation id, whichever version wrote it; an old entry fills what it leaves out
    from the bundled one."""
    if not isinstance(data, dict) or not isinstance(data.get('operations'), dict):
        raise ValueError
    if data.get('version') == 2:
        if any(key not in OPERATIONS or OPERATIONS[key].pagination == SSR_ONLY for key in data['operations']):
            raise Unknown
        return {key: {field: entry[field] for field in FIELDS} for key, entry in data['operations'].items()}
    if 'version' in data:
        raise ValueError
    entries = {}
    for name, spec in data['operations'].items():
        operation = by_legacy_name(name)
        if operation is None:
            raise Unknown
        if operation.pagination != SSR_ONLY and spec.get('verified'):
            base = bundled[operation.id]
            entries[operation.id] = {'name': name, **{field: spec.get(field, base[field]) for field in FIELDS[1:]}}
    return entries


def valid(entry):
    return (isinstance(entry.get('name'), str) and entry['name'].endswith('Query')
            and str(entry.get('doc_id')).isdigit() and isinstance(entry.get('flags'), dict))


class Registry:
    def __init__(self):
        override = cache_dir() / 'registry.json'
        try:
            self.operations = json.loads(BUNDLED.read_text())['operations']
            if override.exists():
                self.operations.update(override_entries(json.loads(override.read_text()), self.operations))
            if set(self.operations) - OPERATIONS.keys() or not all(map(valid, self.operations.values())):
                raise ValueError
        except Unknown:
            raise ThreadsError(6, 'The query registry override names an operation this skill does not know.',
                               f'Remove {override}; it holds entries this skill no longer knows.',
                               error='registry') from None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise ThreadsError(6, 'The query registry is unreadable.', 'Restore the bundled registry or remove the invalid cache override.',
                               error='registry') from None

    def entry(self, operation):
        if operation not in self.operations:
            raise ThreadsError(2, 'Only the bundled read-only operations are available.')
        return copy.deepcopy(self.operations[operation])

    def name(self, operation):
        return self.operations[operation]['name']

    def admitted(self):
        """The names a query may be sent under: every operation's current name."""
        return [entry['name'] for entry in self.operations.values()]

    def variables(self, operation, values, entry=None):
        selected = entry or self.entry(operation)
        result = copy.deepcopy(OPERATIONS[operation].variables)
        for key, value in values.items():
            result[key] = (result.get(key, {}) | value) if isinstance(value, dict) else value

        def unresolved(value):
            if isinstance(value, dict):
                return any(unresolved(v) for v in value.values())
            if isinstance(value, list):
                return any(unresolved(v) for v in value)
            return value is REQUIRED
        if unresolved(result):
            raise ThreadsError(2, 'Required query variables are missing or unresolved.')
        return result | selected['flags']


def save(updates):
    """Merge verified entries into the cache override and write it as version 2."""
    with account_lock():
        path = cache_dir() / 'registry.json'
        try:
            bundled = json.loads(BUNDLED.read_text())['operations']
            saved = override_entries(json.loads(path.read_text()), bundled) if path.exists() else {}
            saved.update(updates)
            write_state('registry.json', {'version': 2, 'operations': saved})
        except (ValueError, KeyError, AttributeError, TypeError, OSError):
            raise ThreadsError(6, 'Registry override cannot be merged; previous file preserved.') from None
