"""A closed operation catalogue; overrides may change queries, never the read surface."""
import copy
import json
from pathlib import Path

from ._blocked import cache_dir
from ._errors import ThreadsError

BUNDLED = Path(__file__).with_name('registry.json')


class Registry:
    def __init__(self):
        try:
            self.operations = json.loads(BUNDLED.read_text())['operations']
            override = cache_dir() / 'registry.json'
            if override.exists():
                for name, spec in json.loads(override.read_text())['operations'].items():
                    if name not in self.operations or not spec.get('verified'):
                        raise ValueError
                    self.operations[name] = self.operations[name] | spec
            for name, spec in self.operations.items():
                if not name.endswith('Query') or not str(spec['doc_id']).isdigit() or not isinstance(spec['flags'], dict):
                    raise ValueError
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise ThreadsError(6, 'The query registry is unreadable.', 'Restore the bundled registry or remove the invalid cache override.',
                               error='envelope_drift') from None

    def get(self, name):
        if name not in self.operations:
            raise ThreadsError(2, 'Only the bundled read-only operations are available.')
        return copy.deepcopy(self.operations[name])

    def variables(self, name, values, spec=None):
        operation = spec or self.get(name)
        result = copy.deepcopy(operation['variables_template'])
        for key, value in values.items():
            result[key] = (result.get(key, {}) | value) if isinstance(value, dict) else value
        def unresolved(value):
            if isinstance(value, dict):
                return any(unresolved(v) for v in value.values())
            if isinstance(value, list):
                return any(unresolved(v) for v in value)
            return isinstance(value, str) and (value.startswith('<') or '|' in value)
        if unresolved(result):
            raise ThreadsError(2, 'Required query variables are missing or unresolved.')
        return result | operation['flags']
