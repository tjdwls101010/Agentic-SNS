"""Find the document boundaries inside a SEC complete submission text file.

A submission is not XML and not HTML: it is a line-oriented SGML envelope where `<DOCUMENT>`,
`<TEXT>` and their closers each stand alone on a line, and everything between `<TEXT>` and
`</TEXT>` is the document's own bytes — which in these filings routinely include `<TABLE>`,
`<ARTICLE>` and other angle-bracket tokens that are not submission metadata.
"""

import re

from output import SecError

# Submission metadata, read only in the header before <TEXT>. A filing from 1995 declares none
# of these except TYPE and SEQUENCE, and requiring any of them rejects the filing outright.
FIELDS = {'TYPE': 'document_type', 'SEQUENCE': 'sequence', 'FILENAME': 'filename',
          'DESCRIPTION': 'description'}
FIELD = re.compile(r'^<([A-Z][A-Z0-9-]*)>(.*)$')
# A tag that stands alone on its line, and nothing past the end of that line. Matching trailing
# whitespace with \s* runs on through blank lines, which ate the indentation every exhibit in a
# 1996 filing opens with.
ALONE = {name: re.compile(rf'^<{name}>[^\S\r\n]*\r?$', re.MULTILINE)
         for name in ('DOCUMENT', '/DOCUMENT', 'TEXT', '/TEXT')}


def _fail(message, fix='Read the original submission text file; no document was reconstructed by guessing.'):
    raise SecError('parse_failed', message, fix)


def split_documents(text):
    """Return each `<DOCUMENT>` in submission order, with its header fields and its own text.

    Offsets are character offsets into `text` as decoded. Using byte offsets here would drift
    from the first multi-byte character onward and cite the wrong passage from there on.
    """
    documents = []
    position = 0
    starts = [match.start() for match in ALONE['DOCUMENT'].finditer(text)]
    if not starts:
        _fail('No <DOCUMENT> boundary was found in this submission text file.')
    for start in starts:
        if start < position:
            _fail('A <DOCUMENT> boundary was found inside another document.')
        document, position = _one(text, start)
        documents.append(document)
    # Every gap between documents, not only the tail: a body that repeats the closing sequence
    # and is then followed by a real document used to pass, with the first document truncated at
    # the false end. A line-oriented reader cannot tell the two apart, so it says so rather than
    # choosing one reading.
    edges = [(0, documents[0]['start'])] if documents else []
    edges += [(documents[i]['end'], documents[i + 1]['start']) for i in range(len(documents) - 1)]
    edges.append((documents[-1]['end'], len(text)) if documents else (0, len(text)))
    for low, high in edges:
        gap = text[low:high]
        if ALONE['/DOCUMENT'].search(gap) or ALONE['/TEXT'].search(gap):
            _fail('A closing document tag appears outside any open document.')
    return documents


def _one(text, start):
    header_end = ALONE['TEXT'].search(text, start)
    close = ALONE['/DOCUMENT'].search(text, start)
    if header_end is None or close is None or header_end.start() > close.start():
        _fail('A <DOCUMENT> in this submission is not closed, or has no <TEXT> body.')
    body_end = ALONE['/TEXT'].search(text, header_end.end())
    if body_end is None or body_end.start() > close.start():
        _fail('A document body is not closed by </TEXT> before its </DOCUMENT>.')

    # The body begins after the newline that ends the <TEXT> line, and ends before the newline
    # that begins the </TEXT> line.
    opening = header_end.end() + 1 if text[header_end.end():header_end.end() + 1] == '\n' else header_end.end()
    record = {'start': start, 'end': close.end(),
              'text_start': opening, 'text_end': body_end.start()}
    record['text'] = text[record['text_start']:record['text_end']]
    for name in FIELDS.values():
        record[name] = None
    for line in text[start:header_end.start()].splitlines():
        field = FIELD.match(line)
        if field and field[1] in FIELDS:
            value = field[2].strip()
            record[FIELDS[field[1]]] = value or None
    return record, close.end()
