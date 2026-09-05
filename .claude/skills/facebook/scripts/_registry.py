"""Bundled query snapshots with per-query local overrides."""
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from _blocked import cache_dir
from _errors import FacebookError


@dataclass(frozen=True)
class QuerySpec:
    name: str
    doc_id: str
    connection_key: str | None
    cursor_var: str | None
    referer: str
    variables: dict = field(default_factory=dict)
    expected_key: str | None = None
    expected_kind: str = 'connection'
    relay_provider_flags: dict = field(default_factory=dict, repr=False)


def load_registry():
    try:
        bundled = json.loads(Path(__file__).with_name('registry.json').read_text())
        path = cache_dir() / 'registry.json'
        override = json.loads(path.read_text()) if path.exists() else {}
        for key, patch in override.get('queries', {}).items():
            if key not in bundled['queries'] or not isinstance(patch, dict):
                raise ValueError
            spec = bundled['queries'][key]
            spec.update({k: v for k, v in patch.items() if k != 'variables'})
            spec['variables'].update(patch.get('variables', {}))
        bundled['relay_provider_flags'].update(override.get('relay_provider_flags', {}))
        for spec in bundled['queries'].values():
            if not isinstance(spec['doc_id'], str) or not spec['doc_id'].isdigit():
                raise ValueError
            QuerySpec(**spec)
        return bundled
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise FacebookError(6, 'Query registry is invalid.', 'Run refresh or remove the local registry override.') from None


def get_query(key):
    registry = load_registry()
    if key not in registry['queries']:
        raise FacebookError(2, 'Unknown query key.', 'Use a supported read command.')
    return QuerySpec(**registry['queries'][key], relay_provider_flags=registry['relay_provider_flags'])


def build_variables(spec, overrides=None):
    variables = copy.deepcopy(spec.variables)
    variables.update(copy.deepcopy(spec.relay_provider_flags or load_registry()['relay_provider_flags']))
    if overrides:
        variables.update(copy.deepcopy(overrides))
    return variables


ABOUT_SECTION_ID = '2327158227'
FEED_SORT_TOKENS = {'top': {'orderby': ['TOP_STORIES'], 'feedStyle': 'DEFAULT'},
                    'recent': {'orderby': ['MOST_RECENT'], 'feedStyle': 'MOST_RECENT_FEED_DEFAULT'}}
GROUP_SORT_TOKENS = {'top': 'TOP_POSTS', 'recent': 'CHRONOLOGICAL', 'activity': 'RECENT_ACTIVITY'}
COMMENT_SORT_TOKENS = {'top': 'RANKED_UNFILTERED_INTENT_V1', 'recent': 'REVERSE_CHRONOLOGICAL_UNFILTERED_INTENT_V1'}
