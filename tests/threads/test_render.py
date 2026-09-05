from argparse import Namespace

from threads_skill._render import render, text
from threads_skill._models import build_post
from .test_models import raw_post


def test_text_normalization_and_dense_next_hops():
    assert text(' **bold**  [link](https://example.invalid/)\nzero\u200bwidth ', 0) == 'bold link (https://example.invalid/)⏎zerowidth'
    result = {'results': [build_post(raw_post()).to_dict()], 'stop_reason': 'limit_reached',
              'next': 'python3 threads.py home --after 1', 'budget': {'remaining': 8, 'limit': 10, 'window_used': 2, 'window_limit': 120}, 'fetched_bytes': 800000}
    output = render(result, Namespace(command='home', chars=180))
    assert 'local budget 8 of 10' in output and '0.8MB' in output
    assert 'url: "https://www.threads.com/@fixture_user/post/FIX_1"' in output
    assert 'more: python3 threads.py home --after 1' in output
    assert len(output.splitlines()) <= 7
