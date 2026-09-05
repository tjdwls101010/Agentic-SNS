import pytest

from threads_skill._registry import Registry
from threads_skill._errors import ThreadsError


def test_registry_templates_never_leak_placeholders_or_flags_across_operations():
    registry = Registry()
    feed = registry.variables('BarcelonaFeedDirectQuery', {'variant': 'following',
        'data': {'pagination_source': 'text_post_feed_following', 'reason': 'pagination'}})
    assert feed['variant'] == 'following'
    assert feed['data']['reason'] == 'pagination'
    profile = registry.variables('BarcelonaProfilePageDirectQuery', {'userID': '42'})
    assert profile['userID'] == '42'
    assert '__relay_internal__pv__BarcelonaHasDearAlgoConsumptionrelayprovider' not in profile
    with pytest.raises(ThreadsError):
        registry.variables('BarcelonaProfilePageDirectQuery', {})
    with pytest.raises(ThreadsError):
        registry.get('SomeWriteMutation')
