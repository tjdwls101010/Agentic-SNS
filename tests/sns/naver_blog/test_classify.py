"""Response classification: the step order is the contract (a transport failure beats a block, a block a login wall, a
login wall a missing target, a missing target a contract error; a restriction is read only from a valid answer)."""
import pytest

from sns.errors import SnsError
from sns.naver_blog import web
from tests.sns.naver_blog.scene import KIND_OF, fixture

CASES = fixture('classify.json')['cases']
REASON = {'query_restricted': 'restricted'}  # the fixture predates the core's word for a restricted query


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_classify(case):
    response = {'location': None, **case['response']}
    want = case['outcome']
    if want.get('outcome') == 'ok':
        web.classify(case['op'], response, case.get('ids', {}))
        return
    with pytest.raises(SnsError) as caught:
        web.classify(case['op'], response, case.get('ids', {}))
    error = caught.value
    assert error.kind == KIND_OF[want['code']]
    if 'reason' in want:
        assert error.reason == REASON.get(want['reason'], want['reason'])
    if 'kept' in want:
        assert len(error.payload['result'].get('list') or error.payload['result'].get('items') or []) == want['kept']


def test_a_429_carries_the_reason_the_client_turns_into_a_hold():
    with pytest.raises(SnsError) as caught:
        web.classify('search_posts', {'status': 429, 'url': 'https://m.blog.naver.com/api/search/v1/post', 'body': '',
                                      'location': None})
    assert (caught.value.kind, caught.value.reason) == ('blocked', 'rate_limit')
