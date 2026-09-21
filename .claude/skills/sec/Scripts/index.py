"""Read the attachment table off a SEC filing index page."""

import re
from urllib.parse import urljoin

from output import SecError
from snapshot import cell_text

# The index page names its own columns, so the reader matches by name. Matching by position
# would misread any filing index that orders or omits a column differently, and an index with
# no Size column at all has to report no size rather than a zero.
COLUMNS = {'seq': 'sequence_number', 'description': 'description', 'document': 'document',
           'type': 'document_type', 'size': 'size'}
FIELDS = ('sequence_number', 'document', 'description', 'document_type', 'size', 'url')


def _fail(message):
    raise SecError('parse_failed', message,
                   'Read the original SEC filing index and verify its attachment rows.')


def _children(node, *tags):
    """Direct rows and cells only, so a table nested inside a cell adds no rows of its own."""
    found = []
    for child in node.iterchildren():
        tag = str(child.tag).lower() if isinstance(child.tag, str) else ''
        if tag in tags:
            found.append(child)
        elif tag in ('thead', 'tbody', 'tfoot'):
            found.extend(_children(child, *tags))
    return found


def attachment_rows(root, base_url):
    """Return every attachment row of every attachment table, in page order."""
    from transport import validate_url

    tables = root.xpath('//table[contains(concat(" ", normalize-space(@class), " "), " tableFile ")]')
    if not tables:
        _fail('The response does not contain a SEC filing document table.')
    rows = []
    for table in tables:
        all_rows = _children(table, 'tr')
        header = next((row for row in all_rows if _children(row, 'th')), None)
        if header is None:
            _fail('A SEC attachment table has no header row naming its columns.')
        names = [cell_text(''.join(cell.itertext())).casefold() for cell in _children(header, 'th')]
        places = {COLUMNS[name]: index for index, name in enumerate(names) if name in COLUMNS}
        if 'document' not in places:
            _fail('A SEC attachment table has no Document column.')
        for row in all_rows:
            if row is header:
                continue
            cells = _children(row, 'td', 'th')
            if not cells:
                continue
            if len(cells) != len(names):
                # An extra cell shifts every field after it, so the row comes back with another
                # column's value under the wrong name rather than failing.
                _fail('A SEC attachment row does not have one cell per column of its table.')
            rows.append(_row(cells, places, base_url, validate_url))
    return rows


def _row(cells, places, base_url, validate_url):
    def value(name):
        index = places.get(name)
        return cell_text(''.join(cells[index].itertext())) if index is not None else ''

    link = cells[places['document']].xpath('.//a[@href]')
    if not link:
        _fail('A SEC attachment row has no document link.')
    # The Document cell carries an iXBRL badge beside the name, so the filename comes from the
    # link. validate_url resolves the /ix?doc= viewer to the document it is showing.
    url = validate_url(urljoin(base_url, link[0].get('href')))
    size = value('size')
    record = {'sequence_number': value('sequence_number') or None,
              'document': url.rsplit('/', 1)[-1],
              'description': value('description') or None,
              'document_type': value('document_type') or None,
              'size': int(size) if re.fullmatch(r'\d+', size or '') else None,
              'url': url}
    if places.get('size') is not None and size and record['size'] is None:
        _fail('A SEC attachment row declares a size that is not a number.')
    return record
