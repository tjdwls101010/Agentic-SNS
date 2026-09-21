"""Turn one HTML table into a grid: span occupancy, table-wide column folding, canonical text.

The grid is the reading model for a SEC table. Nothing here decides which row is a header:
the measured filings declare none, and the one statement this model was designed against
stacks two half-year periods vertically, so any single column meaning fixed for the whole
table is wrong for half of it. What the grid supplies is the layout the reader can see.
"""


from output import SecError
from snapshot import cell_text

# Wider than any table a filing lays out; past this a span value is a typo rather than a layout,
# and expanding it would allocate a row of nothing per column.
MAX_COLUMNS = 4096

CELL_TAGS = ('td', 'th')
ROW_GROUP_TAGS = ('thead', 'tbody', 'tfoot')
SKIP_TAGS = frozenset({'script', 'style'})
SPACING_TAGS = frozenset({'div', 'p', 'br', 'li', 'tr'})


def _fail(message, fix):
    raise SecError('parse_failed', message, fix)


def _span(cell, name, lowest):
    raw = cell.get(name, '1')
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        _fail(f'A table cell declares {name}="{raw}", which is not a number.',
              'Read the original table; the span was not guessed at.')
    if value < lowest or value > MAX_COLUMNS:
        _fail(f'A table cell declares {name}={value}, outside the supported range.',
              'Read the original table; the span was not clamped to a usable value.')
    return value


def _parts_of(cell, table_ids, link_ids):
    """Split a cell into its own text and the child tables that interrupt it.

    A child table's strings stay in the child. Copying them up would make the parent report
    values it does not itself contain, and would count one phrase as two search hits.
    """
    parts, images, pending = [], [], []

    def flush():
        value = cell_text(''.join(pending))
        pending.clear()
        if value:
            parts.append({'kind': 'text', 'text': value})

    def walk(node):
        for child in node:
            tag = str(child.tag).lower() if isinstance(child.tag, str) else ''
            if tag == 'table':
                flush()
                parts.append({'kind': 'child_table', 'child_table_id': table_ids.get(child)})
                if child.tail:
                    pending.append(child.tail)
                continue
            if tag in SKIP_TAGS or not isinstance(child.tag, str):
                if child.tail:
                    pending.append(child.tail)
                continue
            if tag == 'img':
                identifier = link_ids.get(child)
                if identifier is not None:
                    images.append(identifier)
            if tag in SPACING_TAGS:
                pending.append(' ')
            if child.text:
                pending.append(child.text)
            walk(child)
            if tag in SPACING_TAGS:
                pending.append(' ')
            if child.tail:
                pending.append(child.tail)

    if cell.text:
        pending.append(cell.text)
    walk(cell)
    flush()
    return parts, images


def _place(node):
    """Walk the table's own rows and place each cell, honouring spans already in the way."""
    rows, groups = [], []
    for element in node.iterchildren():
        tag = str(element.tag).lower() if isinstance(element.tag, str) else ''
        if tag == 'tr':
            rows.append(element)
            groups.append(None)
        elif tag in ROW_GROUP_TAGS:
            for row in element.iterchildren():
                if isinstance(row.tag, str) and str(row.tag).lower() == 'tr':
                    rows.append(row)
                    groups.append(element)
    # A row outside any thead/tbody/tfoot belongs to one implicit group, so rowspan=0 stops
    # where that run of rows stops rather than at the end of the table.
    group_end = {}
    for index, group in enumerate(groups):
        group_end[index] = index
    for index in range(len(rows) - 1, -1, -1):
        if index + 1 < len(rows) and groups[index + 1] is groups[index]:
            group_end[index] = group_end[index + 1]

    occupied = {}
    placed = []
    for r, row in enumerate(rows):
        column = 0
        for cell in row:
            if not isinstance(cell.tag, str) or str(cell.tag).lower() not in CELL_TAGS:
                continue
            rowspan = _span(cell, 'rowspan', 0)
            colspan = _span(cell, 'colspan', 1)
            while occupied.get(column, -1) >= r:
                column += 1
            height = (group_end[r] - r + 1) if rowspan == 0 else rowspan
            last = r + height - 1
            if column + colspan > MAX_COLUMNS:
                _fail('A table row reaches beyond the supported column count.',
                      'Read the original table; no column was dropped to make it fit.')
            for c in range(column, column + colspan):
                if occupied.get(c, -1) >= r:
                    _fail('Two table cells claim the same position.',
                          'Read the original table; neither cell was moved aside or overwritten.')
                occupied[c] = last
            placed.append({'node': cell, 'row': r, 'column': column, 'rowspan': rowspan,
                           'colspan': colspan, 'effective_rows': height})
            column += colspan
    return rows, placed


def build_table(node, table_id, *, table_ids=None, link_ids=None, parent=None):
    """Return the stored record for one table: placement, folding, canonical text and spans."""
    table_ids = table_ids or {}
    link_ids = link_ids or {}
    rows, placed = _place(node)
    columns = max((c['column'] + c['colspan'] for c in placed), default=0)

    for cell in placed:
        parts, images = _parts_of(cell['node'], table_ids, link_ids)
        cell['parts'] = parts
        cell['images'] = images
        cell['has_text'] = any(part['kind'] == 'text' for part in parts)
        cell['reason'] = ('child_table' if any(p['kind'] == 'child_table' for p in parts)
                          else 'image' if images else None)

    # Folding is by where a cell starts, not by what a wide span covers: a heading spanning the
    # whole table must not keep alive the columns its own row leaves empty.
    kept = sorted({c['column'] for c in placed if c['has_text'] or c['reason']})
    position = {column: index for index, column in enumerate(kept)}

    origin = {(c['row'], c['column']): c for c in placed}
    pieces, ranges, cells, spans = [], [], [], []
    offset = 0
    for r in range(len(rows)):
        fields, field_parts = [], []
        for column in kept:
            cell = origin.get((r, column))
            if cell is None:
                fields.append('')
                field_parts.append(None)
                continue
            # A child table interrupts the cell; the boundary keeps the text on either side of it
            # from joining into a sentence the original never contained.
            text = ''.join(p['text'] if p['kind'] == 'text' else '\n' for p in cell['parts'])
            fields.append(text)
            field_parts.append(cell)
        while fields and not fields[-1]:
            fields.pop()
            field_parts.pop()
        line = '\t'.join(fields)
        cursor = offset
        for index, (field, cell) in enumerate(zip(fields, field_parts, strict=True)):
            if cell is not None:
                cell['text_start'], cell['text_end'] = cursor, cursor + len(field)
            cursor += len(field) + 1
        ranges.append([r, offset, offset + len(line)])
        pieces.append(line)
        offset += len(line) + 1

    text = '\n'.join(pieces)
    for cell in placed:
        start = cell.get('text_start')
        record = {'row': cell['row'], 'column': cell['column'],
                  'rowspan': cell['rowspan'], 'colspan': cell['colspan']}
        if start is None:
            # The cell starts in a folded column: it has no text and no image, so it owns no
            # canonical range, but its place and span stay on the record.
            record['text_start'] = record['text_end'] = ranges[cell['row']][1]
        else:
            record['text_start'], record['text_end'] = start, cell['text_end']
        tag = str(cell['node'].tag).lower()
        if tag == 'th':
            record['th'] = True
        for attribute in ('scope', 'headers'):
            if cell['node'].get(attribute):
                record[attribute] = cell['node'].get(attribute)
        if cell['reason']:
            record['nonempty_reason'] = cell['reason']
        if cell['images']:
            record['links'] = cell['images']
        if any(part['kind'] == 'child_table' for part in cell['parts']):
            detail, cursor = [], record['text_start']
            for part in cell['parts']:
                if part['kind'] == 'text':
                    detail.append({'kind': 'text', 'text_start': cursor, 'text_end': cursor + len(part['text'])})
                    cursor += len(part['text'])
                else:
                    detail.append({'kind': 'child_table', 'child_table_id': part['child_table_id']})
                    cursor += 1
            record['parts'] = detail
        cells.append(record)
        if cell['colspan'] != 1 or cell['rowspan'] != 1:
            covered = sum(1 for c in range(cell['column'], cell['column'] + cell['colspan']) if c in position)
            span = {'row': cell['row'], 'column': cell['column'],
                    'colspan': cell['colspan'], 'rowspan': cell['rowspan'], 'w': covered}
            if cell['rowspan'] != cell['effective_rows']:
                span['effective_rows'] = cell['effective_rows']
            spans.append(span)

    return {'table_id': table_id,
            'parent_table_id': parent[0] if parent else None,
            'parent_cell': {'row': parent[1], 'column': parent[2]} if parent else None,
            'original_rows': len(rows), 'original_columns': columns,
            'kept_columns': kept, 'row_ranges': ranges,
            'cells': cells, 'spans': spans, 'text': text}


def escape(value):
    return value.replace('\\', '\\\\').replace('|', '\\|').replace('\n', '\\n')


def row_text(table, row, fragments=None):
    """Render one grid row as `original-row-number | cell | cell …`.

    The escapes and the row number are display only: they are not in the canonical text and so
    never move a position.
    """
    start, end = next(((s, e) for r, s, e in table['row_ranges'] if r == row), (0, 0))
    fields = table['text'][start:end].split('\t') if end > start else []
    fields += [''] * (len(table['kept_columns']) - len(fields))
    if fragments:
        for index, value in fragments.items():
            fields[index] = value
    while fields and not fields[-1]:
        fields.pop()
    return '|'.join([str(row)] + [escape(field) for field in fields])


def render_rows(table, rows):
    return '\n'.join(row_text(table, row) for row in rows)
