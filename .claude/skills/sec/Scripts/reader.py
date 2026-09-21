"""Budgeted navigation over one immutable snapshot; no parsing or network access."""

import json
import re
from bisect import bisect_right
from urllib.parse import unquote

from grid import row_text
from output import SecError, measure
from snapshot import SNAPSHOT_VERSION
from store import digest

# Budget bounds: the host tool truncates Bash results around 30,000 characters, so the ceiling
# stays below that.
MIN_BUDGET, DEFAULT_BUDGET, MAX_BUDGET = 1024, 12000, 24000
CURSOR_VERSION = 4
NARROWING = {'outline': '--kind', 'find': 'a more specific query', 'read': '--position and --end',
             'table': '--rows', 'links': '--kind'}
OUTLINE_KINDS = ('toc', 'emphasis', 'table', 'anchor', 'internal_link')
DEFAULT_OUTLINE_KINDS = ('toc', 'emphasis', 'table')
# A table's opening rows are a convenience; the body is the work. Half of what is left after the
# body has made progress is the most they may take.
CONTEXT_SHARE = 0.5


def fingerprint(snapshot):
    # Ten characters: short enough to repeat on every item, wide enough that two snapshots in
    # one session differ.
    return snapshot.id[:10]


def position(snapshot, offset):
    block, inner = _locate(snapshot, offset)
    return f'{fingerprint(snapshot)}:{block}:{inner}'


def _starts(snapshot):
    starts, offset = [], 0
    for block in snapshot.data['blocks']:
        starts.append(offset)
        offset += len(block['text']) + 1
    starts.append(max(offset - 1, 0))
    return starts


def _canonical(snapshot):
    return '\n'.join(block['text'] for block in snapshot.data['blocks']), _starts(snapshot)


def _locate(snapshot, offset):
    starts = _starts(snapshot)
    blocks = snapshot.data['blocks']
    if offset >= starts[-1] and blocks:
        return len(blocks) - 1, offset - starts[len(blocks) - 1]
    index = max(0, bisect_right(starts[:-1], offset) - 1)
    return index, offset - starts[index]


def _offset(snapshot, value, default):
    if value is None:
        return default
    try:
        *identity, block, inner = str(value).split(':')
        block, inner = int(block), int(inner)
        blocks = snapshot.data['blocks']
        if identity not in ([fingerprint(snapshot)], [snapshot.id]) or block < 0 or inner < 0:
            raise ValueError
        if block > len(blocks) or (block == len(blocks) and inner):
            raise ValueError
        if block < len(blocks) and inner > len(blocks[block]['text']):
            raise ValueError
        starts = _starts(snapshot)
        return starts[block] + inner
    except (ValueError, AttributeError, IndexError):
        raise SecError('invalid_position', 'Position belongs to a different snapshot or is out of range.',
                       'Use a position this snapshot returned; positions start with its own fingerprint.'
                       ) from None


def _verify(snapshot, store):
    encoded = json.dumps(snapshot.data, sort_keys=True, ensure_ascii=False).encode()
    if digest(encoded) != snapshot.id:
        raise SecError('snapshot_changed', 'Snapshot data was changed after it was saved.',
                       'Reload the original snapshot or open the source again.')
    store.get(snapshot.id)
    store.get(snapshot.data['source']['sha256'])
    store.get(snapshot.data['dom'])


def _envelope(snapshot, operation):
    """Every field the finished page will carry, at its widest.

    The envelope is measured while the page is being filled, so a field added only at the end
    would let a page pass the check and then overflow when it is printed.
    """
    blocks = snapshot.data['blocks']
    envelope = {'operation': operation, 'snapshot_id': snapshot.id,
                'source_url': snapshot.data['source']['url'], 'status': snapshot.data['status'],
                'format': snapshot.data['format'],
                'known_extraction_limits': snapshot.data['known_extraction_limits'],
                'has_more': True, 'scope_complete': False, 'remaining_items': 99999999,
                'returned_chars': MAX_BUDGET, 'next_cursor': '0' * 64}
    if operation == 'read':
        envelope['next_position'] = (f'{fingerprint(snapshot)}:{max(len(blocks) - 1, 0)}:'
                                     f"{max((len(b['text']) for b in blocks), default=0)}")
    if operation == 'find':
        envelope['total_matches'] = 0
    return envelope


def _check_budget(budget):
    if not isinstance(budget, int) or not MIN_BUDGET <= budget <= MAX_BUDGET:
        raise SecError('invalid_budget', f'max-chars must be {MIN_BUDGET}..{MAX_BUDGET} characters.',
                       'Use the default or a value in this range.')


def _too_small(operation):
    return SecError('budget_too_small', 'This response cannot fit in the requested budget.',
                    f'Select less with {NARROWING[operation]}, or raise --max-chars up to {MAX_BUDGET}.')


def _query(snapshot, operation, options, budget, as_json):
    # The output mode changes where a page ends, so a cursor is bound to it as well.
    return {'version': CURSOR_VERSION, 'snapshot_version': SNAPSHOT_VERSION, 'operation': operation,
            'snapshot_id': snapshot.id, 'options': options, 'budget': budget, 'json': bool(as_json)}


def _paginate(snapshot, store, operation, options, items, cursor, budget, as_json, assemble,
              enrich=None):
    """Add items until one does not fit, splitting only when the page is otherwise empty.

    Deferring an item that does not fit keeps a split to the case where a single item is larger
    than a whole page; splitting greedily instead cuts mid-word on every page boundary.
    """
    _check_budget(budget)
    _verify(snapshot, store)
    query = _query(snapshot, operation, options, budget, as_json)
    state = store.resume(cursor, query) if cursor else {'index': 0, 'offset': 0}
    index, offset = state['index'], state['offset']
    taken = []
    while index < len(items):
        piece, length = items[index].take(offset)
        taken.append(piece)
        if measure(assemble(taken, index + 1 == len(items) and length is None), as_json) <= budget:
            index, offset = index + 1, 0
            continue
        taken.pop()
        if taken:
            break
        low, high = 0, items[index].size(offset)
        while low < high:
            middle = (low + high + 1) // 2
            piece, _ = items[index].take(offset, middle)
            if measure(assemble([piece], False), as_json) <= budget:
                low = middle
            else:
                high = middle - 1
        if not low:
            raise _too_small(operation)
        taken.append(items[index].take(offset, low)[0])
        offset += low
        break
    more = index < len(items)
    result = assemble(taken, not more)
    result['has_more'] = more
    result['scope_complete'] = not more
    result['remaining_items'] = len(items) - index
    result['next_cursor'] = store.save({'query': query, 'state': {'index': index, 'offset': offset}}) if more else None
    if enrich is not None:
        enrich(result, budget, as_json)
    result['returned_chars'] = measure(result, as_json)
    if result['returned_chars'] > budget:
        raise _too_small(operation)
    return result


class _Item:
    """One unit of output that can be returned whole or, when alone, cut short."""

    def __init__(self, record, text_key='text'):
        self.record, self.key = record, text_key

    def size(self, offset):
        return max(0, len(self.record.get(self.key) or '') - offset)

    def take(self, offset, limit=None):
        text = (self.record.get(self.key) or '')[offset:]
        cut = text if limit is None else text[:limit]
        piece = dict(self.record)
        if self.key in piece:
            piece[self.key] = cut
        if offset or len(cut) != len(text):
            piece['fragment'] = {'offset': offset, 'text_complete': len(cut) == len(text)}
        return piece, (None if len(cut) == len(text) else len(cut))


# --- outline --------------------------------------------------------------------------------


def outline(snapshot, store, *, kinds=DEFAULT_OUTLINE_KINDS, observations=False, in_tables=None,
            cursor=None, budget=DEFAULT_BUDGET, as_json=False):
    kinds = tuple(kinds)
    if not kinds or any(kind not in OUTLINE_KINDS for kind in kinds):
        raise SecError('invalid_argument', 'Unknown outline kind.',
                       'Use kinds from: ' + ', '.join(OUTLINE_KINDS) + '.')
    if in_tables not in (None, 'only', 'exclude'):
        raise SecError('invalid_argument', 'Unknown --in-tables selection.', 'Use only or exclude.')
    if in_tables == 'only' and not observations:
        # The navigation layer is defined as emphasis outside tables, so an empty result here
        # would read as "no emphasis inside tables" rather than as a contradiction.
        raise SecError('invalid_argument',
                       'The navigation layer is outside tables, so --in-tables only cannot apply to it.',
                       'Add --all to select from the observation layer, or drop --in-tables.')

    chosen = []
    for item in snapshot.data['outline']:
        if item['kind'] not in kinds:
            continue
        if item['kind'] == 'emphasis':
            if not observations and not item['navigation']:
                continue
            inside = 'table_id' in item
            if (in_tables == 'only' and not inside) or (in_tables == 'exclude' and inside):
                continue
        chosen.append(item)

    items = [_Item(entry) for entry in _group(snapshot, chosen)]
    options = {'kinds': sorted(kinds), 'observations': bool(observations), 'in_tables': in_tables}

    def assemble(taken, _complete):
        return dict(_envelope(snapshot, 'outline'), items=taken)

    return _paginate(snapshot, store, 'outline', options, items, cursor, budget, as_json, assemble)


def _group(snapshot, chosen):
    """Emphasis groups by phrase, keeping every place it occurs and that place's own evidence."""
    grouped, order = {}, []
    for item in chosen:
        entry = {key: value for key, value in item.items()
                 if key not in ('block', 'offset', 'signals', 'navigation', 'row', 'column', 'context_block')}
        entry['position'] = position(snapshot, _at(snapshot, item))
        if item['kind'] != 'emphasis':
            if item['kind'] == 'table':
                entry.pop('text', None)
            entry.pop('url', None) if item['kind'] == 'anchor' else _anchor(entry, snapshot)
            order.append(entry)
            continue
        place = {'position': entry.pop('position'), 'signals': item['signals']}
        for key in ('table_id', 'row'):
            if key in item:
                place[key] = item[key]
        key = ('emphasis', item['text'])
        if key not in grouped:
            grouped[key] = {'kind': 'emphasis', 'text': item['text'], 'occurrences': []}
            order.append(grouped[key])
        grouped[key]['occurrences'].append(place)
    return order


def _anchor(entry, snapshot):
    url = entry.get('url', '')
    source = snapshot.data['source']['url']
    if url.startswith(source + '#'):
        entry.pop('url')
        entry['anchor'] = unquote(url[len(source) + 1:])
    elif url == source:
        entry.pop('url')


def _at(snapshot, item):
    return _starts(snapshot)[item['block']] + item.get('offset', 0)


# --- find -----------------------------------------------------------------------------------


def find(snapshot, store, *, query, case_sensitive=False, cursor=None, budget=DEFAULT_BUDGET,
         as_json=False):
    if not query:
        raise SecError('invalid_query', 'Search text cannot be empty.', 'Provide a nonempty literal string.')
    text, _ = _canonical(snapshot)
    pattern = re.compile(re.escape(query), 0 if case_sensitive else re.IGNORECASE)
    matches = [(m.start(), m.end()) for m in pattern.finditer(text)]
    items = [_Item(_match(snapshot, text, start, end)) for start, end in matches]
    options = {'query': query, 'case_sensitive': bool(case_sensitive)}

    def assemble(taken, _complete):
        return dict(_envelope(snapshot, 'find'), items=taken, total_matches=len(matches))

    return _paginate(snapshot, store, 'find', options, items, cursor, budget, as_json, assemble)


def _match(snapshot, text, start, end):
    # 성진: 앞뒤 60/100자는 표 문맥의 대체물이 아니라 매치를 알아보기 위한 조각이다, 표 안 매치는 table_id·행·열이 그 일을 한다.
    item = {'position': position(snapshot, start), 'match_end': position(snapshot, end),
            'text': text[max(0, start - 60):end + 100]}
    first, last = _cell(snapshot, start), _cell(snapshot, max(start, end - 1))
    if first:
        item.update(table_id=first[0], row=first[1], column=first[2])
    if last and last != first:
        # A match that runs across cells, rows or tables says so rather than being reported as
        # one place it never wholly occupied.
        item['table_id_end'], item['row_end'], item['column_end'] = last
    return item


def _cell(snapshot, offset):
    block, inner = _locate(snapshot, offset)
    blocks = snapshot.data['blocks']
    if block >= len(blocks) or blocks[block]['kind'] != 'grid':
        return None
    table = next(t for t in snapshot.data['tables'] if t['table_id'] == blocks[block]['table_id'])
    cell = next((c for c in table['cells'] if c['text_start'] <= inner < c['text_end']), None)
    if cell is None:
        row = next((r for r, s, e in table['row_ranges'] if s <= inner <= e), None)
        return (table['table_id'], row, None) if row is not None else None
    return (table['table_id'], cell['row'], cell['column'])


# --- links ----------------------------------------------------------------------------------


def links(snapshot, store, *, kind=None, cursor=None, budget=DEFAULT_BUDGET, as_json=False):
    if kind not in (None, 'image', 'internal', 'external'):
        raise SecError('invalid_kind', 'Unknown link kind.', 'Use image, internal or external.')
    chosen = []
    for item in snapshot.data['links']:
        if kind is not None and item['kind'] != kind:
            continue
        entry = {key: value for key, value in item.items()
                 if key not in ('block', 'offset', 'context_block', 'id')}
        entry['position'] = position(snapshot, _at(snapshot, item))
        # Where the link sits and where it points are different places.
        entry['context_position'] = position(snapshot, _starts(snapshot)[item['context_block']])
        chosen.append(entry)
    items = [_Item(entry) for entry in chosen]

    def assemble(taken, _complete):
        return dict(_envelope(snapshot, 'links'), items=taken)

    return _paginate(snapshot, store, 'links', {'kind': kind}, items, cursor, budget, as_json, assemble)


# --- read -----------------------------------------------------------------------------------


def read(snapshot, store, *, position=None, end=None, cursor=None, budget=DEFAULT_BUDGET,
         as_json=False):
    start_offset = _offset(snapshot, position, 0)
    stop_offset = _offset(snapshot, end, _starts(snapshot)[-1] + 1)
    if stop_offset < start_offset:
        raise SecError('invalid_range', 'End precedes the start position.',
                       'Use an exclusive end after the start.')
    units = _units(snapshot, start_offset, stop_offset)
    options = {'position': position, 'end': end}
    _check_budget(budget)
    _verify(snapshot, store)
    query = _query(snapshot, 'read', options, budget, as_json)
    state = store.resume(cursor, query) if cursor else {'index': 0, 'offset': 0}
    index, offset = state['index'], state['offset']
    taken = []
    while index < len(units):
        unit = units[index]
        taken.append(unit.take(offset))
        if measure(_read_result(snapshot, taken, {}), as_json) <= budget:
            index, offset = index + 1, 0
            continue
        taken.pop()
        if taken:
            break
        low, high = 0, unit.size(offset)
        while low < high:
            middle = (low + high + 1) // 2
            if measure(_read_result(snapshot, [unit.take(offset, middle)], {}), as_json) <= budget:
                low = middle
            else:
                high = middle - 1
        if not low:
            raise _too_small('read')
        taken.append(unit.take(offset, low))
        offset += low
        break
    more = index < len(units)
    result = _read_result(snapshot, taken, _context(snapshot, taken, budget, as_json))
    _detail(snapshot, result, budget, as_json)
    result['has_more'] = more
    result['scope_complete'] = not more
    result['remaining_items'] = len(units) - index
    # next_position is always unread body: repeating a table's opening rows never moves it back.
    result['next_position'] = position_of(snapshot, units[index].start + offset) if more else None
    result['next_cursor'] = store.save({'query': query, 'state': {'index': index, 'offset': offset}}) if more else None
    result['returned_chars'] = measure(result, as_json)
    if result['returned_chars'] > budget:
        raise _too_small('read')
    return result


def position_of(snapshot, offset):
    return position(snapshot, offset)


class _Prose:
    kind = 'grid_none'

    def __init__(self, snapshot, block, text, start):
        self.snapshot, self.block, self.text, self.start = snapshot, block, text, start

    def size(self, offset):
        return max(0, len(self.text) - offset)

    def take(self, offset, limit=None):
        body = self.text[offset:] if limit is None else self.text[offset:offset + limit]
        return {'kind': 'text', 'position': position(self.snapshot, self.start + offset),
                'text': body, 'block': self.block,
                'complete': offset + len(body) == len(self.text)}


class _Row:
    def __init__(self, snapshot, table, row, start, end):
        self.snapshot, self.table, self.row = snapshot, table, row
        self.start, self.end = start, end

    def size(self, offset):
        return max(0, (self.end - self.start) - offset)

    def take(self, offset, limit=None):
        span = self.end - self.start
        length = span - offset if limit is None else min(limit, span - offset)
        return {'kind': 'row', 'table': self.table, 'row': self.row,
                'position': position(self.snapshot, self.start + offset),
                'offset': offset, 'length': length, 'complete': offset == 0 and length == span}


def _units(snapshot, start_offset, stop_offset):
    starts = _starts(snapshot)
    units = []
    for index, block in enumerate(snapshot.data['blocks']):
        low, high = max(starts[index], start_offset), min(starts[index] + len(block['text']), stop_offset)
        if high <= low and not (low == high == start_offset and start_offset < stop_offset):
            continue
        if block['kind'] != 'grid':
            units.append(_Prose(snapshot, index, block['text'][low - starts[index]:high - starts[index]], low))
            continue
        table = next(t for t in snapshot.data['tables'] if t['table_id'] == block['table_id'])
        for row, begin, finish in table['row_ranges']:
            first, last = max(starts[index] + begin, low), min(starts[index] + finish, high)
            if last < first:
                continue
            units.append(_Row(snapshot, table, row, first, last))
    return units


def _render_row(table, row, offset, length):
    """Render one grid row, cut to the characters this page actually covers."""
    begin, finish = table['row_ranges'][row][1:]
    if offset == 0 and length >= finish - begin:
        return row_text(table, row)
    # Every column starts empty: overriding only the columns this page reaches would leave the
    # others at full length, so a one-character page still printed the whole row.
    fields = dict.fromkeys(range(len(table['kept_columns'])), '')
    cursor = begin + offset
    for cell in table['cells']:
        if cell['text_end'] <= cursor or cell['text_start'] >= cursor + length:
            continue
        column = table['kept_columns'].index(cell['column']) if cell['column'] in table['kept_columns'] else None
        if column is None:
            continue
        low = max(cell['text_start'], cursor) - cell['text_start']
        high = min(cell['text_end'], cursor + length) - cell['text_start']
        whole = table['text'][cell['text_start']:cell['text_end']]
        fields[column] = whole[low:high]
    return row_text(table, row, fields) + '  …'


def _read_result(snapshot, taken, context):
    context = context or {}
    segments, current = [], None
    for piece in taken:
        if piece['kind'] == 'text':
            current = None
            segments.append({'kind': 'text', 'position': piece['position'], 'text': piece['text'],
                             'text_complete': piece['complete']})
            continue
        table = piece['table']
        if current is None or current['table_id'] != table['table_id']:
            current = _segment(snapshot, table, piece['position'])
            segments.append(current)
        current['rows'].append({'row': piece['row'], 'text': _render_row(
            table, piece['row'], piece['offset'], piece['length']),
            'row_complete': piece['complete']})
    for segment in segments:
        if segment['kind'] != 'grid' or not segment['rows'] or segment['rows'][0]['row'] == 0:
            continue
        # Saying that a table was entered partway through is part of the body, not a convenience:
        # a page that quietly omits it reads as if the table began where the page did.
        table = next(t for t in snapshot.data['tables'] if t['table_id'] == segment['table_id'])
        segment['context_rows'] = []
        segment['context_truncated'] = True
        segment['context_next_position'] = position(
            snapshot, _starts(snapshot)[table['block']] + table['row_ranges'][0][1])
        opening = context.get(segment['table_id'])
        if opening is None:
            continue
        segment['context_rows'], segment['context_truncated'], following = opening
        if following is None:
            segment.pop('context_next_position', None)
        else:
            segment['context_next_position'] = following
    return dict(_envelope(snapshot, 'read'), segments=segments)


def _segment(snapshot, table, at):
    """A grid segment's identity. What it measures and what merges in it are added if they fit.

    A field with nothing in it is left out rather than printed as null: those lines are what a
    small budget was being spent on, and a table that is not nested has no parent to report.
    """
    segment = {'kind': 'grid', 'position': at, 'table_id': table['table_id'],
               'original_rows': table['original_rows'], 'kept_columns': table['kept_columns'],
               'rows': []}
    if table['parent_table_id']:
        segment['parent_table_id'] = table['parent_table_id']
        segment['parent_cell'] = table['parent_cell']
    return segment


def _detail(snapshot, result, budget, as_json):
    """Add each grid's framing and merge list while the budget allows, first segment first.

    A wide table's spans and its surrounding prose together run to several hundred characters.
    Treating them as compulsory made the smallest allowed budget refuse the page outright,
    part way through a document, rather than returning rows and continuing.
    """
    tables = {table['table_id']: table for table in snapshot.data['tables']}
    for segment in result['segments']:
        if segment['kind'] != 'grid':
            continue
        table = tables[segment['table_id']]
        for key, value in (('caption', table['caption']), ('context', table['context_blocks'][:1]),
                           ('spans', table['spans'])):
            if not value:
                continue
            segment[key] = value
            if measure(result, as_json) > budget:
                segment.pop(key)


def _context(snapshot, taken, budget, as_json):
    """Carry a table's opening rows when the page starts partway into it.

    Never a reason to fail: the body is the work and the opening rows are a convenience, so
    whatever fits goes in and the rest is reported as truncated with a position to continue from.
    """
    added = {}
    for piece in taken:
        if piece['kind'] != 'row' or piece['row'] == 0:
            continue
        table = piece['table']
        if table['table_id'] in added:
            continue
        if any(other['kind'] == 'row' and other['table'] is table and other['row'] < piece['row']
               for other in taken):
            continue
        # Sequential, not shared out: reading order is document order, so the table met first
        # takes its share and a later one on the same page may get none.
        floor = measure(_read_result(snapshot, taken, added), as_json)
        ceiling = floor + int(max(0, budget - floor) * CONTEXT_SHARE)
        chosen = None
        for count in range(piece['row'] + 1):
            rows = [{'row': row, 'text': row_text(table, row)} for row in range(count)]
            truncated = count < piece['row']
            following = (position(snapshot,
                                  _starts(snapshot)[table['block']] + table['row_ranges'][count][1])
                         if truncated else None)
            trial = dict(added)
            trial[table['table_id']] = (rows, truncated, following)
            # Even saying that the opening rows were left out costs output, so that statement
            # has to fit too. Where it does not, the page carries body alone.
            if measure(_read_result(snapshot, taken, trial), as_json) > ceiling:
                break
            chosen = (rows, truncated, following)
        if chosen is not None:
            added[table['table_id']] = chosen
    return added


# --- table ----------------------------------------------------------------------------------


def table(snapshot, store, *, table_id, rows=None, cursor=None, budget=DEFAULT_BUDGET, as_json=False):
    selected = next((t for t in snapshot.data['tables'] if t['table_id'] == table_id), None)
    if selected is None:
        raise SecError('invalid_table', 'Table identifier is not in this snapshot.',
                       'Use table_id from open or outline output.')
    last = max(selected['original_rows'] - 1, 0)
    span = re.fullmatch(r'(\d+)(?:-(\d+))?', rows or '')
    first, final = (int(span[1]), int(span[2] or span[1])) if span else (0, last)
    if (rows and not span) or first > final or final > last:
        raise SecError('invalid_argument', 'Row range is outside this table.',
                       f'Use rows within 0-{last}, e.g. --rows 2-5.')
    items = [_Item({'row': row, 'text': row_text(selected, row)}) for row in range(first, final + 1)]
    options = {'table_id': table_id, 'rows': rows}
    framing = _framing(snapshot, selected)

    def assemble(taken, _complete):
        body = dict(_segment(snapshot, selected, position(snapshot, _starts(snapshot)[selected['block']])),
                    rows=[{'row': piece['row'], 'text': piece['text'],
                           'row_complete': 'fragment' not in piece} for piece in taken])
        if framing['positions']:
            body['context_position'] = framing['positions']
        return dict(_envelope(snapshot, 'table'), table=body)

    def enrich(result, allowance, as_json_mode):
        """Attach what says where this table sits, with the budget the rows left over.

        The rows are the work. Making the caption and footnotes compulsory meant that a table
        whose framing was long refused the smallest allowed budget outright instead of returning
        rows and a position to read the framing from.
        """
        body = result['table']
        if body['rows'] and body['rows'][0]['row'] != first:
            return
        added = []
        for key in ('caption', 'context', 'footnotes'):
            if not framing[key]:
                continue
            body[key] = framing[key]
            if measure(result, as_json_mode) > allowance:
                body.pop(key)
            else:
                added.append(key)
        if all(key in added for key in ('caption', 'context', 'footnotes') if framing[key]):
            body.pop('context_position', None)

    return _paginate(snapshot, store, 'table', options, items, cursor, budget, as_json, assemble, enrich)


def _framing(snapshot, selected):
    starts = _starts(snapshot)
    return {'context': selected['context_blocks'], 'caption': selected['caption'],
            'footnotes': selected['footnotes'],
            'positions': [position(snapshot, starts[note['block']])
                          for note in [*selected['context_blocks'], *selected['footnotes']]
                          if note.get('block') is not None]}
