"""The default text output through the CLI: dense, one line per fact, the author's text kept as sent."""
from .fixtures.builders import envelope, feed, listed_post
from .helpers import POST, run_cli


def test_a_listing_is_a_header_three_lines_per_post_and_the_next_hops(fake_aside):
    result = run_cli('home', '--limit', '3')
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith('home · 3 shown · stopped=limit_reached · feed=foryou · ')
    assert 'requests 1 of 10 · window 1/120 per 10 min' in lines[0]
    assert lines[1].startswith('[p1] @fixture_user (Synthetic Person) · ')
    assert lines[2] == '     "Synthetic post 1"'
    assert lines[3] == '     url: "https://www.threads.com/@fixture_user/post/FIX_1"'
    assert lines[-2].startswith('more: ') and '--after' in lines[-2]
    assert lines[-1].startswith('open: post <url>')
    assert len(lines) == 1 + 3 * 3 + 2


def test_whitespace_is_folded_line_and_paragraph_breaks_are_marked_and_zero_width_characters_dropped(routes):
    text = 'first  line\r\nsecond​line   \n\n  third'
    routes.set('BarcelonaFeedDirectQuery', envelope(feed([listed_post(1, caption={'text': text})])))
    routes.write()
    result = run_cli('home', '--feed', 'following')
    assert '     "first line⏎secondline⏎⏎third"' in result.stdout.splitlines()


def test_text_output_keeps_urls_handles_and_body_exactly_as_threads_sent_them(fake_aside):
    """Threads renders no markdown, so `__` and `**` are the author's characters and part of handles and URLs."""
    result = run_cli('post', POST)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'url: "https://www.threads.com/@fixture__other/post/FIX_1"' in result.stdout
    assert '@fixture__other (Synthetic Other)' in result.stdout
    assert 'line two with __init__ and **stars** kept' in result.stdout


def test_a_long_preview_is_cut_at_chars_and_marked(routes):
    routes.set('BarcelonaFeedDirectQuery', envelope(feed([listed_post(1, caption={'text': 'x' * 50})])))
    routes.write()
    lines = run_cli('home', '--feed', 'following', '--chars', '10').stdout.splitlines()
    assert '     "' + 'x' * 10 + '…"' in lines


def test_the_header_names_requests_the_shared_window_and_bytes(fake_aside):
    header = run_cli('home', '--limit', '1').stdout.splitlines()[0]
    assert header.endswith('requests 1 of 10 · window 1/120 per 10 min · fetched 0.0MB'), header
    assert 'local budget' not in header


def test_a_relationship_listing_names_its_relation(routes):
    from .fixtures.builders import person, users
    routes.set('BarcelonaFriendshipsFollowingTabQuery',
               envelope(users('following', [person(60)], counts={'following': 1}))).write()
    header = run_cli('graph', '@fixture_user', 'following').stdout.splitlines()[0]
    assert 'relation=following' in header


def test_an_unreported_reply_count_is_unknown_not_none(routes):
    routes.edit('/@fixture_user/post/FIX_2', lambda html: html.replace('"direct_reply_count": 7', '"x": 7')).write()
    text = run_cli('post', POST).stdout
    assert '~None' not in text and 'None' not in text.splitlines()[1]
    assert 'of unknown direct received' in text.splitlines()[1]


def test_a_link_preview_shows_where_the_link_goes(routes):
    wrapped = 'https://l.threads.com/?u=https%3A%2F%2Fexample.com%2Fa%3Fb%3D1&e=SYNTHETIC&s=1'
    info = {'direct_reply_count': 12, 'link_preview_attachment': {'title': 'Synthetic link', 'url': wrapped}}
    routes.set('BarcelonaFeedDirectQuery', envelope(feed([listed_post(1, text_post_app_info=info)]))).write()
    body = run_cli('home', '--feed', 'following', '--json').stdout
    assert '"url": "https://example.com/a?b=1"' in body and 'l.threads.com' not in body
    assert 'link: "Synthetic link" (https://example.com/a?b=1)' in run_cli('home', '--feed', 'following').stdout
