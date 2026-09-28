"""The default text output through the CLI: dense, one line per fact, the author's text kept as sent."""
from .fixtures.builders import envelope, feed, listed_post
from .helpers import POST, run_cli


def test_a_listing_is_a_header_three_lines_per_post_and_the_next_hops(fake_aside):
    result = run_cli('home', '--limit', '3')
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith('home · 3 shown · stopped=limit_reached · feed=foryou · ')
    assert 'local budget' in lines[0] and '(window 1/120)' in lines[0]
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
