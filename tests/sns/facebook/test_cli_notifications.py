"""notifications through the real cli.py and a fake Aside: the record lines, what layout rows do, the seen mapping, the
continuation with the pagination query, and the one failure that must not move the tab (a refused stored query id is
never relearned by opening the notifications screen, which is what makes the app mark notifications seen)."""
import json
import re
from datetime import datetime

import pytest

from sns.facebook import web
from tests.sns.facebook.scenes import known_tab, look, queries, query_result, rerun, run, sent

FIRST, LATER = 'CometNotificationsRootQuery', 'CometNotificationsListPaginationQuery'
REJECTED = json.dumps({'errors': [{'message': 'PersistedQueryNotFound', 'code': 1675002}]})
TRACKING = 'TRACKING-SENTINEL-DO-NOT-OUTPUT'


def notif(identity, text='Sample Person replied to your comment', seen='SEEN_AND_READ', created='2026-09-12T03:00:00Z',
          kind='feed_comment_reply'):
    """A NOTIFICATION row the way the client's list query returns it (synthetic values)."""
    epoch = int(datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp())
    return {'node': {'row_type': 'NOTIFICATION', 'notif': {
        'id': 'gid-' + identity, 'notif_id': identity, 'seen_state': seen, 'creation_time': {'timestamp': epoch},
        'notif_type': kind, 'body': {'text': text}, 'url': f'https://www.facebook.com/example/posts/{identity}',
        'notif_image': {'uri': 'https://example.invalid/a.jpg'}, 'icon_data': {'name': 'x'}, 'tracking': TRACKING}}}


def layout(row_type):
    return {'node': {'row_type': row_type}}


def body(rows, has_next=True, cursor='NC1', unseen=0):
    return json.dumps({'data': {'viewer': {'notifications_unseen_count': unseen, 'notifications_page': {
        'edges': rows, 'page_info': {'has_next_page': has_next, 'end_cursor': cursor if has_next else None}}}}})


def page(rows, has_next=True, cursor='NC1', **kwargs):
    return query_result(body(rows, has_next, cursor), **kwargs)


def routes(browser):
    return [c for c in browser.calls() if c['op'] == 'facebook.route']


def test_one_page_of_notifications_skips_layout_rows_and_says_how_to_go_on(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([layout('BUCKET_HEADER'), notif('N1'), notif('N2', seen='UNSEEN',
                                            text='Sample Person tagged you', kind='tagged'),
                                            layout('SEE_PREVIOUS_BUTTON')]))
    code, out, _ = run(browser, 'notifications')
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'facebook notifications · 2 shown · stopped=limit_reached · requests=1'
    assert lines[1] == '[n1] 2026-09-12T03:00+00:00 · feed_comment_reply · read'
    assert lines[2] == '     text[37 of 37 chars shown]: "Sample Person replied to your comment"'
    assert lines[3] == '     url: "https://www.facebook.com/example/posts/N1"'
    assert lines[4] == '[n2] 2026-09-12T03:00+00:00 · tagged · unseen'
    assert re.fullmatch(r'more: uv run ".*cli\.py" facebook notifications --after \d+', lines[-1])
    assert TRACKING not in out
    first = queries(browser)[0]['args']
    assert first['name'] == FIRST and first['variables'] == {'count': 15, 'environment': 'MAIN_SURFACE',
                                                             'filter_tokens': [], 'scale': 2}


def test_more_continues_with_the_pagination_query_from_the_end_cursor(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([notif('N1')], cursor='NC1'))
    code, out, _ = run(browser, 'notifications')
    look(browser).respond('facebook.query', page([notif('N2')], has_next=False))
    code, out, _ = rerun(browser, out.splitlines()[-1])
    assert code == 0 and '[n1]' in out and sent(browser) == [FIRST, LATER]
    assert queries(browser)[1]['args']['variables'] == {
        'count': 15, 'cursor': 'NC1', 'environment': 'MAIN_SURFACE', 'filter_tokens': [], 'notif_cache_ids': [],
        'notif_query_flags': [], 'scale': 2}


def test_a_limit_reads_on_across_pages(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([notif('N1'), notif('N2')], cursor='NC1'))
    browser.respond('facebook.query', page([notif('N3'), notif('N4')], cursor='NC2'))
    code, out, _ = run(browser, 'notifications', '--limit', '3', '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == ['N1', 'N2', 'N3']
    assert sent(browser) == [FIRST, LATER] and result['request_count'] == 2


def test_records_carry_the_shared_head_the_seen_words_and_nothing_opaque(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([notif('N1', seen='UNSEEN'), notif('N2', seen='SEEN_BUT_UNREAD'),
                                            notif('N3', seen='SEEN_AND_READ'), notif('N4', seen='SOMETHING_NEW')],
                                           has_next=False))
    code, out, _ = run(browser, 'notifications', '--json')
    result = json.loads(out)
    assert code == 0 and [r['seen'] for r in result['results']] == ['unseen', 'seen', 'read', None]
    first = result['results'][0]
    assert list(first)[:4] == ['kind', 'id', 'url', 'created_at']
    assert first['kind'] == 'notification' and first['id'] == 'N1' and first['url'].endswith('/posts/N1')
    assert first['created_at'] == '2026-09-12T03:00:00Z' and first['notification_type'] == 'feed_comment_reply'
    assert first['text'] == 'Sample Person replied to your comment' and first['captured_at']
    assert set(first) == {key for key in web.SCHEMAS['notification']['fields'] if '[' not in key}
    assert TRACKING not in out
    assert any('seen state' in note for note in result['coverage'])


def test_a_page_of_layout_rows_only_is_an_empty_list_not_a_changed_answer(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([layout('BUCKET_HEADER'), layout('SEE_PREVIOUS_BUTTON')], has_next=False))
    code, out, _ = run(browser, 'notifications', '--json')
    result = json.loads(out)
    assert code == 7 and result['error'] == 'empty' and result['results'] == []


def test_a_notification_row_that_cannot_be_read_is_a_changed_answer(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([{'node': {'row_type': 'NOTIFICATION'}}]))
    code, out, _ = run(browser, 'notifications')
    assert code == 6 and json.loads(out)['error'] == 'failed'


def test_a_refused_first_query_ends_the_command_without_moving_the_tab(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(REJECTED, source='stored', doc_id='999'))
    code, out, _ = run(browser, 'notifications')
    result = json.loads(out)
    assert code == 6 and 'no longer accepts the stored notifications query' in result['message']
    assert routes(browser) == [] and sent(browser) == [FIRST]


def test_a_refused_pagination_query_ends_the_command_without_moving_the_tab(browser):
    known_tab(browser)
    browser.respond('facebook.query', page([notif('N1')], cursor='NC1'))
    code, out, _ = run(browser, 'notifications')
    look(browser).respond('facebook.query', query_result(REJECTED, source='live', doc_id='111'))
    code, out, _ = rerun(browser, out.splitlines()[-1])
    assert code == 6 and 'no longer accepts the stored notifications query' in json.loads(out)['message']
    assert routes(browser) == [] and sent(browser) == [FIRST, LATER]


@pytest.mark.parametrize('flag', ['--since', '--until'])
def test_notifications_have_no_date_window(browser, flag):
    code, out, _ = run(browser, 'notifications', flag, '2026-09-01')
    assert code == 2 and browser.calls() == []
