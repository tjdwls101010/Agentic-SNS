import json
from argparse import Namespace

from .test_cli import run_cli
from .test_thread import thread_html
from threads_skill._session import Session
from threads_skill._target import parse_target
from threads_skill._thread import read_thread


def test_schema_covers_post_page_roles_and_relationships():
    html = thread_html()
    result = read_thread(html, Session.from_html(html), Namespace(
        target=parse_target('/@fixture_user/post/FIX_2', 'post'), limit=2, sort='top', out=None))
    schema = json.loads(run_cli('schema', '--json').stdout)['$defs']['Post']
    for post in result['results']:
        assert set(post) <= schema['properties'].keys()
    assert schema['properties']['reply_to_id']['anyOf'] == [{'type': 'string'}, {'type': 'null'}]
