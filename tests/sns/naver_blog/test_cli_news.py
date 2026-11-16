"""me news (내소식) through the real CLI and synthetic Naver answers: the request is the site's own NewsList call and
nothing else, records come newest first as Naver sends them, the cursor continues, and an empty or changed answer ends
the way other reads do."""
import json

import pytest

from tests.sns.naver_blog.scene import M, SECTION
from tests.sns.support.cli import command_of, more_line

PATH = '/ajax/NewsList.naver'
# The query the blog home sent on 2026-11-16 (observed in the browser), not read from the ledger.
SITE_QUERY = {'countPerPage': 5, 'lastMessageTimeKey': '', 'pagingModeType': 'next'}
ITEM = {'commcastCategoryType': 'BLOG_COMMENT_REPLY', 'url': 'http://blog.naver.com/example/123?copen=1', 'count': 0,
        'guestbookNo': None, 'commentNo': 42, 'profileImagePath': '/profile/example.png', 'createTime': 1794551249000,
        'title': 'Example post', 'writerNickName': 'Example writer', 'isRead': False, 'createKeyString': 'cursor-1',
        'writerBlogId': 'example'}


def answer(items, more=False, cursor='cursor-1'):
    return ")]}',\n" + json.dumps({'result': {'hasPrev': False, 'hasNext': more, 'firstMessageTimeKey': cursor,
                                               'lastMessageTimeKey': cursor, 'mrBlogQuestion': None, 'list': items}})


def test_news_records_and_the_one_request_it_sends(naver):
    naver.logged_in()
    naver.respond(SECTION, PATH, body=answer([ITEM]))
    code, out, _ = naver.run('naver-blog', 'me', 'news', '--json')
    assert code == 0, out
    [record] = json.loads(out)['results']
    assert record['kind'] == 'news' and record['id'] == 'news:cursor-1'
    assert record['category'] == 'BLOG_COMMENT_REPLY' and record['read'] is False
    assert record['title'] == 'Example post' and record['url'] == ITEM['url']
    assert record['author'] == {'name': 'Example writer', 'id': 'example', 'url': 'https://blog.naver.com/example',
                                'blog_name': None}
    assert record['created_at'] == '2026-11-13T15:27+09:00'   # 1794551249000 ms, a KST minute like every Naver kind
    assert not {'profileImagePath', 'count', 'commentNo', 'guestbookNo', 'profile_image', 'comment_no'} & set(record)
    assert naver.paths() == ['/api/current-user', PATH] and naver.unused() == []
    sent = naver.fetches()[-1]
    assert (sent['host'], sent['path'], sent['query']) == (SECTION, PATH, SITE_QUERY)


def test_news_text_lines(naver):
    naver.logged_in()
    naver.respond(SECTION, PATH, body=answer([ITEM, {**ITEM, 'createKeyString': 'cursor-0', 'title': 'Older post',
                                                     'isRead': True}]))
    code, out, _ = naver.run('naver-blog', 'me', 'news')
    assert code == 0, out
    lines = out.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith('[n1] '))
    assert 'BLOG_COMMENT_REPLY' in lines[first] and 'Example writer' in lines[first] and 'unread' in lines[first]
    assert 'Example post' in lines[first + 1] and lines[first + 2].strip() == 'url: ' + ITEM['url']
    second = next(line for line in lines if line.startswith('[n2] '))
    assert ' read' in second and 'unread' not in second
    assert out.index('Example post') < out.index('Older post')   # Naver's order, newest first


def test_news_more_and_the_continuation_sends_the_cursor(naver):
    naver.logged_in()
    naver.respond(SECTION, PATH, body=answer([ITEM], more=True), query={'lastMessageTimeKey': ''})
    code, out, _ = naver.run('naver-blog', 'me', 'news', '--limit', '1')
    assert code == 0 and 'Example post' in out and more_line(out), out
    naver.logged_in()
    naver.respond(SECTION, PATH, body=answer([{**ITEM, 'createKeyString': 'cursor-2', 'title': 'Second post'}],
                                             cursor='cursor-2'), query={'lastMessageTimeKey': 'cursor-1'})
    code, out, _ = naver.run(*command_of(more_line(out)))
    assert code == 0 and 'Second post' in out and 'Example post' not in out, out
    sent = naver.fetches()[-1]
    assert (sent['host'], sent['path'], sent['query']) == (SECTION, PATH, {**SITE_QUERY, 'lastMessageTimeKey': 'cursor-1'})
    assert naver.unused() == []


def test_news_empty_is_exit_7(naver):
    naver.logged_in()
    naver.respond(SECTION, PATH, body=answer([], cursor=''))
    code, out, _ = naver.run('naver-blog', 'me', 'news')
    assert code == 7 and json.loads(out)['error'] == 'empty', out


def test_a_changed_news_answer_is_exit_6(naver):
    naver.logged_in()
    naver.respond(SECTION, PATH, body=")]}',\n" + json.dumps({'result': {'hasNext': False}}))
    code, out, _ = naver.run('naver-blog', 'me', 'news')
    assert code == 6 and json.loads(out)['error'] == 'failed', out
    naver.logged_in()
    naver.respond(SECTION, PATH, body=answer([ITEM], more=True, cursor=''))   # more follow, and no cursor to ask with
    code, out, _ = naver.run('naver-blog', 'me', 'news')
    assert code == 6 and json.loads(out)['error'] == 'failed', out


def test_news_asks_who_is_logged_in_first(naver):
    naver.respond(M, '/api/current-user', json={'isSuccess': True, 'result': {'loggedIn': False}})
    code, out, _ = naver.run('naver-blog', 'me', 'news')
    assert code == 4 and naver.paths() == ['/api/current-user'], out


def raw(result):
    return ")]}',\n" + json.dumps({'result': result})


@pytest.mark.parametrize('more', ['true', 1, None], ids=['string', 'number', 'missing'])
def test_a_page_that_does_not_say_plainly_whether_more_follow_is_a_changed_answer(naver, more):
    naver.logged_in()
    result = {'lastMessageTimeKey': 'cursor-1', 'list': [ITEM]}
    naver.respond(SECTION, PATH, body=raw(result if more is None else {**result, 'hasNext': more}))
    code, out, _ = naver.run('naver-blog', 'me', 'news')
    assert code == 6 and json.loads(out)['error'] == 'failed', out


def test_a_next_page_that_names_the_cursor_it_was_asked_with_stops_the_read(naver):
    naver.logged_in()
    naver.respond(SECTION, PATH, body=answer([ITEM], more=True), query={'lastMessageTimeKey': ''})
    naver.respond(SECTION, PATH, body=answer([{**ITEM, 'createKeyString': 'cursor-2'}], more=True),
                  query={'lastMessageTimeKey': 'cursor-1'})
    code, out, _ = naver.run('naver-blog', 'me', 'news', '--limit', '10', '--json')
    result = json.loads(out)
    assert code == 8 and result['error'] == 'partial' and [r['id'] for r in result['results']] == ['news:cursor-1']


def test_a_page_of_items_none_of_which_can_be_read_is_a_changed_answer(naver):
    naver.logged_in()
    naver.respond(SECTION, PATH, body=answer([{'title': 'no key'}, {'createKeyString': None}]))
    code, out, _ = naver.run('naver-blog', 'me', 'news')
    assert code == 6 and json.loads(out)['error'] == 'failed', out
