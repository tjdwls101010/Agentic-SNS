"""post and comments through the real cli.py and a fake Aside."""
import json
import re

from tests.sns.facebook.scenes import known_tab, look, page_result, queries, query_result, rerun, run, story

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


def script_post(browser, nodes, has_next=True, text='the whole post text'):
    known_tab(browser)
    browser.respond('facebook.page', page_result(URL, '<script>{"storyID":"UzpfSTE6Mg=="}</script>'))
    browser.respond('facebook.query', query_result(post_body(text)), name='CometSinglePostDialogContentQuery')
    browser.respond('facebook.query', query_result(comments_body(nodes, has_next)),
                    name='CommentListComponentsRootQuery')


def test_post_shows_full_text_parents_and_reply_handles(browser):
    long_text = 'x' * 500
    script_post(browser, [comment('C1', replies=2), comment('C2', replies=0), comment('C3')], text=long_text)
    code, out, _ = run(browser, 'post', URL)
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'facebook post · sort=all · 4 shown · stopped=limit_reached · requests=3'
    assert lines[2] == f'     text[500 of 500 chars shown]: "{long_text}"'
    handles = dict(re.findall(r'author: "https://www.facebook.com/person.(c\d)"   replies (\d+)', out))
    assert set(handles) == {'c1', 'c3'}
    assert re.fullmatch(rf'more: uv run ".*cli\.py" facebook comments {re.escape(URL)} --sort all --after \d+', lines[-1])
    calls = [c for c in browser.calls() if c['op'] in ('facebook.page', 'facebook.query')]
    assert [c['op'] for c in calls] == ['facebook.page', 'facebook.query', 'facebook.query']
    assert calls[1]['args']['variables']['storyID'] == 'UzpfSTE6Mg=='
    assert calls[2]['args']['variables']['id'] == 'P1'
    assert calls[2]['args']['variables']['commentsIntentToken'] == 'RANKED_UNFILTERED_INTENT_V1'


def test_post_without_more_comments_is_exhausted_and_has_no_more(browser):
    script_post(browser, [comment('C1', replies=0)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    assert code == 0 and 'stopped=exhausted' in out.splitlines()[0] and 'more:' not in out


def test_comment_sort_names_map_to_facebooks_orders(browser):
    script_post(browser, [comment('C1', replies=0)], has_next=False)
    run(browser, 'post', URL, '--sort', 'relevant')
    assert queries(browser)[-1]['args']['variables']['commentsIntentToken'] == 'RANKED_FILTERED_INTENT_V1'


def test_limit_keeps_the_unshown_parents_for_comments(browser):
    script_post(browser, [comment('C1', replies=0), comment('C2', replies=0), comment('C3', replies=0)])
    code, out, _ = run(browser, 'post', URL, '--limit', '1')
    assert code == 0 and '2 shown' in out.splitlines()[0]
    more = out.splitlines()[-1]
    assert re.search(rf'facebook comments {re.escape(URL)} --sort all --after \d+$', more)
    look(browser)
    browser.respond('facebook.query', query_result(comments_body([comment('C4', replies=0)], has_next=False, cursor=None)),
                    name='CommentsListComponentsPaginationQuery')
    code, out, _ = rerun(browser, more)
    assert code == 0, out
    assert out.splitlines()[0] == 'facebook comments · sort=all · 2 shown · stopped=limit_reached · requests=0'
    assert 'Person C2' in out and 'Person C3' in out
    look(browser)
    code, out, _ = rerun(browser, out.splitlines()[-1])
    assert 'Person C4' in out and 'stopped=exhausted' in out
    page = queries(browser)[-1]['args']['variables']
    assert page['commentsAfterCursor'] == 'CC1' and page['id'] == 'P1'


def test_a_cut_comment_is_read_in_full_by_chars_0(browser):
    script_post(browser, [comment('C1', replies=0, text='y' * 300)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    assert 'text[180 of 300 chars shown]' in out
    look(browser)
    browser.respond('facebook.page', page_result(URL, '<script>{"storyID":"UzpfSTE6Mg=="}</script>'))
    browser.respond('facebook.query', query_result(post_body()), name='CometSinglePostDialogContentQuery')
    browser.respond('facebook.query', query_result(comments_body([comment('C1', replies=0, text='y' * 300)], False)),
                    name='CommentListComponentsRootQuery')
    code, out, _ = run(browser, 'post', URL, '--chars', '0')
    assert 'text[300 of 300 chars shown]' in out


def test_comments_command_finds_the_post_first(browser):
    script_post(browser, [comment('C1', replies=0)], has_next=False)
    code, out, _ = run(browser, 'comments', URL, '--sort', 'newest')
    assert code == 0
    assert out.splitlines()[0] == 'facebook comments · sort=newest · 1 shown · stopped=exhausted · requests=3'
    assert '[p1]' not in out


def test_comments_without_a_limit_read_one_page(browser):
    script_post(browser, [comment('C1', replies=0)], has_next=True)
    code, out, _ = run(browser, 'comments', URL)
    assert code == 0 and len(queries(browser)) == 2 and out.splitlines()[-1].startswith('more: ')


def test_a_post_url_is_required(browser):
    code, out, _ = run(browser, 'post', 'https://www.facebook.com/some.page')
    assert code == 2 and json.loads(out)['error'] == 'argument' and browser.calls() == []


def test_a_share_link_is_named_as_not_read_and_sends_nothing(browser):
    code, out, _ = run(browser, 'post', 'https://www.facebook.com/share/p/1AbCdEf/')
    result = json.loads(out)
    assert code == 2 and 'permalink' in result['message'] and browser.calls() == []


def test_missing_story_id_is_a_read_failure(browser):
    known_tab(browser)
    browser.respond('facebook.page', page_result(URL, '<html>removed</html>'))
    code, out, _ = run(browser, 'post', URL)
    result = json.loads(out)
    assert code == 6 and 'private, removed' in result['fix']


def test_another_platforms_link_names_its_command(browser):
    code, out, _ = run(browser, 'post', 'https://x.com/jack/status/20')
    result = json.loads(out)
    assert code == 2 and 'x post' in result['fix'] and browser.calls() == []
