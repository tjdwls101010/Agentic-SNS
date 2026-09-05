import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2] / '.claude/skills/facebook/scripts'
sys.path.insert(0, str(SCRIPTS))


def test_registry_preserves_queries_flags_and_isolates_variables(tmp_path, monkeypatch):
    monkeypatch.setenv('FACEBOOK_HOME', str(tmp_path))
    from _registry import build_variables, get_query, load_registry
    registry = load_registry()
    assert set(registry['queries']) == {'about', 'timeline', 'newsfeed', 'group', 'search', 'post', 'comments', 'comments_page', 'replies'}
    assert len(registry['relay_provider_flags']) == 46
    assert registry['relay_provider_flags']['__relay_internal__pv__StoriesShouldEnablePhotosensitiveContentWarningrelayprovider'] is False
    assert get_query('newsfeed').doc_id == '27790894430578947'
    spec = get_query('search')
    variables = build_variables(spec, {'count': 3})
    variables['args']['text'] = 'changed'
    assert build_variables(spec)['args']['text'] == ''
    assert variables['count'] == 3
    assert variables['__relay_internal__pv__CometUFICommentAutoTranslationTyperelayprovider'] == 'AUTO_TRANSLATE'
    (tmp_path / 'registry.json').write_text(json.dumps({'queries': {'newsfeed': {'doc_id': '123'}}}))
    assert get_query('newsfeed').doc_id == '123'
    assert get_query('newsfeed').connection_key == 'news_feed'
    assert get_query('timeline').doc_id == '27676223615330440'
