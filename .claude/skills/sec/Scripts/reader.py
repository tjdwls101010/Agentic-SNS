"""Budgeted navigation over one immutable snapshot; no parsing or network access."""
import json
import re
from bisect import bisect_right
from urllib.parse import unquote

from output import SecError
from store import digest


def position(snapshot, block, offset=0):
    # The snapshot argument already names the copy; positions carry only block:offset.
    return f'{block}:{offset}'


def _position(snapshot, value, default):
    if value is None:
        return default
    try:
        *sid, block, offset = value.split(':')
        block, offset = int(block), int(offset)
        if sid not in ([], [snapshot.id]) or block < 0 or offset < 0:
            raise ValueError
        blocks = snapshot.data['blocks']
        if block > len(blocks) or (block == len(blocks) and offset) or (block < len(blocks) and offset > len(blocks[block]['text'])):
            raise ValueError
        return block, offset
    except (ValueError, AttributeError):
        raise SecError('invalid_position', 'Position belongs to a different snapshot or is out of range.', 'Use a position returned for this snapshot.') from None


# Budget bounds: the host tool truncates Bash results around 30,000 characters, so the ceiling stays below that.
MIN_BUDGET, DEFAULT_BUDGET, MAX_BUDGET = 1024, 12000, 24000
NARROWING = {'outline': '--kind', 'find': 'a more specific query', 'read': '--position and --end',
             'table': '--rows', 'links': '--kind'}
OUTLINE_KINDS = ('toc', 'heading', 'table', 'anchor', 'internal_link')
DEFAULT_OUTLINE_KINDS = ('toc', 'heading', 'table')
# Fields the model acts on; block bookkeeping stays inside the position string.
INTERNAL = ('block', 'offset', 'text_offset', 'text_complete', 'context_block', 'target_resolved')


def _anchor_or_url(item, source_url):
    url = item.get('url', '')
    if url.startswith(source_url + '#'):
        return {'anchor': unquote(url[len(source_url) + 1:])}
    return {'url': url} if url else {}


def _prose(snapshot):
    # In XML the path and attributes are the evidence; everywhere else the text carries its own structure.
    return snapshot.data['format'] != 'xml'


def _public(operation, item, source_url, prose=True):
    if operation == 'table':
        # A cell keeps only what distinguishes it: place, span beyond one, header role, text and its position.
        public = {k: v for k, v in item.items() if k in ('kind', 'row', 'column', 'text', 'position', 'scope', 'headers') and v not in ('', None)}
        public.update({k: item[k] for k in ('colspan', 'rowspan') if item.get(k, 1) != 1})
        if item.get('header'):
            public['header'] = True
        if item.get('text_complete') is False:
            public['text_complete'] = False
        public.update(_anchor_or_url(item, source_url))
        return public
    public = {k: v for k, v in item.items() if k not in INTERNAL and v != ''}
    if operation == 'read':
        # The separator between blocks belongs to the joined stream, not to the value at this path.
        public['text'] = public.get('text', '').removesuffix('\n')
    if operation == 'read' and prose:
        public.pop('text', None)
    if operation == 'outline':
        public.pop('context_position', None)
    if item.get('kind') in ('table', 'anchor'):
        public.pop('text', None) if item['kind'] == 'table' else None
        public.pop('url', None)
    elif operation != 'links' and 'url' in public:
        # The envelope carries source_url once; an item names only the anchor observed in the original DOM.
        url = public.pop('url')
        if url.startswith(source_url + '#'):
            public['anchor'] = unquote(url[len(source_url) + 1:])
    if operation == 'links' and 'target_resolved' in item:
        public['target_resolved'] = item['target_resolved']
    return public


def _assemble_table(result):
    # Context, caption and footnotes lead the record stream, so they arrive with the first rows and then page like them.
    table = {k: v for k, v in result.items() if k != 'items'}
    rows = []
    for item in result['items']:
        kind = item.pop('kind', 'cell')
        if kind in ('context', 'caption', 'footnote'):
            note = {k: v for k, v in item.items() if k in ('text', 'anchor', 'url', 'text_complete')}
            if kind == 'caption':
                table['caption'] = note['text']
            elif kind == 'context':
                table.setdefault('context', []).append(note['text'])
            else:
                table.setdefault('footnotes', []).append(note)
            continue
        row = next((r for r in rows if r['row'] == item['row']), None)
        if row is None:
            row = {'row': item['row'], 'cells': []}
            if 'position' in item:
                row['position'] = item['position']
            rows.append(row)
        item.pop('row')
        item.pop('position', None)
        if kind == 'cell':
            row['cells'].append(item)
        else:
            cell = next((c for c in row['cells'] if c['column'] == item['column']), None)
            link = {'kind': kind, **{k: v for k, v in item.items() if k in ('text', 'anchor', 'url')}}
            if cell is None:
                row['cells'].append({'column': item['column'], 'links': [link]})
            else:
                cell.setdefault('links', []).append(link)
    for row in rows:
        # A row is a header row only when every cell is one; a mixed row keeps the mark on the cell.
        if row['cells'] and all(cell.get('header') for cell in row['cells']):
            row['header'] = True
            for cell in row['cells']:
                cell.pop('header')
    table['rows'] = rows
    return table


def _page(snapshot, store, operation, options, items, cursor, budget, finish=lambda result: result):
    if not isinstance(budget, int) or not MIN_BUDGET <= budget <= MAX_BUDGET:
        raise SecError('invalid_budget', f'max-chars must be {MIN_BUDGET}..{MAX_BUDGET} characters.', 'Use the default or a value in this range.')
    query = {'version': 3, 'operation': operation, 'snapshot_id': snapshot.id, 'options': options, 'budget': budget}
    # Validate saved bytes on every public read, including callers holding a snapshot object.
    encoded = json.dumps(snapshot.data, sort_keys=True, ensure_ascii=False).encode()
    if digest(encoded) != snapshot.id:
        raise SecError('snapshot_changed', 'Snapshot data was changed after it was saved.', 'Reload the original snapshot or open the source again.')
    store.get(snapshot.id)
    store.get(snapshot.data['source']['sha256'])
    store.get(snapshot.data['dom'])
    state = store.resume(cursor, query) if cursor else {'index': 0, 'offset': 0}
    index, offset = state['index'], state['offset']
    result = {'snapshot_id': snapshot.id, 'items': [], 'next_cursor': '0' * 64, 'has_more': True,
              'scope_complete': False, 'remaining_items': len(items), 'returned_chars': budget, 'extraction_complete': snapshot.data['extraction_complete'],
              'source_url': snapshot.data['source']['url'], 'status': snapshot.data['status']}
    prose = _prose(snapshot)
    if operation == 'read':
        if prose:
            result['text'] = ''
        result['next_position'] = position(snapshot, len(snapshot.data['blocks']), max((len(b['text']) for b in snapshot.data['blocks']), default=0))

    def size():
        return len(json.dumps(finish(json.loads(json.dumps(result))), ensure_ascii=False, indent=2)) + 1

    while index < len(items):
        original = items[index]
        text = original.get('text', '')
        remaining = text[offset:]
        item = dict(original, text=remaining, text_offset=offset, text_complete=True)
        if 'block' in original:
            item['position'] = position(snapshot, original['block'], original.get('offset', 0) + (offset if operation == 'read' else 0))
        if 'context_block' in original:
            item['context_position'] = position(snapshot, original['context_block'], 0)
        public = _public(operation, item, snapshot.data['source']['url'], prose)
        result['items'].append(public)
        prefix = result.get('text', '')
        if operation == 'read' and prose:
            result['text'] = prefix + remaining
        if size() > budget:
            lo, hi = 0, len(remaining)
            if 'text' in public:
                public['text_complete'] = False
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if 'text' in public:
                    public['text'] = remaining[:mid]
                if operation == 'read' and prose:
                    result['text'] = prefix + remaining[:mid]
                if size() <= budget:
                    lo = mid
                else:
                    hi = mid - 1
            if lo == 0:
                result['items'].pop()
                if operation == 'read' and prose:
                    result['text'] = prefix
                if not result['items']:
                    raise SecError('budget_too_small', 'This response cannot fit in the requested budget.',
                                   f"Select less with {NARROWING[operation]}, or raise --max-chars up to {MAX_BUDGET}.")
                break
            if 'text' in public:
                public['text'] = remaining[:lo]
            if operation == 'read' and prose:
                result['text'] = prefix + remaining[:lo]
            offset += lo
            break
        index += 1
        offset = 0
    more = index < len(items)
    result['has_more'] = more
    result['scope_complete'] = not more
    result['remaining_items'] = len(items) - index
    if operation == 'read':
        result['next_position'] = position(snapshot, items[index]['block'], items[index]['offset'] + offset) if more else None
    result['next_cursor'] = store.save({'query': query, 'state': {'index': index, 'offset': offset}}) if more else None
    result['returned_chars'] = size()
    # The number's own decimal width is part of the serialized budget.
    result['returned_chars'] = size()
    if result['returned_chars'] > budget:
        raise SecError('budget_too_small', 'This response cannot fit in the requested budget.',
                       f"Select less with {NARROWING[operation]}, or raise --max-chars up to {MAX_BUDGET}.")
    return finish(result)


def _canonical(snapshot):
    starts = []
    offset = 0
    for block in snapshot.data['blocks']:
        starts.append(offset)
        offset += len(block['text']) + 1
    text = '\n'.join(block['text'] for block in snapshot.data['blocks'])
    starts.append(len(text))
    return text, starts


def read(snapshot, store, *, position=None, end=None, cursor=None, budget=DEFAULT_BUDGET):
    start = _position(snapshot, position, (0, 0))
    stop = _position(snapshot, end, (len(snapshot.data['blocks']), 0))
    if stop < start:
        raise SecError('invalid_range', 'End precedes the start position.', 'Use an exclusive end after the start.')
    # 성진: 매 페이지에서 사본을 선형 탐색한다, 매우 큰 문서에서 지연이 실측되면 저장 인덱스를 추가한다.
    text, starts = _canonical(snapshot)
    start_offset = starts[start[0]] + start[1]
    stop_offset = starts[stop[0]] + stop[1]
    items = []
    for i, block in enumerate(snapshot.data['blocks']):
        lo = max(starts[i], start_offset)
        hi = min(starts[i + 1], stop_offset)
        if hi <= lo and not (block.get('empty') and start <= (i, 0) < stop):
            continue
        items.append(dict(block, text=text[lo:hi], block=i, offset=lo - starts[i]))
    return _page(snapshot, store, 'read', {'position': position, 'end': end}, items, cursor, budget)


def outline(snapshot, store, *, kinds=DEFAULT_OUTLINE_KINDS, cursor=None, budget=DEFAULT_BUDGET):
    kinds = tuple(kinds)
    if not kinds or any(kind not in OUTLINE_KINDS for kind in kinds):
        raise SecError('invalid_argument', 'Unknown outline kind.', 'Use kinds from: ' + ', '.join(OUTLINE_KINDS) + '.')
    items = [item for item in snapshot.data['outline'] if item['kind'] in kinds]
    return _page(snapshot, store, 'outline', {'kinds': sorted(kinds)}, items, cursor, budget)


def find(snapshot, store, *, query, case_sensitive=False, cursor=None, budget=DEFAULT_BUDGET):
    if not query:
        raise SecError('invalid_query', 'Search text cannot be empty.', 'Provide a nonempty literal string.')
    pattern = re.compile(re.escape(query), 0 if case_sensitive else re.IGNORECASE)
    text, starts = _canonical(snapshot)
    block_starts = starts[:-1]

    def locate(offset):
        if offset == len(text):
            return len(block_starts), 0
        block = bisect_right(block_starts, offset) - 1
        return block, offset - block_starts[block]

    items = []
    for match in pattern.finditer(text):
        block, offset = locate(match.start())
        items.append({'block': block, 'offset': offset, 'match_end': position(snapshot, *locate(match.end())),
                      'text': text[max(0, match.start() - 60):match.end() + 100],
                      'url': snapshot.data['blocks'][block].get('url', snapshot.data['source']['url'])})
    return _page(snapshot, store, 'find', {'query': query, 'case_sensitive': case_sensitive}, items, cursor, budget)


def links(snapshot, store, *, kind=None, cursor=None, budget=DEFAULT_BUDGET):
    if kind not in (None, 'image', 'internal', 'external'):
        raise SecError('invalid_kind', 'Unknown link kind.', 'Use image, internal or external.')
    items = [item for item in snapshot.data['links'] if kind is None or item['kind'] == kind]
    return _page(snapshot, store, 'links', {'kind': kind}, items, cursor, budget)


def table(snapshot, store, *, table_id, rows=None, cursor=None, budget=DEFAULT_BUDGET):
    selected = next((t for t in snapshot.data['tables'] if t['table_id'] == table_id), None)
    if selected is None:
        raise SecError('invalid_table', 'Table identifier is not in this snapshot.', 'Use table_id from open or outline output.')
    last = selected['rows'] - 1
    span = re.fullmatch(r'(\d+)(?:-(\d+))?', rows or '')
    first, final = (int(span[1]), int(span[2] or span[1])) if span else (0, last)
    if not span and rows or first > final or final > last:
        raise SecError('invalid_argument', 'Row range is outside this table.', f'Use rows within 0-{last}, e.g. --rows 2-5.')
    framing = [r for r in selected['items'] if r['kind'] in ('context', 'caption', 'footnote') and r['text']]
    # Empty layout cells carry no evidence; the original DOM keeps them.
    body = [r for r in selected['items']
            if r['kind'] not in ('context', 'caption', 'footnote')
            and first <= r['row'] <= final and (r['text'] or r['kind'] != 'cell')]
    return _page(snapshot, store, 'table', {'table_id': table_id, 'rows': rows}, framing + body, cursor, budget,
                 _assemble_table)
