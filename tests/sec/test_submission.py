"""Document boundaries inside a SEC complete submission text file."""

import gzip
import json
import re
from pathlib import Path

import pytest
from output import SecError
from submission import split_documents

FIXTURES = Path(__file__).parent / 'fixtures'


def original(directory, name):
    metadata = json.loads((FIXTURES / directory / 'provenance.json').read_text())[name]
    raw = (FIXTURES / directory / metadata.get('storage', name)).read_bytes()
    body = gzip.decompress(raw) if metadata.get('compression') == 'gzip' else raw
    return body.decode('latin-1')


# --- the 1995 submission whose documents have no filename -------------------------------------


def test_a_document_with_no_filename_is_still_a_document():
    # Requiring <FILENAME> breaks every historical filing at once: neither document in this 1995
    # submission declares one, and the SDK returned an empty string for both.
    documents = split_documents(original('documents', 'old.txt'))
    assert [(d['sequence'], d['document_type'], d['filename']) for d in documents] == [
        ('1', '24F-2NT', None), ('2', 'EX-99.11', None),
    ]


@pytest.mark.parametrize(('directory', 'name'), [('documents', 'old.txt'), ('holdout', 'apple-1996.txt')])
def test_the_recovered_pieces_add_back_up_to_the_original(directory, name):
    text = original(directory, name)
    documents = split_documents(text)
    pieces, cursor = [], 0
    for document in documents:
        pieces.append(text[cursor:document['start']])
        pieces.append(text[document['start']:document['end']])
        cursor = document['end']
    pieces.append(text[cursor:])
    assert ''.join(pieces) == text
    for document in documents:
        assert text[document['text_start']:document['text_end']] == document['text']


def test_every_document_of_a_seven_document_submission_is_recovered():
    # Apple's 1996 10-K: three exhibits share the type EX-10, so keying by type collapses them.
    documents = split_documents(original('holdout', 'apple-1996.txt'))
    assert [(d['sequence'], d['document_type']) for d in documents] == [
        ('1', '10-K'), ('2', 'EX-10'), ('3', 'EX-10'), ('4', 'EX-10'),
        ('5', 'EX-11'), ('6', 'EX-21'), ('7', 'EX-27'),
    ]
    assert [d['description'] for d in documents[:6]] == [None] * 6
    assert documents[6]['description'] == 'ART. 5 FDS FOR FY95 FORM 10-K'
    openings = [re.sub(r'\s+', ' ', d['text'].strip())[:40] for d in documents]
    assert openings == [
        '_' * 40,
        'EXHIBIT 10.A.5 APPLE COMPUTER, INC. 1990',
        'EXHIBIT 10.A.6 APPLE COMPUTER, INC. EMPL',
        'EXHIBIT 10.A.40 August 19, 1996 Mr. Gera',
        '<TABLE> <CAPTION> EXHIBIT 11 APPLE COMPU',
        'EXHIBIT 21 SUBSIDIARIES OF APPLE COMPUTE',
        '<TABLE> <S> <C> <ARTICLE> 5 <MULTIPLIER>',
    ]
    assert [len(d['text']) for d in documents] == [196627, 36762, 22671, 10293, 1592, 538, 1034]


def test_the_wrapper_around_the_documents_is_kept_rather_than_discarded():
    text = original('holdout', 'apple-1996.txt')
    documents = split_documents(text)
    assert text[:documents[0]['start']].startswith('-----BEGIN PRIVACY-ENHANCED MESSAGE-----')
    assert text[documents[-1]['end']:].strip().endswith('-----END PRIVACY-ENHANCED MESSAGE-----')


# --- where metadata may be read from ----------------------------------------------------------


def test_metadata_is_read_before_the_text_and_never_inside_it():
    # Two of Apple's 1996 exhibits contain <TABLE>, <S>, <C> and <ARTICLE> inside <TEXT>, and the
    # last one ends on <EPS-DILUTED>. None of those is submission metadata.
    body = ('<DOCUMENT>\n<TYPE>EX-27\n<SEQUENCE>7\n<TEXT>\n'
            '<TABLE>\n<TYPE>NOT-METADATA\n<SEQUENCE>99\n<DESCRIPTION>nor this\n</TABLE>\n'
            '</TEXT>\n</DOCUMENT>\n')
    document, = split_documents(body)
    assert document['document_type'] == 'EX-27' and document['sequence'] == '7'
    assert document['description'] is None
    assert 'NOT-METADATA' in document['text']


def test_a_missing_sequence_does_not_let_one_document_overwrite_another():
    body = ('<DOCUMENT>\n<TYPE>EX-1\n<TEXT>\nfirst\n</TEXT>\n</DOCUMENT>\n'
            '<DOCUMENT>\n<TYPE>EX-2\n<TEXT>\nsecond\n</TEXT>\n</DOCUMENT>\n')
    documents = split_documents(body)
    assert [d['sequence'] for d in documents] == [None, None]
    assert [d['text'].strip() for d in documents] == ['first', 'second']


def test_a_repeated_sequence_keeps_both_documents():
    body = ('<DOCUMENT>\n<TYPE>EX-1\n<SEQUENCE>2\n<TEXT>\nfirst\n</TEXT>\n</DOCUMENT>\n'
            '<DOCUMENT>\n<TYPE>EX-2\n<SEQUENCE>2\n<TEXT>\nsecond\n</TEXT>\n</DOCUMENT>\n')
    documents = split_documents(body)
    assert [d['document_type'] for d in documents] == ['EX-1', 'EX-2']


# --- what must not be recovered silently --------------------------------------------------------


def test_a_document_that_never_closes_is_an_error_rather_than_a_silent_truncation():
    with pytest.raises(SecError) as error:
        split_documents('<DOCUMENT>\n<TYPE>EX-1\n<TEXT>\nbody with no end\n')
    assert error.value.code == 'parse_failed'


def test_a_submission_with_no_document_boundary_is_an_error():
    with pytest.raises(SecError) as error:
        split_documents('just some text\n')
    assert error.value.code == 'parse_failed'


def test_a_closing_tag_pair_appearing_inside_text_is_reported_rather_than_guessed_at():
    # A body that itself contains the closing sequence cannot be told apart from a real end by a
    # line-oriented reader, so the reader says so instead of choosing one reading.
    body = ('<DOCUMENT>\n<TYPE>EX-1\n<TEXT>\nquoted example:\n</TEXT>\n</DOCUMENT>\n'
            'still inside the first document\n</TEXT>\n</DOCUMENT>\n')
    with pytest.raises(SecError) as error:
        split_documents(body)
    assert error.value.code == 'parse_failed'


def test_offsets_are_character_offsets_into_the_decoded_text():
    # A byte offset used as a character offset drifts from the first multi-byte character on.
    body = '<DOCUMENT>\n<TYPE>EX-1\n<TEXT>\nvalue €8.8 billion\n</TEXT>\n</DOCUMENT>\n'
    document, = split_documents(body)
    assert body[document['text_start']:document['text_end']] == document['text']
    assert '€8.8 billion' in document['text']


# --- what the independent review of these parsers found -------------------------------------


def test_the_body_keeps_the_blank_lines_it_opens_with():
    # The <TEXT> matcher's \s* ran past the end of its own line and ate the indentation the
    # document opens with. In Apple's 1996 filing every exhibit begins with blank lines and tabs.
    text = original('holdout', 'apple-1996.txt')
    documents = split_documents(text)
    assert documents[1]['text'].startswith('\n\t\t\t\t\t\t\t\t\n\t\tEXHIBIT 10.A.5')
    for document in documents:
        assert text[document['text_start']:document['text_end']] == document['text']


def test_a_closing_pair_inside_one_document_is_reported_rather_than_split_on():
    # The check only looked after the last document, so an ambiguous body followed by a real
    # second document was accepted and the first document lost everything after the false end.
    body = ('<DOCUMENT>\n<TYPE>EX-1\n<TEXT>\nbefore\n</TEXT>\n</DOCUMENT>\n'
            'still the first document\n</TEXT>\n</DOCUMENT>\n'
            '<DOCUMENT>\n<TYPE>EX-2\n<TEXT>\nsecond\n</TEXT>\n</DOCUMENT>\n')
    with pytest.raises(SecError) as error:
        split_documents(body)
    assert error.value.code == 'parse_failed'


def test_carriage_returns_do_not_hide_a_boundary():
    body = '<DOCUMENT>\r\n<TYPE>EX-1\r\n<TEXT>\r\nbody\r\n</TEXT>\r\n</DOCUMENT>\r\n'
    document, = split_documents(body)
    assert document['document_type'] == 'EX-1'
    assert 'body' in document['text']
