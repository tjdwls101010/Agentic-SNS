"""What may leave the process: the read-only gate, assembled requests, the one hop that names a domain address's blog,
and the route table fetch.js holds being the Python ledger's (35 rows)."""
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl

import pytest

from sns.errors import SnsError
from sns.naver_blog import web
from tests.sns.naver_blog.scene import KIND_OF, fixture

REQUESTS = fixture('requests.json')
FETCH_JS = Path(web.__file__).with_name('fetch.js')


@pytest.mark.parametrize('case', REQUESTS['allowlist']['cases'], ids=lambda c: c['host'] + c['path'])
def test_gate(case):
    assert web.allowed(case['host'], case['path'], case.get('query')) is case['allowed']


@pytest.mark.parametrize('case', REQUESTS['builds']['cases'], ids=lambda c: c['name'])
def test_build(case):
    if case.get('refused'):
        with pytest.raises(SnsError) as caught:
            web.build_request(case['op'], page=case.get('page'), **case['ids'])
        assert caught.value.kind == 'failed' and caught.value.reason == 'drift'
        return
    host, path, query = web.build_request(case['op'], page=case.get('page'), **case['ids'])
    values = {key: str(value) for key, value in query.items()}
    assert {k: values.get(k) for k in case['query_has']} == case['query_has']
    assert not [k for k in case.get('query_lacks', []) if k in values]
    if 'path' in case:
        assert path == case['path']
    assert web.allowed(host, path, web.encoded(query))


@pytest.mark.parametrize('case', REQUESTS['redirects']['cases'], ids=lambda c: f"{c['status']}")
def test_domain_hop(case):
    response = {'status': case['status'], 'url': 'https://blog.naver.com/mydomain', 'location': case.get('location'),
                'body': case.get('body', '')}
    if 'outcome' in case:
        with pytest.raises(SnsError) as caught:
            web.frame_blog_id(response)
        assert (caught.value.kind, caught.value.reason) == (KIND_OF[case['outcome']['code']], case['outcome']['reason'])
    else:
        assert web.frame_blog_id(response) == case['canonical']


def test_the_ledger_has_35_rows_and_no_write_api():
    assert len(web.OPERATIONS) == 35 and sum(len(patterns) for patterns in web.ROUTES.values()) == 35
    assert set(web.ROUTES) == {'m.blog.naver.com', 'apis.naver.com', 'section.blog.naver.com', 'blog.naver.com',
                               'naver.me', '*.pstatic.net'}


def test_the_route_table_in_fetch_js_is_the_ledgers():
    text = FETCH_JS.read_text(encoding='utf-8')
    assert text.startswith('// sns-snippet: naver_blog.fetch\n')
    table = re.search(r'// routes:begin[^\n]*\n\s*const ROUTES = (\{.*?\});\n\s*// routes:end', text, re.S)[1]
    assert json.loads(table) == web.ROUTES


def test_every_request_the_ledger_builds_passes_the_gate():
    for row in web.OPERATIONS.values():
        if row.envelope in ('hop', 'image'):
            continue
        ids = {key: 'sample_blog' if key not in ('logNo', 'blogNo', 'categoryNo', 'groupId') else '1'
               for key in re.findall(r'\{(\w+)\}', row.path) + list(row.required)}
        host, path, query = web.build_request(row.op, page=1 if row.pagination else None, **ids)
        assert web.allowed(host, path, web.encoded(query)), row.op
        assert dict(parse_qsl(web.encoded(query))) == {k: str(v) for k, v in query.items()}
