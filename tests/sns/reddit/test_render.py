"""The text page's record lines (fixture render.json): Reddit markdown as one dense line, quotes kept apart from the
author's words, comments indented by depth, and the media a record carries."""
import json

import pytest

from sns.reddit import PLATFORM
from tests.sns.reddit.scene import fixture

RENDER = fixture('render.json')
LINK = 'https://www.reddit.com/comments/a/_/c1/'


def comment(text='x', depth=0, **extra):
    return {'kind': 'comment', 'id': f't1_c{depth}', 'author': 'replier', 'text': text, 'depth': depth, 'url': LINK,
            **extra}


def lines(*records, chars=0, command='comments', **envelope):
    return PLATFORM.render({'results': list(records), **envelope}, chars, command)


def shown_text(rendered):
    """The text a record line shows: the JSON string after its text[N of M chars shown]: label."""
    line = next(l for l in '\n'.join(rendered).splitlines() if 'chars shown]: ' in l)
    return json.loads(line.split('chars shown]: ', 1)[1])


@pytest.mark.parametrize('case', RENDER['text'], ids=lambda c: c['name'])
def test_flatten(case):
    assert shown_text(lines(comment(case['input']))) == case['line']


def test_a_reply_and_the_quote_it_answers_are_two_voices_on_the_page():
    case = next(c for c in RENDER['text'] if c['name'] == 'quote-then-reply')
    assert '"❝Electric cars are always cheaper to run.❞ ⏎ Not where I live' in '\n'.join(lines(comment(case['input'])))


def test_comment_lines_are_indented_by_depth_up_to_twenty():
    page = '\n'.join(lines(*[comment('x', d) for d in (0, 3, 30)], chars=None)).splitlines()
    starts = [line for line in page if '[c' in line]
    assert [len(line) - len(line.lstrip(' ')) for line in starts] == [0, 6, 40]


def test_the_default_clips_and_zero_shows_everything_received():
    long = 'word ' * 100
    assert 'text[180 of ' in '\n'.join(lines(comment(long), chars=None))
    assert f'text[{len(long.strip())} of {len(long.strip())} chars shown]' in '\n'.join(lines(comment(long), chars=0))


def test_a_post_carries_its_media_with_number_kind_size_and_both_urls():
    media = [{'n': 1, 'kind': 'video', 'image_url': 'https://preview.redd.it/p.jpg', 'video_url': 'https://v.redd.it/v.mp4',
              'width': 1280, 'height': 720, 'alt': 'a clip', 'media_id': None}]
    page = '\n'.join(lines({'kind': 'post', 'id': 't3_a', 'subreddit': 's', 'author': 'u', 'title': 'T', 'text': '',
                            'url': 'https://www.reddit.com/comments/a/', 'media': media}, command='post'))
    assert 'media 1: video 1280x720 image: "https://preview.redd.it/p.jpg" video: "https://v.redd.it/v.mp4" ' \
           'caption: "a clip"' in page


def test_the_thread_line_comes_first_and_labels_follow_the_kind():
    rendered = lines({'kind': 'subreddit', 'id': 't5_a', 'name': 'x', 'url': 'u'}, {'kind': 'user', 'id': 't2_b', 'name': 'y',
                                                                              'url': 'u'},
                     {'kind': 'wiki_index', 'id': 'wiki:x', 'subreddit': 'x', 'url': 'u'}, command='about',
                     thread={'reported': 3, 'received': 2, 'sort': 'best'})
    assert rendered[0].startswith('thread: 3 comments reported')
    assert [l.split()[0] for l in rendered[1:] if l.startswith('[')] == ['[s1]', '[u1]', '[w1]']
