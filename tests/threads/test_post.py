"""Reading one post page through the CLI: the page's own payloads, chosen by shape and identity, never by name."""
import json
import os
from pathlib import Path

from .helpers import POST, calls, run_cli

PAGE = '/@fixture_user/post/FIX_2'


def test_post_reads_body_parents_and_first_reply_batch_in_one_request(fake_aside):
    result = run_cli('post', POST, '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    shown = [(p['id'], p['role'], p['depth']) for p in body['results']]
    assert shown == [('1', 'parent', 0), ('2', 'post', 0), ('3', 'reply', 0), ('4', 'reply', 1),
                     ('7', 'reply', 0), ('5', 'reply', 0), ('6', 'reply', 0)]
    target = body['results'][1]
    assert target['text'] == 'Synthetic post body line one\nline two with __init__ and **stars** kept'
    assert body['results'][3]['relation'] == 'reply-to=3'
    assert body['results'][4]['unavailable'] is True
    # 7 reported; 3 readable direct replies and 1 tombstone received, so about 3 were never sent.
    assert body['completeness'] == {'reported_direct': 7, 'received_direct': 3, 'shown_direct': 3,
                                    'shown_descendants': 1, 'unshown_received': 0, 'unavailable': 1,
                                    'unfetched': 3, 'unfetched_is_estimate': True}
    assert body['stop_reason'] == 'not_paginable' and body['next'] is None
    assert [c['snippet'] for c in calls(fake_aside)] == ['page']


def test_post_limit_counts_direct_replies_and_keeps_the_rest_as_received_not_shown(fake_aside):
    body = json.loads(run_cli('post', POST, '--limit', '1', '--json').stdout)
    assert [p['id'] for p in body['results']] == ['1', '2', '3', '4']
    assert (body['completeness']['shown_direct'], body['completeness']['unshown_received']) == (1, 2)


def test_recent_sort_reads_the_recent_route(fake_aside):
    result = run_cli('post', POST, '--sort', 'recent', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert [c['path'] for c in calls(fake_aside)] == ['/@fixture_user/post/FIX_2?sort_order=recent']
    assert [p['id'] for p in json.loads(result.stdout)['results']][2:] == ['6', '5', '7', '3', '4']


def test_a_second_payload_claiming_the_same_role_is_refused_not_guessed(routes):
    def duplicate(html):
        start = html.index('{"__bbox": {"complete": true, "result": {"data": {"media": {"pk": "2"')
        end = html.index('"viewer"', start)
        copy = html[start:end].replace('Synthetic post body', 'Synthetic other body')
        return html[:start] + copy + '"viewer": {}}}}}, ' + html[start:]
    routes.edit(PAGE, duplicate).write()
    result = run_cli('post', POST, '--json')
    assert result.returncode == 6, result.stdout + result.stderr
    assert 'Synthetic' not in result.stdout


def test_post_route_without_a_single_post_identity_is_refused(routes):
    routes.edit(PAGE, lambda html: html.replace('"variables": {"postID": "2"}}]', '"variables": {"postID": "9"}}]'))
    routes.write()
    result = run_cli('post', POST, '--json')
    assert result.returncode == 6, result.stdout + result.stderr


def test_a_cache_override_written_before_post_pages_left_the_registry_still_loads(fake_aside):
    """An override naming the retired post-page queries keeps working for the queries that remain."""
    home = Path(os.environ['THREADS_HOME'])
    home.mkdir(parents=True)
    legacy = Path(__file__).with_name('fixtures') / 'legacy' / 'registry.json'
    (home / 'registry.json').write_text(legacy.read_text())
    feed = run_cli('home', '--feed', 'following', '--limit', '3', '--json')
    assert feed.returncode == 0, feed.stdout + feed.stderr
    assert calls(fake_aside)[-1]['doc_id'] == '2001'
    post = run_cli('post', POST, '--json')
    assert post.returncode == 0, post.stdout + post.stderr


def test_a_page_for_another_shortcode_is_never_rendered(routes):
    routes.copy(PAGE, '/@fixture_user/post/WRONG').write()
    result = run_cli('post', 'https://www.threads.com/@fixture_user/post/WRONG', '--json')
    assert result.returncode == 6, result.stdout + result.stderr
    assert 'Synthetic' not in result.stdout


def test_a_deleted_reply_keeps_the_replies_received_under_it(routes):
    tombstone = '{"node": {"pk": "3", "id": "3_43", "is_post_unavailable": true}}'
    routes.edit(PAGE, lambda html: html.replace(html[html.index('{"node": {"pk": "3"'):
                                                     html.index('{"node": {"pk": "4"') - 2], tombstone)).write()
    body = json.loads(run_cli('post', POST, '--json').stdout)
    assert '4' in [p['id'] for p in body['results']]
    assert (body['completeness']['unavailable'], body['completeness']['shown_descendants']) == (2, 1)
