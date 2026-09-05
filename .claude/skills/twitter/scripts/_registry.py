"""Only IDs, gating and feature switches may be changed by cache data."""
import copy
import json
from pathlib import Path
from ._blocked import read_state, write_state
from ._errors import TwitterError


class Registry:
    def __init__(self, override=None):
        self.data = json.loads(Path(__file__).with_name('registry.json').read_text())
        override = read_state('registry.json') if override is None else override
        for name, changes in override.get('operations', {}).items():
            if name in self.data['operations']:
                self.data['operations'][name].update({k: v for k, v in changes.items() if k in ('query_id', 'gated')})
        self.data['features'].update(override.get('features', {}))
        self.refreshed_at = override.get('refreshed_at')

    def get(self, name):
        if name not in self.data['operations']:
            raise TwitterError(2, 'Unknown read operation.', 'Use the commands shown by --help.')
        return self.data['operations'][name]

    def variables(self, name, **values):
        result = copy.deepcopy(self.get(name)['vars'])
        for key in list(result):
            if key in values:
                result[key] = values[key]
            if result[key] is None:
                del result[key]
        def unresolved(value):
            return isinstance(value, str) and ('<' in value or '|' in value or value == '…') or isinstance(value, list) and any(unresolved(v) for v in value)
        if any(unresolved(v) for k, v in result.items() if k not in values):
            raise TwitterError(2, f'Missing variables for {name}.', 'Supply the target and supported command options.')
        return result


def learn(name=None, **changes):
    override = read_state('registry.json')
    if name:
        override.setdefault('operations', {}).setdefault(name, {}).update(changes)
    else:
        if changes.get('missing_features'):
            changes['missing_features'] = sorted(set(override.get('missing_features', [])) | set(changes['missing_features']))
        override.update(changes)
    write_state('registry.json', override)
