"""Budgeted navigation over one immutable snapshot; no parsing or network access."""
import json
from bisect import bisect_right

from output import SecError
from store import digest


def position(snapshot, block, offset=0):
    return f'{snapshot.id}:{block}:{offset}'


def _position(snapshot, value, default):
    if value is None:
        return default
    try:
        sid, block, offset = value.split(':')
        block, offset = int(block), int(offset)
        if sid != snapshot.id or block < 0 or offset < 0:
            raise ValueError
        blocks = snapshot.data['blocks']
        if block > len(blocks) or (block == len(blocks) and offset) or (block < len(blocks) and offset > len(blocks[block]['text'])):
            raise ValueError
        return block, offset
    except (ValueError, AttributeError):
        raise SecError('invalid_position', 'Position belongs to a different snapshot or is out of range.', 'Use a position returned for this snapshot.') from None


def _page(snapshot, store, operation, options, items, cursor, limit, budget):
    if not isinstance(limit, int) or not 1 <= limit <= 20 or not isinstance(budget, int) or not 1024 <= budget <= 12000:
        raise SecError('invalid_budget', 'Limit must be 1..20 and budget must be 1024..12000 characters.', 'Use the defaults or values in these ranges.')
    query = {'version': 2, 'operation': operation, 'snapshot_id': snapshot.id, 'options': options, 'limit': limit, 'budget': budget}
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
    if operation == 'read':
        result['text'] = ''
        result['next_position'] = position(snapshot, len(snapshot.data['blocks']), max((len(b['text']) for b in snapshot.data['blocks']), default=0))

    def size():
        return len(json.dumps(result, ensure_ascii=False, indent=2)) + 1

    while index < len(items) and len(result['items']) < limit:
        original = items[index]
        text = original.get('text', '')
        remaining = text[offset:]
        item = dict(original, text=remaining, text_offset=offset, text_complete=True)
        if 'block' in original:
            item['position'] = position(snapshot, original['block'], original.get('offset', 0) + (offset if operation == 'read' else 0))
        if 'context_block' in original:
            item['context_position'] = position(snapshot, original['context_block'], 0)
        result['items'].append(item)
        prefix = result.get('text', '')
        if operation == 'read':
            result['text'] = prefix + remaining
        if size() > budget:
            lo, hi = 0, len(remaining)
            item['text_complete'] = False
            while lo < hi:
                mid = (lo + hi + 1) // 2
                item['text'] = remaining[:mid]
                if operation == 'read':
                    result['text'] = prefix + remaining[:mid]
                if size() <= budget:
                    lo = mid
                else:
                    hi = mid - 1
            if lo == 0:
                result['items'].pop()
                if operation == 'read':
                    result['text'] = prefix
                if not result['items']:
                    raise SecError('budget_too_small', 'One item has metadata larger than this budget.', 'Increase budget or follow the original source URL.')
                break
            item['text'] = remaining[:lo]
            if operation == 'read':
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
    return result


def _canonical(snapshot):
    starts = []
    offset = 0
    for block in snapshot.data['blocks']:
        starts.append(offset)
        offset += len(block['text']) + 1
    text = '\n'.join(block['text'] for block in snapshot.data['blocks'])
    starts.append(len(text))
    return text, starts


def read(snapshot, store, *, position=None, end=None, cursor=None, limit=20, budget=12000):
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
    return _page(snapshot, store, 'read', {'position': position, 'end': end}, items, cursor, limit, budget)


def outline(snapshot, store, *, cursor=None, limit=20, budget=12000):
    return _page(snapshot, store, 'outline', {}, snapshot.data['outline'], cursor, limit, budget)


def find(snapshot, store, *, query, case_sensitive=False, cursor=None, limit=20, budget=12000):
    if not query:
        raise SecError('invalid_query', 'Search text cannot be empty.', 'Provide a nonempty literal string.')
    import re
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
    return _page(snapshot, store, 'find', {'query': query, 'case_sensitive': case_sensitive}, items, cursor, limit, budget)


def links(snapshot, store, *, kind=None, cursor=None, limit=20, budget=12000):
    if kind not in (None, 'image', 'internal', 'external'):
        raise SecError('invalid_kind', 'Unknown link kind.', 'Use image, internal or external.')
    items = [item for item in snapshot.data['links'] if kind is None or item['kind'] == kind]
    return _page(snapshot, store, 'links', {'kind': kind}, items, cursor, limit, budget)


def table(snapshot, store, *, table_id, cursor=None, limit=20, budget=12000):
    selected = next((t for t in snapshot.data['tables'] if t['table_id'] == table_id), None)
    if selected is None:
        raise SecError('invalid_table', 'Table identifier is not in this snapshot.', 'Use table_id from open output.')
    return _page(snapshot, store, 'table', {'table_id': table_id}, selected['items'], cursor, limit, budget)
