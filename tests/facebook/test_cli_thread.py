"""post and comments through the real cli.py and a fake Aside."""
import json
import re

from conftest import command_of, STATE_OK, known_tab, query_result, run_cli, story

URL = 'https://www.facebook.com/some.page/posts/pfbid0abc'


def comment(identity, replies=None, token=True, text=None, depth=0, parent=None):
    feedback = {'id': 'F' + identity}
    if replies is not None:
        feedback['replies_fields'] = {'total_count': replies}
    if token:
        feedback['expansion_info'] = {'expansion_token': 'tok-' + identity}
    node = {'id': identity, 'depth': depth, 'author': {'id': '7' + identity, 'name': 'Person ' + identity,
                                                       'url': 'https://www.facebook.com/person.' + identity.lower()},
            'body': {'text': text if text is not None else 'comment ' + identity}, 'created_time': 1767225600,
            'feedback': feedback}
    if parent:
        node['comment_direct_parent'] = {'id': parent}
    return node


def comments_body(nodes, has_next=True, cursor='CC1'):
    return json.dumps({'data': {'node': {'__typename': 'Feedback', 'comment_rendering_instance_for_feed_location': {
        'comments': {'edges': [{'node': n} for n in nodes],
                     'page_info': {'has_next_page': has_next, 'end_cursor': cursor if has_next else None}}}}}})


def post_body(text='the whole post text'):
    root = story('P1', text=text)
    root['__typename'] = 'Story'
    return json.dumps({'data': {'node_v2': root}})


def script_post(browser, data_dir, nodes, has_next=True, text='the whole post text'):
    known_tab(browser, data_dir)
    browser.respond('page', {'status': 200, 'url': URL, 'body': '<script>{"storyID":"UzpfSTE6Mg=="}</script>',
                             'explicit': 1, 'resources': 1})
    browser.respond('query', query_result(post_body(text)), name='CometSinglePostDialogContentQuery')
    browser.respond('query', query_result(comments_body(nodes, has_next)), name='CommentListComponentsRootQuery')


def test_post_shows_full_text_parents_and_reply_handles(browser, data_dir):
    long_text = 'x' * 500
    script_post(browser, data_dir, [comment('C1', replies=2), comment('C2', replies=0), comment('C3')], text=long_text)
    code, out, _ = run_cli(browser, 'post', URL)
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'post · sort=all · 4 shown · stopped=limit_reached · requests=3/25'
    assert lines[2] == f'     text[500 of 500 chars shown, complete]: "{long_text}"'
    handles = dict(re.findall(r'author: "https://www.facebook.com/person.(c\d)"   replies (\d+)', out))
    assert set(handles) == {'c1', 'c3'}
    assert lines[-1].endswith(f'cli.py" comments {URL} --sort all --after {int(max(handles.values())) + 1}')
    calls = [c for c in browser.calls() if c['op'] in ('page', 'query')]
    assert [c['op'] for c in calls] == ['page', 'query', 'query']
    assert calls[1]['args']['variables']['storyID'] == 'UzpfSTE6Mg=='
    assert calls[2]['args']['variables']['id'] == 'P1'
    assert calls[2]['args']['variables']['commentsIntentToken'] == 'RANKED_UNFILTERED_INTENT_V1'
    saved = json.loads((data_dir / 'handles' / f'{handles["c1"]}.json').read_text())
    assert saved['context'] == {'command': 'replies', 'target': None, 'account_id': '1000123'}
    assert saved['state'] == {'feedback_id': 'FC1', 'expansion_token': 'tok-C1', 'parent_id': 'C1', 'post_id': 'P1',
                              'post_url': URL, 'depth': 1, 'cursor': None, 'reported': 2, 'shown': 0}


def test_post_without_more_comments_is_exhausted_and_has_no_more(browser, data_dir):
    script_post(browser, data_dir, [comment('C1', replies=0)], has_next=False)
    code, out, _ = run_cli(browser, 'post', URL)
    assert code == 0 and 'stopped=exhausted' in out.splitlines()[0] and 'more:' not in out


def test_comment_sort_names_map_to_facebooks_orders(browser, data_dir):
    script_post(browser, data_dir, [comment('C1', replies=0)], has_next=False)
    run_cli(browser, 'post', URL, '--sort', 'relevant')
    sent = [c for c in browser.calls() if c['op'] == 'query'][-1]['args']['variables']['commentsIntentToken']
    assert sent == 'RANKED_FILTERED_INTENT_V1'


def test_limit_keeps_the_unshown_parents_for_comments(browser, data_dir):
    script_post(browser, data_dir, [comment('C1', replies=0), comment('C2', replies=0), comment('C3', replies=0)])
    code, out, _ = run_cli(browser, 'post', URL, '--limit', '1')
    assert code == 0 and '2 shown' in out.splitlines()[0]
    more = out.splitlines()[-1].split('cli.py" ', 1)[1].split()
    assert more[:4] == ['comments', URL, '--sort', 'all']
    browser.respond('state', STATE_OK)
    browser.respond('query', query_result(comments_body([comment('C4', replies=0)], has_next=False, cursor=None)),
                    name='CommentsListComponentsPaginationQuery')
    code, out, _ = run_cli(browser, *more)
    assert code == 0, out
    assert out.splitlines()[0] == 'comments · sort=all · 2 shown · stopped=limit_reached · requests=0/25'
    assert 'Person C2' in out and 'Person C3' in out
    browser.respond('state', STATE_OK)
    code, out, _ = run_cli(browser, *command_of(out.splitlines()[-1]))
    assert 'Person C4' in out and 'stopped=exhausted' in out
    page = [c for c in browser.calls() if c['op'] == 'query'][-1]['args']['variables']
    assert page['commentsAfterCursor'] == 'CC1' and page['id'] == 'P1'


def test_detail_line_rereads_a_page_whose_comments_were_cut(browser, data_dir):
    script_post(browser, data_dir, [comment('C1', replies=0, text='y' * 300)], has_next=False)
    code, out, _ = run_cli(browser, 'post', URL)
    assert 'text[180 of 300 chars shown, complete]' in out
    assert out.splitlines()[-1].endswith(f'cli.py" post {URL} --sort all --chars 0')
    assert out.splitlines()[-1].startswith('detail: ')


def test_comments_command_finds_the_post_first(browser, data_dir):
    script_post(browser, data_dir, [comment('C1', replies=0)], has_next=False)
    code, out, _ = run_cli(browser, 'comments', URL, '--sort', 'newest')
    assert code == 0 and out.splitlines()[0] == 'comments · sort=newest · 1 shown · stopped=exhausted · requests=3/25'
    assert '[p1]' not in out


def test_a_post_url_is_required(browser, data_dir):
    code, out, _ = run_cli(browser, 'post', 'https://www.facebook.com/some.page')
    assert code == 2 and json.loads(out)['error'] == 'argument' and browser.calls() == []


def test_missing_story_id_is_a_read_failure(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('page', {'status': 200, 'url': URL, 'body': '<html>removed</html>', 'explicit': 1, 'resources': 1})
    code, out, _ = run_cli(browser, 'post', URL)
    result = json.loads(out)
    assert code == 6 and 'private, removed' in result['fix']
