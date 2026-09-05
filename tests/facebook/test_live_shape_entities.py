"""Search wrappers observed live, reduced to synthetic public contract inputs."""
import json
from datetime import datetime, timezone

from _entity import build_entities


def test_entity_in_edge_rendering_strategy_is_a_search_result():
    edge = {'node': {'__typename': 'SearchResult', 'id': 'opaque-result'},
            'rendering_strategy': {'view_model': {
                'profile': {'__typename': 'Group', 'id': '100', 'name': 'Synthetic group',
                            'url': 'https://www.facebook.com/groups/100/'},
                'ctas': {'primary': [{'profile': {'__typename': 'User', 'id': '200',
                                                'name': 'Not a result', 'url': 'https://www.facebook.com/200'}}]}}}}
    body = json.dumps({'data': {'serpResponse': {'results': {'edges': [edge]}}}}).encode()
    result = build_entities([body], search_type='groups', captured_at=datetime.now(timezone.utc))
    assert [e.id for e in result] == ['100']
