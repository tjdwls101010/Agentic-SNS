"""feed through the real CLI and a scripted Aside: pages, handles, windows, the stop table and recovery (fixtures:
paging.json; plan 'stop table', 'operation rotation recovery')."""
import json
import time

from tests.sns.x.scenes import known_tab, limits, query_result, queries, rerun, run, stand_limit, state, state_of

USER = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'example_author', 'name': 'Example'}}


def post(ident, minutes_ago=0, text=None, at=None, **legacy):
    created = time.strftime('%a %b %d %H:%M:%S +0000 %Y', time.gmtime(at if at is not None else time.time() - 60 * minutes_ago))
    return {'__typename': 'Tweet', 'rest_id': ident, 'core': {'user_results': {'result': USER}},
            'legacy': {'full_text': text or f'post {ident}', 'created_at': created, 'favorite_count': 1, **legacy}}


def entry(node, ident=None):
    return {'entryId': f'tweet-{ident or node["rest_id"]}', 'content': {'itemContent': {'itemType': 'TimelineTweet',
                                                                                        'tweet_results': {'result': node}}}}


def home(entries, bottom='CUR1', extra=()):
    items = list(entries) + list(extra)
    if bottom:
        items.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    return {'data': {'home': {'home_timeline_urt': {'instructions': [{'type': 'TimelineAddEntries', 'entries': items}]}}}}


RATE = {'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '499', 'x-rate-limit-reset': str(int(time.time()) + 900)}


def feed(browser, *args, env=None):
    return run(browser, 'feed', *args, env=env)


def test_one_page_by_default_with_a_more_line(browser):
    known_tab(browser).respond('x.query', query_result(home([entry(post('1850000000000000001')),
                                                                     entry(post('1850000000000000002'))]), headers=RATE))
    code, out, err = feed(browser)
    assert code == 0, (out, err)
    lines = out.splitlines()
    assert lines[0].startswith('x feed · feed=foryou · 2 shown · stopped=limit_reached · requests=1')
    assert '[p1] @example_author (Example)' in out and 'url: "https://x.com/example_author/status/1850000000000000001"' in out
    assert lines[-1].startswith('more: uv run "')
    [query] = queries(browser)
    assert query['args']['name'] == 'HomeTimeline'
    assert query['args']['variables'] == {'count': 20, 'includePromotedContent': True, 'requestContext': 'launch',
                                          'withCommunity': True}
    assert query['args']['toggles'] == {'withPayments': False}


def test_more_continues_from_the_cursor_without_repeats(browser):
    known_tab(browser).respond('x.query', query_result(home([entry(post('1850000000000000001'))]), headers=RATE))
    code, out, _ = feed(browser)
    browser.respond('x.state', state())
    browser.respond('x.query', query_result(home([entry(post('1850000000000000001')), entry(post('1850000000000000003'))],
                                               bottom='CUR2'), headers=RATE), name='HomeTimeline')
    code, out, _ = rerun(browser, out.splitlines()[-1])
    assert code == 0, out
    assert '1 shown' in out.splitlines()[0] and '1850000000000000003' in out and '1850000000000000001' not in out
    second = queries(browser)[-1]
    assert second['args']['variables']['cursor'] == 'CUR1'


def test_the_following_feed_uses_its_own_operation_and_is_not_newest_first(browser):
    posted = time.time() - 1800
    known_tab(browser).respond('x.query', query_result(home([entry(post('1850000000000000001', at=posted))], bottom=None),
                                                               headers=RATE))
    # the window is the day of the post itself (TZ=UTC for the run), so the test does not depend on the hour it runs
    code, out, _ = feed(browser, '--feed', 'following', '--since', time.strftime('%Y-%m-%d', time.gmtime(posted)))
    assert code == 0, out
    assert [c['args']['name'] for c in queries(browser)] == ['HomeLatestTimeline']
    assert 'sample (not in date order)' in out.splitlines()[1]


def test_a_repost_row_is_the_reposters_act_with_the_original_underneath(browser):
    original = post('1850000000000000001', 120, text='the original words', retweet_count=50, favorite_count=400)
    reposter = {'__typename': 'User', 'rest_id': '1000000003', 'core': {'screen_name': 'reposter_x', 'name': 'R'}}
    row = {'__typename': 'Tweet', 'rest_id': '1850000000000000009', 'core': {'user_results': {'result': reposter}},
           'legacy': {'full_text': 'RT @example_author: the original…', 'created_at': original['legacy']['created_at'],
                      'retweet_count': 50, 'favorite_count': 0, 'retweeted_status_result': {'result': original}}}
    known_tab(browser).respond('x.query', query_result(home([entry(row)]), headers=RATE))
    code, out, _ = feed(browser, '--chars', '0')
    assert code == 0, out
    assert '[p1] @reposter_x (R) reposted' in out
    assert 'repost of: @example_author (Example)' in out and 'likes=400' in out and '"the original words"' in out
    assert 'RT @' not in out


def test_ads_are_left_out_and_counted(browser):
    ad = {'entryId': 'promoted-tweet-1850000000000000090-1', 'content': {'itemContent': {'itemType': 'TimelineTweet',
          'tweet_results': {'result': post('1850000000000000090')}}}}
    known_tab(browser).respond('x.query', query_result(home([entry(post('1850000000000000001'))], extra=[ad]),
                                                               headers=RATE))
    code, out, _ = feed(browser)
    assert code == 0 and 'coverage: 1 promoted entries (ads) left out' in out


def test_json_envelope(browser):
    known_tab(browser).respond('x.query', query_result(home([entry(post('1850000000000000001'))]), headers=RATE))
    code, out, _ = feed(browser, '--json')
    envelope = json.loads(out)
    assert code == 0 and envelope['ok'] and envelope['request_count'] == 1 and 'max_requests' not in envelope
    assert envelope['results'][0]['id'] == '1850000000000000001' and envelope['next'].startswith('uv run')


def test_an_explicitly_empty_feed_is_exit_7(browser):
    known_tab(browser).respond('x.query', query_result(home([], bottom=None), headers=RATE))
    code, out, _ = feed(browser)
    assert code == 7 and json.loads(out)['error'] == 'empty'


def limited(reset):
    return query_result('{"errors":[{"code":88,"message":"Rate limit exceeded"}]}', status=429, headers={
        'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '0', 'x-rate-limit-reset': str(reset)})


def test_the_operations_limit_before_any_record_is_exit_10_and_not_a_block(browser):
    reset = int(time.time()) + 600
    known_tab(browser).respond('x.query', limited(reset))
    code, out, _ = feed(browser)
    envelope = json.loads(out)
    assert code == 10 and envelope['error'] == 'scope_limit' and envelope['stop_reason'] == 'rate_limited'
    assert envelope['limit']['scope'] == 'HomeTimeline' and envelope['limit']['reset'] == reset
    assert 'other commands' in envelope['fix']
    assert not state_of()['blocked'] and limits()['HomeTimeline']['blocked_until'] == reset  # the operation only


def test_the_operations_limit_after_records_is_a_resumable_stop(browser):
    reset = int(time.time()) + 600
    known_tab(browser).respond('x.query', query_result(home([entry(post('1850000000000000001'))]), headers=RATE))
    browser.respond('x.query', limited(reset))
    code, out, _ = feed(browser, '--limit', '40')
    assert code == 0, out
    head = out.splitlines()[0]
    assert 'stopped=rate_limited' in head and 'limit HomeTimeline resets' in head
    assert out.splitlines()[-1].startswith('more: ')


def test_a_known_empty_bucket_is_refused_without_a_request(browser):
    stand_limit('HomeTimeline', remaining=0)
    known_tab(browser)
    code, out, _ = feed(browser)
    assert code == 10 and 'x.query' not in browser.ops()


def test_the_time_limit_after_records_is_a_resumable_stop(browser):
    known_tab(browser).respond('x.query', query_result(home([entry(post('1850000000000000001'))]), headers=RATE))
    browser.respond('x.query', {'__sleep': 3, **query_result(home([entry(post('1850000000000000002'))], bottom='CUR2'),
                                                           headers=RATE)})
    code, out, _ = feed(browser, '--limit', '40', env={'SNS_DEADLINE_SECONDS': '8'})
    assert code == 0, out
    assert 'stopped=time_limit' in out.splitlines()[0] and out.splitlines()[-1].startswith('more: ')


def test_the_time_limit_before_any_record_is_exit_6(browser):
    known_tab(browser)
    code, out, _ = feed(browser, env={'SNS_DEADLINE_SECONDS': '0.2'})
    envelope = json.loads(out)
    assert code == 6 and envelope['stop_reason'] == 'time_limit'


def test_a_lock_mid_read_keeps_the_records_and_exits_5(browser):
    known_tab(browser).respond('x.query', query_result(home([entry(post('1850000000000000001'))]), headers=RATE))
    browser.respond('x.query', query_result('{"errors":[{"code":326,"message":"locked"}]}', status=403))
    code, out, _ = feed(browser, '--limit', '40')
    assert code == 5 and '1850000000000000001' in out and 'coverage: incomplete' in out
    assert state_of()['block_reason'] == 'account_locked' and state_of()['person']['viewer'] == '1000000099'
    assert 'more:' not in out


def test_missing_features_are_added_and_the_read_retried_once(browser):
    known_tab(browser).respond('x.query', query_result(
        '{"errors":[{"message":"The following features cannot be null: brand_new_flag"}]}', status=400))
    browser.respond('x.query', query_result(home([entry(post('1850000000000000001'))]), headers=RATE))
    code, out, _ = feed(browser)
    assert code == 0, out
    retry = queries(browser)[1]
    assert retry['args']['extra_features'] == ['brand_new_flag']
    assert 'requests=2' in out.splitlines()[0]


def test_a_refused_signature_is_retried_with_a_fresh_generator(browser):
    known_tab(browser).respond('x.query', query_result('', status=404))
    browser.respond('x.query', query_result(home([entry(post('1850000000000000001'))]), headers=RATE))
    code, out, _ = feed(browser)
    assert code == 0, out
    assert [c['args'].get('fresh_generator') for c in queries(browser)] == [None, True]


def test_a_refused_csrf_token_is_retried_once_then_needs_login(browser):
    refused = query_result('{"errors":[{"code":353,"message":"This request requires a matching csrf cookie and header."}]}',
                           status=403)
    known_tab(browser).respond('x.query', refused)
    browser.respond('x.query', query_result(home([entry(post('1850000000000000001'))]), headers=RATE))
    code, out, _ = feed(browser)
    assert code == 0 and browser.ops().count('x.query') == 2, out
    browser.respond('x.state', state()).respond('x.query', refused).respond('x.query', refused)
    code, out, _ = feed(browser)
    assert code == 4 and browser.ops().count('x.query') == 4


def test_variables_x_no_longer_accepts_need_an_update(browser):
    known_tab(browser).respond('x.query', query_result('{"errors":[{"message":"x must be defined"}]}', status=422))
    code, out, _ = feed(browser)
    envelope = json.loads(out)
    assert code == 6 and 'update' in envelope['fix']
    assert browser.ops().count('x.query') == 1


def test_out_refuses_an_endless_feed_without_a_limit_and_collects_with_one(browser, tmp_path):
    """S2: with no request budget a feed that never ends needs --limit to know when to stop (both feeds are endless)."""
    known_tab(browser)
    for name in ('foryou', 'following'):
        code, out, _ = feed(browser, '--feed', name, '--out', str(tmp_path / f'{name}.ndjson'))
        envelope = json.loads(out)
        assert code == 2 and envelope['error'] == 'argument' and '--limit' in envelope['fix'], out
    assert queries(browser) == [] and not (tmp_path / 'foryou.ndjson').exists()
    browser.respond('x.query', query_result(home([entry(post('1850000000000000001')),
                                                  entry(post('1850000000000000002'))]), headers=RATE))
    code, out, _ = feed(browser, '--out', str(tmp_path / 'saved.ndjson'), '--limit', '2')
    assert code == 0 and '2 saved to' in out, out
    assert len((tmp_path / 'saved.ndjson').read_text().splitlines()) >= 3  # header, two records, the page marker


def test_a_feed_has_no_request_budget(browser):
    code, out, _ = feed(browser, '--max-requests', '5')
    assert code == 2 and 'unrecognized arguments' in json.loads(out)['message']
