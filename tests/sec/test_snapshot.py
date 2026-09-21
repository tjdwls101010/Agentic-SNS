"""Format detection, encoding, normalization and provenance of a saved reading snapshot."""

import pytest
from snapshot import cell_text, collapse


def test_a_cell_of_only_zero_width_spaces_is_an_empty_layout_cell():
    # Workiva fills layout cells with &#8203;, which Python's \s does not match, so 51% of
    # NBIS blocks were a truthy string that rendered as nothing.
    assert cell_text('\u200b') == ''
    assert cell_text('\u200b\u200b\u200b') == ''
    assert cell_text(' \u200b \u200b ') == ''
    assert cell_text('\n\t\u200b\n') == ''


def test_a_cell_mixing_a_zero_width_space_with_text_keeps_the_character():
    # No sample in the measured documents mixed U+200B into a real value, so removing it
    # there would be a change without evidence.
    assert cell_text('foo\u200bbar') == 'foo\u200bbar'
    assert cell_text(' Share\u200bholders ') == 'Share\u200bholders'


def test_whitespace_that_python_already_matches_collapses_to_one_space():
    assert cell_text('a\xa0b') == 'a b'
    assert cell_text('a\u202fb') == 'a b'
    assert cell_text('a\u2007b') == 'a b'
    assert cell_text('a \n\t b') == 'a b'


@pytest.mark.parametrize(
    'value',
    [
        '(1,968.1)',
        '—',
        '–',
        '-',
        '−',
        'Share\u2011based',
        '$9.2',
        '€8.8',
        '51%',
        '235,753,600',
        '(6.59)',
    ],
)
def test_evidence_characters_survive_normalization_exactly(value):
    # An em dash is a reported zero, parentheses are a reported negative, and a non-breaking
    # hyphen is part of a word. NFKC or an ASCII fold would rewrite every one of them.
    assert cell_text(value) == value


def test_collapse_does_not_decide_emptiness():
    # collapse is the whitespace rule; only cell_text judges a layout cell, so a caller that
    # needs the raw collapsed string can still see the zero-width run.
    assert collapse(' \u200b ') == '\u200b'
