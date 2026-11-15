"""An author nobody named (the platform sent no account for it) reads as unavailable in text, on X and Threads, whose
records now always carry an author object (P5: {name, id, url} with nulls when unknown) — an empty object is still
no author (review of P5: it printed '@?')."""
import pytest

from sns import threads, x


def record(kind='post'):
    return {'kind': kind, 'id': '1', 'url': None, 'created_at': None, 'text': 'hello', 'promoted': False,
            'author': {'name': None, 'id': None, 'url': None}}


@pytest.mark.parametrize('platform', [x, threads], ids=['x', 'threads'])
def test_an_author_object_without_any_value_reads_as_unavailable(platform):
    envelope = {'ok': True, 'platform': platform.PLATFORM.key, 'command': 'post', 'results': [record()]}
    drawn = platform.PLATFORM.render(envelope, None, 'post')
    lines = drawn[0] if isinstance(drawn, tuple) else drawn
    text = '\n'.join(lines)
    assert 'unavailable' in text and '@?' not in text, text
