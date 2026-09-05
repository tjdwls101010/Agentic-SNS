import pytest
from twitter_skill._errors import TwitterError
from twitter_skill._registry import Registry


@pytest.mark.parametrize('query', ['price < 100', 'cats | dogs', '…'])
def test_search_passes_user_text_without_template_interpretation(query):
    variables = Registry(override={}).variables('SearchTimeline', rawQuery=query, product='Latest')
    assert variables['rawQuery'] == query


def test_required_template_target_is_not_silently_sent():
    with pytest.raises(TwitterError) as exc:
        Registry(override={}).variables('SearchTimeline', product='Latest')
    assert exc.value.code == 2


def test_missing_features_accumulate_for_refresh(tmp_path, monkeypatch):
    from twitter_skill._registry import learn
    from twitter_skill._blocked import read_state
    monkeypatch.setenv('TWITTER_HOME', str(tmp_path))
    learn(missing_features=['flag_a'])
    learn(missing_features=['flag_b', 'flag_a'])
    assert set(read_state('registry.json')['missing_features']) == {'flag_a', 'flag_b'}
    learn(missing_features=['flag_c'])
    assert set(read_state('registry.json')['missing_features']) == {'flag_a', 'flag_b', 'flag_c'}
