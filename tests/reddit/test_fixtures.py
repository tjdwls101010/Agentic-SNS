"""Offline fixture-tool CLI contracts and production-parser round trips."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from reddit_skill._listing import walk_listing_nodes, parse_thing
from reddit_skill._thread import create_state
from reddit_skill._entities import build_rule

ROOT = Path(__file__).parent
TOOLS = ROOT / 'tools'
FIXTURES = ROOT / 'fixtures'


def run_tool(name, *args):
    return subprocess.run([sys.executable, str(TOOLS / name), *map(str, args)], capture_output=True, text=True)


def listing(children, **fields):
    return {'kind': 'Listing', 'data': {'children': children, 'after': None, **fields}}


def test_derivation_preserves_post_pair_anchors_and_removes_auth(tmp_path):
    post = {'kind': 't3', 'data': {'id': 'realpost', 'name': 't3_realpost', 'title': 'Private title',
            'author': 'OriginalPerson', 'subreddit': 'OriginalCommunity'}}
    comment = {'kind': 't1', 'data': {'id': 'realcomment', 'name': 't1_realcomment', 'parent_id': 't3_realpost',
               'link_id': 't3_realpost', 'author': 'OriginalPerson', 'body': 'Private reply', 'replies': '',
               'permalink': '/r/OriginalCommunity/comments/realpost/private_slug/realcomment/'}}
    pointer = {'kind': 'more', 'data': {'id': 'unread', 'name': 't1_unread', 'parent_id': 't1_realcomment',
               'children': ['unread'], 'count': 1}}
    source = [listing([post], modhash='secret-modhash'), listing([comment, pointer],
              cookie='private-cookie', headers={'Authorization': 'Bearer private-token'})]
    capture, output = tmp_path / 'input.ndjson', tmp_path / 'output.ndjson'
    capture.write_text(json.dumps(source) + '\n')
    result = run_tool('derive_fixture.py', capture, output)
    assert result.returncode == 0, result.stderr
    derived = json.loads(output.read_text())
    assert isinstance(derived, list) and len(derived) == 2
    nodes = list(walk_listing_nodes(derived))
    post_data, comment_data, more_data = [node['data'] for node in nodes]
    assert comment_data['parent_id'] == comment_data['link_id'] == post_data['name']
    assert more_data['parent_id'] == comment_data['name']
    assert more_data['name'] == 't1_' + more_data['children'][0]
    assert comment_data['replies'] == ''
    state = create_state(derived, {'post_id': post_data['id'], 'comment_id': comment_data['id']})
    assert comment_data['name'] in state['nodes']
    assert comment_data['id'] in comment_data['permalink']
    assert post_data['id'] in comment_data['permalink']
    for private in ('Original', 'Private', 'realpost', 'realcomment', 'modhash', 'cookie', 'Authorization', 'private-token'):
        assert private not in output.read_text()
    assert run_tool('check_fixtures_pii.py', output).returncode == 0
    assert run_tool('derive_fixture.py', capture, output).returncode == 2
    assert json.loads(capture.read_text()) == source


@pytest.mark.parametrize('artifact', [
    {'reddit_session': 'fake'}, {'modhash': ''}, {'cookie': 'fake'}, {'Authorization': 'fake'},
    {'email': 'someone@example.test'}, {'phone': '+82 10 1234 5678'},
    {'url': 'https://example.test/a?signature=short'}, {'signature': 'short'},
    {'headers': ['Cookie: reddit_session=fake']}, {'body': 'Authorization: Bearer fake'},
])
def test_scanner_rejects_secret_and_contact_shapes_without_echoing_values(tmp_path, artifact):
    path = tmp_path / 'bad.ndjson'
    path.write_text(json.dumps(artifact) + '\n')
    result = run_tool('check_fixtures_pii.py', path)
    assert result.returncode == 1
    assert 'someone@example.test' not in result.stderr
    assert '+82 10 1234 5678' not in result.stderr


def test_scanner_states_manual_free_text_review_limitation(tmp_path):
    path = tmp_path / 'synthetic.ndjson'
    path.write_text('{"body":"Synthetic text only"}\n')
    result = run_tool('check_fixtures_pii.py', path)
    assert result.returncode == 0
    assert 'free-text' in result.stdout and 'human review' in result.stdout


def test_derivation_keeps_t2_username_separate_from_ids_across_lines(tmp_path):
    source = [listing([
        {'kind': 't2', 'data': {'id': 'same', 'name': 'OriginalUser'}},
        {'kind': 't3', 'data': {'id': 'same', 'name': 't3_same', 'author': 'OriginalUser'}},
        {'kind': 't5', 'data': {'id': 'community', 'name': 't5_community', 'display_name': 'PrivateSub'}}], after='t3_same'),
        {'kind': 't1', 'data': {'id': 'reply', 'name': 't1_reply', 'link_id': 't3_same',
         'parent_id': 't3_same', 'author': 'OriginalUser', 'replies': ''}}]
    capture, output = tmp_path / 'input', tmp_path / 'output'
    capture.write_text('\n'.join(map(json.dumps, source)))
    result = run_tool('derive_fixture.py', capture, output)
    assert result.returncode == 0, result.stderr
    first, second = map(json.loads, output.read_text().splitlines())
    user, post, sub = [parse_thing(node) for node in walk_listing_nodes(first)]
    comment = parse_thing(second)
    assert user['kind'] == 'user' and sub['kind'] == 'subreddit'
    assert user['name'] == post['author'] == comment['author']
    assert not user['name'].startswith('t2_')
    assert user['fullname'][3:] == post['fullname'][3:]
    assert first['data']['after'] == post['fullname'] == comment['parent']
    assert int(user['fullname'][3:], 36) > 0


def test_derivation_is_offline_and_does_not_echo_malformed_source(tmp_path):
    capture = tmp_path / 'bad'
    capture.write_text('private-user@example.test invalid json')
    result = run_tool('derive_fixture.py', capture, tmp_path / 'out')
    assert result.returncode == 2
    assert 'private-user' not in result.stderr
    assert not (tmp_path / 'out').exists()
    assert run_tool('derive_fixture.py', 'https://example.test/capture', tmp_path / 'out').returncode == 2


@pytest.mark.parametrize('name', ['listing', 'post_pair', 'morechildren', 'rules', 'duplicates'])
def test_synthetic_fixtures_load_through_production_parsers(name):
    from reddit_skill._transport import classify
    from reddit_skill._tree import walk_things
    path = FIXTURES / f'{name}.ndjson'
    payloads = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(payloads) == 1
    payload = payloads[0]
    classified = classify({'status': 200, 'url': 'https://www.reddit.com/synthetic.json', 'body': json.dumps(payload)}, name)
    assert classified == payload
    if name == 'rules':
        assert build_rule(payload['rules'][0]).to_dict()['name'] == 'Synthetic civility'
    elif name == 'post_pair':
        state = create_state(payload, {'post_id': 'syn1', 'comment_id': 'syn2'})
        assert state['nodes']['t1_syn2']['parent'] == 't3_syn1'
        assert len(state['pending_more']) == 1
    elif name == 'morechildren':
        things = list(walk_things(payload))
        assert [thing['kind'] for thing, _ in things] == ['t1', 'more']
        assert parse_thing(things[0][0])['parent'] == 't1_syn2'
    else:
        records = [parse_thing(node) for node in walk_listing_nodes(payload)]
        assert len(records) == (4 if name == 'listing' else 2)
        if name == 'listing':
            assert [record['kind'] for record in records] == ['post', 'comment', 'user', 'subreddit']


def test_committed_synthetic_fixture_directory_passes_pii_gate():
    result = run_tool('check_fixtures_pii.py')
    assert result.returncode == 0, result.stderr
    assert '5 file(s)' in result.stdout
