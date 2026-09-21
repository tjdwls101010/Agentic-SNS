"""Render every command's result, in text or JSON, and measure what was emitted.

The budget is the size of what actually leaves this process. Measuring JSON while emitting text
made a small grid page as if it were a large one: the structure cost more than the content.
"""

import json


class SecError(Exception):
    def __init__(self, code, message, fix):
        super().__init__(message)
        self.code, self.message, self.fix = code, message, fix


# What an excerpt needs beside it: where it came from, what limits the extraction it came from,
# and how to continue.
HEADER = ('source_url', 'snapshot_id', 'status', 'format', 'known_extraction_limits',
          'scope_complete', 'has_more', 'remaining_items', 'total_matches', 'next_position',
          'next_cursor', 'returned_chars')
# A listing's own coverage: how many came back, how many are held, and whether the remote side
# was finished. Without these a text-mode listing looks like the whole answer.
LISTING = ('returned', 'remaining_saved', 'remote_complete', 'selection_required', 'filing_hits',
           'total', 'unreturned_reason', 'timed_out', 'shards_failed', 'limit_reached',
           'next_cursor')


def _scalar(value):
    if isinstance(value, dict):
        # A nested record reads as its own fields, not as a Python repr of a dictionary.
        return '{' + _row_line(value) + '}'
    if isinstance(value, list):
        return ' ; '.join(_scalar(item) for item in value) if value else '(none)'
    return str(value)


def _header(value):
    keys = LISTING if value.get('operation') in ('company', 'filings', 'search', 'index') else HEADER
    return [f'{key}: {_scalar(value[key])}' for key in keys if value.get(key) is not None]


def _grid_lines(segment):
    """One table's opening line, its framing, and the rows selected from it."""
    lines = [(f"[{segment['table_id']} | {segment['original_rows']} rows"
              f" × {len(segment['kept_columns'])} columns"
              f" | kept_columns {', '.join(str(c) for c in segment['kept_columns'])}]")]
    if segment.get('caption'):
        lines.append(f"caption: {segment['caption']['text']}")
    for note in segment.get('context', []):
        lines.append(f"context: {note['text']}")
    if segment.get('spans'):
        lines.append('spans: ' + ' | '.join(
            f"r{s['row']}c{s['column']} colspan={s['colspan']} rowspan={s['rowspan']} w={s['w']}"
            + (f" effective_rows={s['effective_rows']}" if 'effective_rows' in s else '')
            for s in segment['spans']))
    if segment.get('context_rows'):
        lines.append(f"context_rows ({'truncated' if segment.get('context_truncated') else 'complete'}):")
        lines.extend(row['text'] for row in segment['context_rows'])
    elif segment.get('context_truncated'):
        lines.append('context_rows: none fitted this budget')
    lines.extend(row['text'] for row in segment.get('rows', []))
    for note in segment.get('footnotes', []):
        lines.append(f"footnote: {note['text']}")
    for position in segment.get('context_position', []):
        lines.append(f'context_position: {position}')
    return lines


def _outline_line(item):
    if item['kind'] == 'emphasis':
        places = ' | '.join(
            f"{place['position']}"
            f"{' ' + place['table_id'] + ' r' + str(place['row']) if 'table_id' in place else ''}"
            f" bold={place['signals']['bold_fraction']}"
            f"{' size=' + str(place['signals']['font_size_ratio']) if place['signals']['font_size_ratio'] is not None else ''}"
            f"{' caps' if place['signals']['all_caps'] else ''}"
            f"{' ' + place['signals']['alignment'] if place['signals']['alignment'] else ''}"
            for place in item['occurrences'])
        return f"emphasis | {item['text']} | {places}"
    if item['kind'] == 'table':
        return (f"table | {item['table_id']} | {item['rows']} rows × {item['columns']} columns"
                f" | {item['position']} | {item.get('context', '')}")
    extra = f" | {item['anchor']}" if item.get('anchor') else ''
    return f"{item['kind']} | {item.get('text', '')} | {item['position']}{extra}"


def _find_line(item):
    where = ''
    if 'table_id' in item:
        where = f" | {item['table_id']} r{item['row']}"
        if item.get('row_end') is not None and item['row_end'] != item['row']:
            where += f"-r{item['row_end']}"
        if item.get('column') is not None:
            where += f" c{item['column']}"
    return f"{item['position']}{where} | {item['text']}"


def _link_line(item):
    resolved = '' if item.get('target_resolved') is None else (
        ' | resolved' if item['target_resolved'] else ' | unresolved')
    where = f" | {item['table_id']} r{item['row']}c{item['column']}" if 'table_id' in item else ''
    return f"{item['kind']} | {item.get('text', '')} | {item['url']} | {item['position']}{where}{resolved}"


def _row_line(fields):
    return ' | '.join(f'{key}: {_scalar(value)}' for key, value in fields.items()
                      if value is not None and value != [])


def passage(value):
    operation = value.get('operation')
    if operation == 'read':
        lines = []
        for segment in value.get('segments', []):
            lines.extend(_grid_lines(segment) if segment['kind'] == 'grid'
                         else [f"{segment['position']}  {segment['text']}"])
        return '\n'.join(lines)
    if operation == 'table':
        return '\n'.join(_grid_lines(value['table']))
    if operation == 'outline':
        return '\n'.join(_outline_line(item) for item in value['items'])
    if operation == 'find':
        return '\n'.join(_find_line(item) for item in value['items'])
    if operation == 'links':
        return '\n'.join(_link_line(item) for item in value['items'])
    if operation == 'doctor':
        return '\n'.join(f'{key}: {_scalar(value[key])}' for key in value
                         if key not in ('operation', 'error'))
    if operation == 'document':
        lines = [f'encoding: {_row_line(value["encoding"])}',
                 f'blocks: {value["blocks"]} | tables: {value["table_count"]}']
        lines += [f"table | {t['table_id']} | {t['rows']} rows × {t['columns']} columns"
                  f" | {t['position']} | {t['context']}" for t in value['tables']]
        return '\n'.join(lines)
    return '\n'.join(_row_line(item) for item in value.get('items', []))


def _dump(value, indent=0):
    """Indented JSON that keeps a list of plain values on one line.

    One integer per line turned a table's kept_columns into several hundred characters of
    structure, which is what a page's budget was being spent on rather than its content.
    """
    pad = ' ' * indent
    if isinstance(value, dict) and value:
        body = ',\n'.join(f'{pad}  {json.dumps(key, ensure_ascii=False)}: {_dump(item, indent + 2)}'
                          for key, item in value.items())
        return '{\n' + body + f'\n{pad}}}'
    if isinstance(value, list) and value:
        if all(not isinstance(item, (dict, list)) for item in value):
            return json.dumps(value, ensure_ascii=False)
        body = ',\n'.join(f'{pad}  {_dump(item, indent + 2)}' for item in value)
        return '[\n' + body + f'\n{pad}]'
    return json.dumps(value, ensure_ascii=False)


def render(value, as_json):
    if as_json:
        return _dump(value)
    if set(value) == {'error'}:
        error = value['error']
        return f"Error [{error['code']}]: {error['message']}\nFix: {error['fix']}"
    if 'operation' not in value:
        return '\n'.join(f'{key}: {json.dumps(item, ensure_ascii=False)}' for key, item in value.items())
    header = _header(value)
    body = passage(value)
    if not header:
        return body + ('\n\n' + _error_lines(value) if value.get('error') else '')
    if value.get('error'):
        body += '\n\n' + _error_lines(value)
    return '\n'.join(header) + ('\n\n' + body if body else '')


def _error_lines(value):
    error = value['error']
    return f"Error [{error['code']}]: {error['message']}\nFix: {error['fix']}"


def measure(value, as_json):
    """The exact character count this result will print, including its trailing newline."""
    settled = dict(value)
    for _ in range(3):
        size = len(render(settled, as_json)) + 1
        if settled.get('returned_chars') == size:
            return size
        settled['returned_chars'] = size
    return len(render(settled, as_json)) + 1


def emit(value, as_json):
    if 'returned_chars' in value:
        value['returned_chars'] = measure(value, as_json)
    print(render(value, as_json))
