"""Build immutable reading snapshots from already received SEC source bytes."""
import codecs
import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urljoin, urlsplit

from bs4 import UnicodeDammit
from lxml import etree, html
from output import SecError


@dataclass
class SourceDocument:
    body: bytes
    source: dict
    headers: dict = field(default_factory=dict)


@dataclass
class DocumentSnapshot:
    id: str
    data: dict

    def summary(self):
        return {'snapshot_id': self.id, 'source': self.data['source'], 'status': self.data['status'],
                'format': self.data['format'], 'blocks': len(self.data['blocks']), 'tables': [{k: v for k, v in t.items() if k != 'items'} for t in self.data['tables'][:20]],
                'table_count': len(self.data['tables']), 'tables_has_more': len(self.data['tables']) > 20,
                'encoding': self.data['encoding'], 'warnings': self.data['warnings'],
                'extraction_complete': self.data['extraction_complete']}


def _clean(text):
    return re.sub(r'\s+', ' ', text).strip()


def _dom_text(node, excluded_tags):
    def parts(element):
        if not isinstance(element.tag, str) or element.tag.lower() in {'script', 'style'} | excluded_tags:
            return
        if element.tag.lower() in ('div', 'p', 'br'):
            yield ' '
        yield element.text or ''
        for index, child in enumerate(element):
            if index and child.tag in ('td', 'th', 'tr'):
                yield ' '
            yield from parts(child)
            yield child.tail or ''
        if element.tag.lower() in ('div', 'p', 'br'):
            yield ' '
    return _clean(''.join(parts(node)))


def _html_blocks(text, url):
    from edgar.documents import HTMLParser

    sdk = HTMLParser().parse(text)
    # 성진: SDK 제목은 원문 블록 텍스트로 대응하는 탐지 후보다, SDK가 원문 위치를 제공하면 직접 대응으로 바꾼다.
    headings = {_clean(n.text()) for n in sdk.headings}
    root = html.document_fromstring(re.sub(r'^\s*<\?xml[^?]*\?>', '', text))
    inline_namespaces = {'http://www.xbrl.org/2008/inlineXBRL', 'http://www.xbrl.org/2013/inlineXBRL'}
    inline_prefixes = {name[6:] for node in root.iter() for name, value in node.attrib.items()
                       if name.startswith('xmlns:') and value in inline_namespaces}
    nonbody_tags = {f'{prefix}:{name}' for prefix in inline_prefixes for name in ('header', 'hidden')}
    excluded_metadata = False
    blocks, outlines, link_items = [], [], []
    pending = []
    pending_positions = []
    anchor_positions = {}
    node_blocks = {}
    table_nodes = root.xpath('//table')
    table_ids = {node: f'table-{i}' for i, node in enumerate(table_nodes)}
    anchors = {}
    for node in root.iter():
        for key in (node.get('id'), node.get('name') if node.tag == 'a' else None):
            if key:
                anchors.setdefault(key, node)
    link_nodes = {}
    active_anchor = None
    active_heading = False

    def flush():
        nonlocal active_heading
        raw = ''.join(pending)
        value = _clean(raw)
        for item, raw_offset in pending_positions:
            item['block'] = len(blocks)
            item['offset'] = min(len(value), len(re.sub(r'\s+', ' ', raw[:raw_offset]).lstrip()))
        pending_positions.clear()
        pending.clear()
        if value:
            kind = 'heading' if active_heading or value in headings else 'text'
            block = {'kind': kind, 'text': value, 'url': url + '#' + quote(active_anchor) if active_anchor else url}
            blocks.append(block)
            if kind == 'heading':
                outlines.append(dict(block, block=len(blocks) - 1, offset=0))
        active_heading = False

    def walk(node):
        nonlocal active_anchor, active_heading, excluded_metadata
        tag = str(node.tag).lower()
        if tag in nonbody_tags:
            excluded_metadata = True
            return
        if tag in ('script', 'style', 'head') or not isinstance(node.tag, str):
            return
        boundary = tag in ('p', 'div', 'br', 'li', 'table', 'tr', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section')
        if boundary:
            flush()
        node_blocks[node] = len(blocks)
        old_anchor = active_anchor
        if node.get('id') or (tag == 'a' and node.get('name')):
            active_anchor = node.get('id') or node.get('name')
            item = {'kind': 'anchor', 'text': active_anchor, 'block': len(blocks), 'offset': 0,
                    'url': url + '#' + quote(active_anchor)}
            outlines.append(item)
            anchor_positions[node] = item
            pending_positions.append((item, len(''.join(pending))))
        active_heading = active_heading or tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')
        target = node.get('src') if tag == 'img' else node.get('href') if tag == 'a' else None
        if target:
            label = node.get('alt', '') if tag == 'img' else _clean(''.join(node.itertext()))
            kind = 'image' if tag == 'img' else 'internal' if target.startswith('#') else 'external'
            item = {'kind': kind, 'url': urljoin(url, target), 'text': label, 'block': len(blocks),
                    'offset': len(_clean(''.join(pending)))}
            pending_positions.append((item, len(''.join(pending))))
            link_items.append(item)
            link_nodes[node] = item
            if kind == 'internal':
                item['target_resolved'] = unquote(target[1:]) in anchors
        if node.text:
            pending.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                pending.append(child.tail)
        if boundary:
            flush()
        active_anchor = old_anchor

    walk(root)
    flush()
    for node, item in link_nodes.items():
        item['context_block'] = min(item['block'], max(0, len(blocks) - 1))
        if item['kind'] == 'internal' and item['target_resolved']:
            target = anchors[unquote(node.get('href')[1:])]
            target_position = anchor_positions.get(target)
            if target_position is not None:
                target_block = target_position['block']
                kind = 'toc' if target_block < len(blocks) and blocks[target_block]['kind'] == 'heading' else 'internal_link'
                outlines.append(dict(item, kind=kind, block=target_block, offset=target_position['offset']))
    tables = []
    for node in table_nodes:
        if node not in node_blocks:
            continue
        table_id = table_ids[node]
        block_index = node_blocks.get(node, 0)
        # 성진: 표 주변 문맥은 직전 두 블록이다, 더 먼 제목·단위가 필요한 문서는 반환 위치로 범위를 넓힌다.
        records = [{'kind': 'context', 'text': b['text'], 'block': i}
                   for i, b in enumerate(blocks[max(0, block_index - 2):block_index], max(0, block_index - 2))]
        caption = node.find('caption')
        if caption is not None:
            records.append({'kind': 'caption', 'text': _dom_text(caption, nonbody_tags)})
        rows = [row for row in node.iter('tr') if next(row.iterancestors('table'), None) is node]
        occupied = {}
        for r, row in enumerate(rows):
            column = 0
            for cell in row:
                if str(cell.tag).lower() not in ('td', 'th'):
                    continue
                while occupied.get(column, 0) > r:
                    column += 1
                try:
                    rowspan = max(0, int(cell.get('rowspan', 1)))
                    colspan = max(1, int(cell.get('colspan', 1)))
                    if colspan > 10000:
                        raise ValueError
                except ValueError:
                    raise SecError('parse_failed', 'Table contains invalid spans.', 'Inspect the original table.') from None
                for c in range(column, column + colspan):
                    occupied[c] = r + rowspan if rowspan else len(rows)
                cell_block = node_blocks.get(cell, block_index)
                if cell_block < len(blocks):
                    blocks[cell_block]['table_id'] = table_id
                records.append({'kind': 'cell', 'row': r, 'column': column, 'rowspan': rowspan,
                                'colspan': colspan, 'header': cell.tag.lower() == 'th',
                                'scope': cell.get('scope'), 'headers': cell.get('headers'),
                                'text': _dom_text(cell, nonbody_tags), 'block': cell_block})
                for descendant in cell.iter():
                    if descendant in link_nodes:
                        records.append(dict(link_nodes[descendant], row=r, column=column))
                column += colspan
        seen = set()
        for anchor in node.xpath('.//a[starts-with(@href, "#")]'):
            fragment = unquote(anchor.get('href')[1:])
            if fragment in seen:
                continue
            seen.add(fragment)
            if fragment in anchors:
                target = anchors[fragment]
                if not _dom_text(target, nonbody_tags) and target.getparent() is not None:
                    target = target.getparent()
                records.append({'kind': 'footnote', 'text': _dom_text(target, nonbody_tags),
                                'url': urljoin(url, anchor.get('href')), 'block': node_blocks.get(target, 0)})
        outlines.append({'kind': 'table', 'text': table_id, 'table_id': table_id, 'block': block_index, 'offset': 0, 'url': url})
        tables.append({'table_id': table_id, 'rows': len(rows), 'block': block_index, 'items': records,
                       'parent_table_id': table_ids.get(next(node.iterancestors('table'), None))})
    return blocks, outlines, link_items, tables, excluded_metadata


def _xml_blocks(text, url):
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False)
    root = etree.fromstring(re.sub(r'^\s*<\?xml[^?]*\?>', '', text), parser=parser)
    blocks = []

    def walk(node, path, parent):
        base = {'kind': 'xml', 'path': path, 'parent': parent, 'attributes': dict(node.attrib), 'url': url}
        if node.text and node.text.strip():
            blocks.append(dict(base, text=node.text.strip()))
        counts = {}
        for child in node:
            if isinstance(child.tag, str):
                tag = etree.QName(child).localname
                counts[tag] = counts.get(tag, 0) + 1
                walk(child, f'{path}/{tag}[{counts[tag]}]', path)
            if child.tail and child.tail.strip():
                blocks.append(dict(base, text=child.tail.strip()))
        if len(node) == 0 and not (node.text or '').strip():
            blocks.append(dict(base, text='', empty=True))

    walk(root, f'/{etree.QName(root).localname}[1]', None)
    return blocks


def _sgml_blocks(text, url):
    from edgar.sgml import FilingSGML

    filing = FilingSGML.from_text(text)
    blocks = []
    previous = 0
    for match in re.finditer(r'<DOCUMENT>.*?</DOCUMENT>', text, re.IGNORECASE | re.DOTALL):
        if match.start() > previous:
            blocks.append({'kind': 'text', 'text': text[previous:match.start()], 'url': url})
        sequence = re.search(r'<SEQUENCE>\s*([^\r\n<]+)', match.group(), re.IGNORECASE)
        document = filing.get_document_by_sequence(sequence.group(1).strip()) if sequence else None
        if document is None:
            raise SecError('parse_failed', 'SGML document boundary has no matching SDK document.', 'Read the original submission text.')
        blocks.append({'kind': 'document', 'text': match.group(), 'sequence': document.sequence,
                       'document_type': document.type, 'filename': document.filename, 'url': url})
        previous = match.end()
    if not blocks:
        raise SecError('parse_failed', 'No complete SGML document boundaries were found.', 'Read the original submission text.')
    if previous < len(text):
        blocks.append({'kind': 'text', 'text': text[previous:], 'url': url})
    return blocks


def _parse_document(source, store):
    content_type = next((v for k, v in source.headers.items() if k.lower() == 'content-type'), '')
    header_match = re.search(r'charset=["\']?([^;"\'\s]+)', content_type, re.IGNORECASE)
    header_encoding = header_match.group(1) if header_match else None
    media = content_type.split(';', 1)[0].lower()
    binary = source.body.startswith((b'%PDF-', b'\x89PNG', b'\xff\xd8', b'GIF87a', b'GIF89a')) or media == 'application/pdf' or media.startswith('image/')
    decoded = UnicodeDammit(b'' if binary else source.body, is_html=True)
    if not binary and not decoded.declared_html_encoding and header_encoding:
        decoded = UnicodeDammit(source.body, known_definite_encodings=[header_encoding], is_html=True)
    text = decoded.unicode_markup or ''
    declarations = [value for value in (header_encoding, decoded.declared_html_encoding) if value]
    def normalized(value):
        try:
            return codecs.lookup(value).name
        except LookupError:
            return value.lower()
    selected = decoded.original_encoding or 'utf-8'
    encoding = {'selected': selected, 'declared': declarations,
                'inferred': not declarations,
                'conflict': any(normalized(value) != normalized(selected) for value in declarations),
                'loss': bool(decoded.contains_replacement_characters or '\ufffd' in text)}
    url = source.source['url']
    is_html = bool(re.search(r'<(?:html|body|div|p|table|h[1-6]|img|a|span|pre|ul|ol)(?:\s|>)', text[:10000], re.IGNORECASE))
    html_document = bool(re.search(r'<html(?:\s|>)', text[:10000], re.IGNORECASE))
    is_xml = (('xml' in media and media != 'application/xhtml+xml')
              or (urlsplit(url).path.lower().endswith('.xml') and media != 'text/html')
              or (text.lstrip().startswith('<?xml') and not html_document))
    excluded_metadata = False
    if binary:
        format_name = 'pdf' if source.body.startswith(b'%PDF-') or media == 'application/pdf' else 'image'
        blocks, outlines, link_items, tables = [], [], [], []
    elif re.search(r'<DOCUMENT>', text, re.IGNORECASE) and (not is_html or re.search(r'<SEC-HEADER>', text, re.IGNORECASE) or len(re.findall(r'<DOCUMENT>', text, re.IGNORECASE)) > 1):
        format_name = 'sgml'
        blocks = _sgml_blocks(text, url)
        outlines, link_items, tables = [], [], []
    elif is_xml:
        format_name = 'xml'
        blocks = _xml_blocks(text, url)
        outlines, link_items, tables = [], [], []
    elif is_html:
        format_name = 'html'
        blocks, outlines, link_items, tables, excluded_metadata = _html_blocks(text, url)
    else:
        format_name = 'text'
        blocks = [{'kind': 'text', 'text': text, 'url': url}]
        outlines, link_items, tables = [], [], []
    warnings = ['encoding_loss'] if encoding['loss'] else []
    if excluded_metadata:
        warnings.append('nonbody_inline_xbrl_metadata_omitted_from_reader_original_preserved')
    if binary:
        warnings.append('unsupported_format')
    if any(item['kind'] == 'image' for item in link_items):
        warnings.append('image_content_not_extracted')
    if format_name == 'xml' and '<!DOCTYPE' in text:
        warnings.append('external_entities_not_expanded')
    data = {'version': 1, 'source': {'url': source.source['url'], 'sha256': store.put(source.body)},
            'dom': store.put(text.encode()), 'encoding': encoding,
            'warnings': warnings, 'format': format_name, 'status': 'unsupported' if binary else 'parsed', 'extraction_complete': not warnings,
            'blocks': blocks, 'tables': tables, 'links': link_items, 'outline': outlines}
    return DocumentSnapshot(store.save(data), data)


def parse_document(source, store):
    from edgar.exceptions import ParsingError

    if not isinstance(source.body, bytes) or not isinstance(source.source.get('url'), str):
        raise SecError('invalid_source', 'Source requires received bytes and an original URL.', 'Pass the received document body and source metadata.')
    key = store.put(source.body)
    if source.source.get('sha256', key) != key:
        raise SecError('source_mismatch', 'Source hash does not match received bytes.', 'Pass the source metadata belonging to these bytes.')
    try:
        return _parse_document(source, store)
    except SecError:
        raise
    except (ValueError, etree.LxmlError, ParsingError, RecursionError) as error:
        raise SecError('parse_failed', f'Document parsing failed ({type(error).__name__}); original bytes remain saved.', 'Inspect the original source URL; no empty result was substituted.') from None


def load_snapshot(store, snapshot_id):
    try:
        data = json.loads(store.get(snapshot_id))
        if data['version'] != 1 or not all(isinstance(data[k], list) for k in ('blocks', 'tables', 'links', 'outline')):
            raise ValueError
        store.get(data['source']['sha256'])
        store.get(data['dom'])
    except (ValueError, KeyError, TypeError):
        raise SecError('invalid_snapshot', 'Saved record is not a supported document snapshot.', 'Open the source again to create a document snapshot.') from None
    return DocumentSnapshot(snapshot_id, data)
