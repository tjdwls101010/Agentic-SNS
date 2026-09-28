from argparse import Namespace

from threads_skill._render import render, text
from threads_skill._models import build_post
from .test_models import raw_post


def test_text_normalization_and_dense_next_hops():
    assert text(' **bold**  [link](https://example.invalid/)\nzero\u200bwidth ', 0) == '**bold** [link](https://example.invalid/)⏎zerowidth'
    result = {'results': [build_post(raw_post()).to_dict()], 'stop_reason': 'limit_reached',
              'next': 'python3 threads.py home --after 1', 'budget': {'remaining': 8, 'limit': 10, 'window_used': 2, 'window_limit': 120}, 'fetched_bytes': 800000}
    output = render(result, Namespace(command='home', chars=180))
    assert 'local budget 8 of 10' in output and '0.8MB' in output
    assert 'url: "https://www.threads.com/@fixture_user/post/FIX_1"' in output
    assert 'more: python3 threads.py home --after 1' in output
    assert len(output.splitlines()) <= 7


def test_text_output_keeps_urls_handles_and_body_exactly_as_threads_sent_them(fake_aside):
    """Threads renders no markdown, so `__` and `**` are the author's characters and part of handles and URLs."""
    from .test_cli import run_cli
    result = run_cli('post', 'https://www.threads.com/@fixture_user/post/FIX_2')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'url: "https://www.threads.com/@fixture__other/post/FIX_1"' in result.stdout
    assert '@fixture__other (Synthetic Other)' in result.stdout
    assert 'line two with __init__ and **stars** kept' in result.stdout
