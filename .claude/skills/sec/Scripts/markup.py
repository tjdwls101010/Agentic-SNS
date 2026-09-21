"""Turn SEC HTML into reading blocks, links, anchors and tables.

One passage is one block. A table is one block holding its grid, not one block per cell: 92%
of the blocks in the document this model was designed against were single table cells, so
reading it returned a stream of fragments with no way to see which number belonged to which
measure.
"""

import re
from urllib.parse import quote, unquote, urljoin

from grid import build_table
from snapshot import cell_text, collapse

BOUNDARY_TAGS = frozenset(
    {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section'}
)
HEADING_TAGS = frozenset({'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})
CELL_TAGS = frozenset({'td', 'th'})
SKIP_TAGS = frozenset({'script', 'style', 'head'})
INLINE_XBRL = {'http://www.xbrl.org/2008/inlineXBRL', 'http://www.xbrl.org/2013/inlineXBRL'}
# 성진: 표 주변 문맥은 앞뒤 두 블록이다, 더 먼 제목·단위가 필요한 문서가 나오면 반환 위치로 범위를 넓힌다.
FRAMING_BLOCKS = 2


def tag_of(node):
    return str(node.tag).lower() if isinstance(node.tag, str) else ''


def element_text(node, nonbody):
    """Read one element's visible text with the same rules a block uses."""
    def parts(element):
        tag = tag_of(element)
        if tag in SKIP_TAGS or tag in nonbody or not isinstance(element.tag, str):
            return
        if tag in BOUNDARY_TAGS or tag in CELL_TAGS or tag == 'tr':
            yield ' '
        yield element.text or ''
        for child in element:
            yield from parts(child)
            yield child.tail or ''
        if tag in BOUNDARY_TAGS or tag in CELL_TAGS or tag == 'tr':
            yield ' '

    return cell_text(''.join(parts(node)))


def parse_html(text, url):
    """Return (blocks, outline, links, tables, inline_xbrl_metadata_excluded)."""
    from lxml import html

    root = html.document_fromstring(re.sub(r'^\s*<\?xml[^?]*\?>', '', text))
    return _Document(root, url).build()


class _Document:
    def __init__(self, root, url):
        self.root, self.url = root, url
        prefixes = {name[6:] for node in root.iter() for name, value in node.attrib.items()
                    if name.startswith('xmlns:') and value in INLINE_XBRL}
        self.nonbody = {f'{p}:{n}' for p in prefixes for n in ('header', 'hidden')}
        self.table_nodes = root.xpath('//table')
        self.table_ids = {node: f'table-{i}' for i, node in enumerate(self.table_nodes)}
        self.link_ids = {}
        for node in root.iter():
            tag = tag_of(node)
            if (tag == 'a' and node.get('href')) or (tag == 'img' and node.get('src')):
                self.link_ids[node] = f'link-{len(self.link_ids)}'
        self.anchor_nodes = {}
        for node in root.iter():
            for key in (node.get('id'), node.get('name') if tag_of(node) == 'a' else None):
                if key:
                    self.anchor_nodes.setdefault(key, node)

        self.blocks, self.outline, self.links, self.tables = [], [], [], []
        self.excluded = False
        self.pending, self.marks = [], []
        self.link_items, self.anchor_items, self.cell_of = {}, {}, {}
        self.block_of_node = {}
        self.active_anchor = None

    # --- walking ---------------------------------------------------------------------------

    def build(self):
        self.walk(self.root)
        self.flush()
        for table in self.tables:
            self.frame(table)
        self.resolve_links()
        self.list_tables()
        rank = {'toc': 0, 'heading': 1, 'table': 2, 'anchor': 3, 'internal_link': 4}
        self.outline.sort(key=lambda item: (item['block'], item['offset'], rank[item['kind']]))
        return self.blocks, self.outline, self.links, self.tables, self.excluded

    def flush(self):
        raw = ''.join(self.pending)
        value = cell_text(raw)
        for item, raw_offset in self.marks:
            item['block'] = len(self.blocks)
            # lstrip only: the leading space the flush drops shifts every offset, the
            # trailing one is still ahead of the mark.
            item['offset'] = min(len(value), len(re.sub(r'\s+', ' ', raw[:raw_offset]).lstrip()))
        self.marks.clear()
        self.pending.clear()
        if value:
            url = self.url + '#' + quote(self.active_anchor) if self.active_anchor else self.url
            self.blocks.append({'kind': 'text', 'text': value, 'url': url})

    def walk(self, node):
        tag = tag_of(node)
        if tag in self.nonbody:
            self.excluded = True
            return
        if tag in SKIP_TAGS or not isinstance(node.tag, str):
            return
        if tag == 'table':
            self.flush()
            self.emit_table(node)
            return
        if tag in BOUNDARY_TAGS:
            self.flush()
        self.block_of_node[node] = len(self.blocks)
        previous = self.active_anchor
        self.mark_anchor(node, tag)
        self.mark_link(node, tag)
        if node.text:
            self.pending.append(node.text)
        for child in node:
            self.walk(child)
            if child.tail:
                self.pending.append(child.tail)
        if tag in BOUNDARY_TAGS:
            self.flush()
        self.active_anchor = previous

    def mark_anchor(self, node, tag):
        key = node.get('id') or (node.get('name') if tag == 'a' else None)
        if not key:
            return
        self.active_anchor = key
        item = {'kind': 'anchor', 'text': key, 'block': len(self.blocks), 'offset': 0,
                'url': self.url + '#' + quote(key)}
        self.outline.append(item)
        self.anchor_items[node] = item
        self.marks.append((item, len(''.join(self.pending))))

    def mark_link(self, node, tag):
        target = node.get('src') if tag == 'img' else node.get('href') if tag == 'a' else None
        if not target:
            return
        item = self.link_record(node, tag, target)
        self.links.append(item)
        self.link_items[node] = item
        self.marks.append((item, len(''.join(self.pending))))

    def link_record(self, node, tag, target):
        label = node.get('alt', '') if tag == 'img' else collapse(''.join(node.itertext()))
        kind = 'image' if tag == 'img' else 'internal' if target.startswith('#') else 'external'
        item = {'id': self.link_ids[node], 'kind': kind, 'url': urljoin(self.url, target),
                'text': label, 'block': len(self.blocks), 'offset': 0}
        if kind == 'internal':
            item['target_resolved'] = unquote(target[1:]) in self.anchor_nodes
        return item

    # --- tables ----------------------------------------------------------------------------

    def emit_table(self, node):
        """Emit this table's grid block, then its descendants' blocks in DOM order.

        Flat order is not browser order. The parent grid keeps the reference marking where the
        child interrupted a cell, so that difference stays visible instead of the child reading
        as free-standing prose.
        """
        for element in [node, *node.xpath('.//table')]:
            coords = {}
            table = build_table(element, self.table_ids[element], table_ids=self.table_ids,
                                link_ids=self.link_ids, parent=self.parent_of(element),
                                coords=coords, skip_tags=self.nonbody)
            self.cell_of.update(coords)
            table['block'] = len(self.blocks)
            self.blocks.append({'kind': 'grid', 'text': table['text'],
                                'table_id': table['table_id'], 'url': self.url})
            self.tables.append(table)
            self.mark_inside(element, table, coords)

    def parent_of(self, element):
        parent_table = next(element.iterancestors('table'), None)
        if parent_table is None:
            return None
        cell = next((a for a in element.iterancestors() if tag_of(a) in CELL_TAGS), None)
        row, column = self.cell_of.get(cell, (0, 0))
        return (self.table_ids[parent_table], row, column)

    def mark_inside(self, node, table, coords):
        """Give every anchor and link inside this table the cell it actually sits in."""
        starts = {(cell['row'], cell['column']): cell['text_start'] for cell in table['cells']}
        for element in node.iter():
            if element is node or next(element.iterancestors('table'), None) is not node:
                continue
            tag = tag_of(element)
            if tag in SKIP_TAGS or tag in self.nonbody:
                continue
            cell = element if tag in CELL_TAGS else next(
                (a for a in element.iterancestors() if tag_of(a) in CELL_TAGS), None
            )
            place = coords.get(cell)
            self.block_of_node[element] = table['block']
            if place is None:
                continue
            where = {'block': table['block'], 'offset': starts.get(place, 0),
                     'table_id': table['table_id'], 'row': place[0], 'column': place[1]}
            key = element.get('id') or (element.get('name') if tag == 'a' else None)
            if key:
                item = {'kind': 'anchor', 'text': key, 'url': self.url + '#' + quote(key), **where}
                self.outline.append(item)
                self.anchor_items[element] = item
            target = element.get('src') if tag == 'img' else element.get('href') if tag == 'a' else None
            if target:
                item = self.link_record(element, tag, target)
                item.update(where)
                self.links.append(item)
                self.link_items[element] = item

    def frame(self, table):
        """Attach the prose, caption and notes that say what this table measures."""
        node = next(n for n, i in self.table_ids.items() if i == table['table_id'])
        block = table['block']
        before = [{'kind': 'context', 'text': self.blocks[i]['text'], 'block': i}
                  for i in range(max(0, block - FRAMING_BLOCKS), block)
                  if self.blocks[i]['kind'] == 'text' and self.blocks[i]['text']]
        after = []
        # 성진: 표 뒤 두 블록까지만 본다, 표가 곧바로 이어지는 문서에서 다음 표의 머리 조각이 딸려오면 좁힌다.
        for index in range(block + 1, min(block + 1 + 20, len(self.blocks))):
            if len(after) == FRAMING_BLOCKS:
                break
            if self.blocks[index]['kind'] == 'text' and self.blocks[index]['text']:
                after.append({'kind': 'context', 'text': self.blocks[index]['text'], 'block': index})
        caption = node.find('caption')
        table['caption'] = ({'text': element_text(caption, self.nonbody), 'block': block}
                            if caption is not None and element_text(caption, self.nonbody) else None)
        table['context'] = ((table['caption'] or {}).get('text')
                            or (before[-1]['text'] if before else '')
                            or (after[0]['text'] if after else ''))
        table['context_blocks'] = before + after
        table['footnotes'] = self.notes(node, block)

    def notes(self, node, block):
        """The note beside an anchor this table points at, never a section the outline carries."""
        containers = set(node.iterancestors())
        found, seen = [], set()
        for anchor in node.xpath('.//a[starts-with(@href, "#")]'):
            fragment = unquote(anchor.get('href')[1:])
            if fragment in seen or fragment not in self.anchor_nodes:
                continue
            seen.add(fragment)
            target = self.anchor_nodes[fragment]
            if self.is_navigation(target):
                continue
            parent = target.getparent()
            # An anchor tag marks where a note sits; the note is the block around it, not the marker.
            marker = tag_of(target) == 'a'
            candidates = [parent, target] if marker else [target, parent]
            candidates += [target.getnext(), parent.getnext() if parent is not None else None]
            chosen = next((c for c in candidates
                           if c is not None and c is not node and c not in containers
                           and not self.is_navigation(c) and element_text(c, self.nonbody)), None)
            if chosen is None:
                continue
            found.append({'kind': 'footnote', 'text': element_text(chosen, self.nonbody),
                          'url': urljoin(self.url, anchor.get('href')),
                          'block': self.block_of_node.get(chosen, block)})
        return found

    def is_navigation(self, node):
        """A section the document itself declares as a heading is navigation, not a note.

        This asks the original's own tags rather than the emphasis observation: which blocks look
        emphasized is a tuned judgement, and a note must not stop being a note when that tuning
        changes.
        """
        return any(tag_of(n) in HEADING_TAGS for n in [node, *node.iterancestors()])

    # --- assembling ------------------------------------------------------------------------

    def resolve_links(self):
        contents = {}
        for node, item in self.link_items.items():
            item['context_block'] = min(item['block'], max(0, len(self.blocks) - 1))
            if item['kind'] != 'internal' or not item.get('target_resolved'):
                continue
            target = self.anchor_nodes[unquote(node.get('href')[1:])]
            position = self.anchor_items.get(target)
            if position is None:
                continue
            kind = 'toc' if self.is_navigation(target) else 'internal_link'
            entry = dict(item, kind=kind, block=position['block'], offset=position['offset'])
            entry.pop('id', None)
            # A contents row often links its number, title and page separately; one target is one entry.
            key = (entry['block'], entry['offset'])
            if kind == 'toc' and key in contents:
                contents[key]['text'] += ' ' + entry['text']
                continue
            if kind == 'toc':
                contents[key] = entry
            self.outline.append(entry)

    def list_tables(self):
        for table in self.tables:
            self.outline.append({'kind': 'table', 'text': table['table_id'], 'table_id': table['table_id'],
                                 'block': table['block'], 'offset': 0, 'rows': table['original_rows'],
                                 'columns': len(table['kept_columns']), 'context': table['context'][:200]})
