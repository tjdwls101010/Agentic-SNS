"""The text page (fixture render.json): Reddit markdown as one dense line, quotes kept apart from the author's words."""
import pytest

from conftest import fixture
from reddit.render import flatten, render_page

RENDER = fixture('render.json')


@pytest.mark.parametrize('case', RENDER['text'], ids=lambda c: c['name'])
def test_flatten(case):
    assert flatten(case['input']) == case['line']


def test_a_reply_and_the_quote_it_answers_are_two_voices_on_the_page():
    case = next(c for c in RENDER['text'] if c['name'] == 'quote-then-reply')
    page = render_page({'command': 'comments', 'stop_reason': 'exhausted', 'request_count': 0, 'max_requests': 25,
                        'results': [{'kind': 'comment', 'id': 't1_c1', 'author': 'replier', 'text': case['input'],
                                     'depth': 0, 'url': 'https://www.reddit.com/comments/a/_/c1/'}]},
                       chars=0, command='comments')
    assert '"❝Electric cars are always cheaper to run.❞ ⏎ Not where I live' in page


def test_comment_lines_are_indented_by_depth_up_to_twenty():
    records = [{'kind': 'comment', 'id': f't1_c{d}', 'author': 'a', 'text': 'x', 'depth': d, 'url': 'u'} for d in (0, 3, 30)]
    page = render_page({'command': 'comments', 'stop_reason': 'exhausted', 'request_count': 0, 'max_requests': 25,
                        'results': records}, command='comments').splitlines()
    starts = [line for line in page if '[c' in line]
    assert [len(line) - len(line.lstrip(' ')) for line in starts] == [0, 6, 40]
