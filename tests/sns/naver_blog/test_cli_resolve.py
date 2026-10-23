"""resolve through the real cli: where naver.me short links lead without following them, any number of them (a few at a
time when the time limit or a hold interrupts), and another platform's links refused with the command that reads them."""
import json

from tests.sns.support.cli import command_of

SHORT = 'https://naver.me/{}'


def codes(count):
    return [f'Code{i:02d}' for i in range(count)]


def lead(naver, code, status=302, location='https://m.blog.naver.com/cafe_note/224000000001'):
    naver.respond('naver.me', f'/{code}', status=status, location=location, body='')


def test_resolve_shows_where_short_links_go_without_following(naver):
    naver.respond('naver.me', '/AbCd12Ef', status=307, location='https://brandconnect.naver.com/affiliates/42?x=1', body='')
    naver.respond('naver.me', '/ZZ9', status=302, location='https://m.blog.naver.com/cafe_note/224000000001', body='')
    code, out, _ = naver.run('naver-blog', 'resolve', 'https://naver.me/AbCd12Ef', 'naver.me/ZZ9')
    assert code == 0, out
    assert 'https://brandconnect.naver.com/affiliates/42?x=1 (brandconnect.naver.com, id affiliates/42)' in out
    assert 'post cafe_note/224000000001' in out and len(naver.fetches()) == 2


def test_resolve_refuses_what_is_not_a_short_link(naver):
    code, out, _ = naver.run('naver-blog', 'resolve', 'https://example.com/x')
    assert code == 2 and naver.fetches() == [] and json.loads(out)['command'] == 'resolve'


def test_resolve_names_the_command_that_reads_another_platforms_link(naver):
    code, out, _ = naver.run('naver-blog', 'resolve', 'https://www.reddit.com/r/example/comments/abc123/a_title/')
    envelope = json.loads(out)
    assert code == 2 and 'Reddit link' in envelope['message'] and 'reddit post' in envelope['fix']
    assert naver.fetches() == []


def test_more_than_ten_links_are_all_read(naver):
    """The old skill's budget of 10 ended an 11th link with exit 8 and no way to go on: there is no budget now."""
    for code in codes(12):
        lead(naver, code)
    code, out, _ = naver.run('naver-blog', 'resolve', *[SHORT.format(c) for c in codes(12)], '--json')
    envelope = json.loads(out)
    assert code == 0 and len(envelope['results']) == 12 and 'next' not in envelope
    assert envelope['stop_reason'] == 'exhausted' and envelope['request_count'] == 12


def test_the_time_limit_stops_with_the_links_not_yet_read_and_more_goes_on(naver):
    for code in codes(12):
        lead(naver, code)
    links = [SHORT.format(c) for c in codes(12)]
    code, out, _ = naver.run('naver-blog', 'resolve', *links, '--json', env={'SNS_DEADLINE_SECONDS': '8'})
    first = json.loads(out)
    assert code == 0 and first['stop_reason'] == 'time_limit' and 0 < len(first['results']) < 12
    assert first['next'].count('naver.me/') == 12 - len(first['results'])
    naver.monkeypatch.delenv('SNS_DEADLINE_SECONDS')   # the pacing the first run left is still owed in the second
    code, out, _ = naver.run(*command_of('more: ' + first['next']), '--json')
    second = json.loads(out)
    assert code == 0 and len(first['results']) + len(second['results']) == 12 and 'next' not in second
    assert [r['link'] for r in first['results'] + second['results']] == links


def test_a_hold_in_the_middle_keeps_what_was_read_and_waits_for_the_rest(naver):
    lead(naver, 'Code00')
    naver.respond('naver.me', '/Code01', status=429, body='')
    code, out, _ = naver.run('naver-blog', 'resolve', SHORT.format('Code00'), SHORT.format('Code01'),
                             SHORT.format('Code02'), '--json')
    envelope = json.loads(out)
    assert code == 0 and envelope['stop_reason'] == 'rate_limited' and len(envelope['results']) == 1
    assert envelope['next'].count('naver.me/') == 2 and envelope['limit']['reset']


def test_the_links_left_are_named_with_no_account_hint_and_no_account_request(naver):
    """The command that reads the rest needs no handle (its links are its whole state), so a cold hint, a spent
    deadline or a standing hold cannot take it away."""
    for code in codes(12):
        lead(naver, code)
    code, out, _ = naver.run('naver-blog', 'resolve', *[SHORT.format(c) for c in codes(12)], '--json',
                             env={'SNS_DEADLINE_SECONDS': '8'})
    first = json.loads(out)
    assert code == 0 and first['stop_reason'] == 'time_limit' and first['next']
    assert '--after' not in first['next'] and '/api/current-user' not in naver.paths()
