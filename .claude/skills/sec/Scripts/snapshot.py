"""Build immutable reading snapshots from already received SEC source bytes."""

import codecs
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from output import SecError

# Workiva fills layout cells with &#8203;. Python's \s does not match U+200B, so a layout cell
# reached storage as a truthy string that renders as nothing: 51% of NBIS blocks, and 78 of its
# 79 table headers. U+00A0, U+202F and U+2007 are already whitespace to \s and need no rule.
LAYOUT = '\u200b'

# The block numbering and the meaning of a block both changed when a table became one block, so
# a v1 position would silently cite a different passage. Old records are refused, not upgraded.
SNAPSHOT_VERSION = 2

BINARY_SIGNATURES = (b'%PDF-', b'\x89PNG', b'\xff\xd8', b'GIF87a', b'GIF89a')


def collapse(text):
    """Apply the whitespace rule alone, without judging whether anything is left."""
    return re.sub(r'\s+', ' ', text).strip()


def cell_text(raw):
    """Collapse whitespace, and report a run of only layout characters as no text at all.

    A U+200B mixed into a real value is kept: no measured document did that, so removing it
    would be a change with no evidence behind it.
    """
    value = collapse(raw)
    return '' if not value.strip(LAYOUT + ' ') else value


@dataclass
class SourceDocument:
    body: bytes
    source: dict
    headers: dict = field(default_factory=dict)


@dataclass
class DocumentSnapshot:
    id: str
    data: dict

    def table_entry(self, table):
        return {'table_id': table['table_id'], 'rows': table['original_rows'],
                'columns': len(table['kept_columns']),
                'position': f"{self.id[:10]}:{table['block']}:0", 'context': table['context'][:200]}

    def summary(self):
        return {'snapshot_id': self.id, 'source': self.data['source'], 'status': self.data['status'],
                'format': self.data['format'], 'blocks': len(self.data['blocks']),
                'table_count': len(self.data['tables']),
                'tables': [self.table_entry(table) for table in self.data['tables']],
                'encoding': self.data['encoding'],
                'known_extraction_limits': self.data['known_extraction_limits']}


def _decode(source):
    from bs4 import UnicodeDammit

    content_type = next((v for k, v in source.headers.items() if k.lower() == 'content-type'), '')
    header_match = re.search(r'charset=["\']?([^;"\'\s]+)', content_type, re.IGNORECASE)
    header_encoding = header_match.group(1) if header_match else None
    media = content_type.split(';', 1)[0].lower()
    binary = (source.body.startswith(BINARY_SIGNATURES) or media == 'application/pdf'
              or media.startswith('image/'))
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
    encoding = {'selected': selected, 'declared': declarations, 'inferred': not declarations,
                'conflict': any(normalized(v) != normalized(selected) for v in declarations),
                'loss': bool(decoded.contains_replacement_characters or '�' in text)}
    return text, encoding, media, binary, content_type


def _format(text, media, url):
    is_html = bool(re.search(r'<(?:html|body|div|p|table|h[1-6]|img|a|span|pre|ul|ol)(?:\s|>)',
                             text[:10000], re.IGNORECASE))
    html_document = bool(re.search(r'<html(?:\s|>)', text[:10000], re.IGNORECASE))
    # A single <DOCUMENT> wrapper around ordinary HTML is one filing's markup, not a multi
    # document submission; treating it as SGML loses the images and tables inside it.
    if re.search(r'<DOCUMENT>', text, re.IGNORECASE) and (
        not is_html or re.search(r'<SEC-HEADER>', text, re.IGNORECASE)
        or len(re.findall(r'<DOCUMENT>', text, re.IGNORECASE)) > 1
    ):
        return 'sgml'
    if (('xml' in media and media != 'application/xhtml+xml')
            or (urlsplit(url).path.lower().endswith('.xml') and media != 'text/html')
            or (text.lstrip().startswith('<?xml') and not html_document)):
        return 'xml'
    return 'html' if is_html else 'text'


def _xml_blocks(text, url):
    from lxml import etree

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
    from submission import split_documents

    blocks = []
    previous = 0
    for document in split_documents(text):
        if document['start'] > previous:
            blocks.append({'kind': 'text', 'text': text[previous:document['start']], 'url': url})
        blocks.append({'kind': 'document', 'text': text[document['start']:document['end']],
                       'sequence': document['sequence'], 'document_type': document['document_type'],
                       'filename': document['filename'], 'description': document['description'],
                       'url': url})
        previous = document['end']
    if previous < len(text):
        blocks.append({'kind': 'text', 'text': text[previous:], 'url': url})
    return blocks


def _build(source, store):
    text, encoding, media, binary, content_type = _decode(source)
    url = source.source['url']
    limits = ['encoding_loss'] if encoding['loss'] else []
    blocks, outline, links, tables = [], [], [], []

    if binary:
        name = 'pdf' if source.body.startswith(b'%PDF-') or media == 'application/pdf' else 'image'
        limits.append('unsupported_format')
    else:
        name = _format(text, media, url)
        if name == 'html':
            from markup import parse_html

            blocks, outline, links, tables, excluded = parse_html(text, url)
            if excluded:
                limits.append('inline_xbrl_metadata_excluded')
        elif name == 'xml':
            blocks = _xml_blocks(text, url)
            if '<!DOCTYPE' in text:
                limits.append('external_entities_not_expanded')
        elif name == 'sgml':
            blocks = _sgml_blocks(text, url)
        else:
            blocks = [{'kind': 'text', 'text': text, 'url': url}]
    if any(item['kind'] == 'image' for item in links):
        limits.append('image_content_not_extracted')

    data = {'version': SNAPSHOT_VERSION,
            'source': {'url': url, 'sha256': store.put(source.body),
                       'fetched_at': source.source.get('fetched_at'),
                       'content_type': content_type or None},
            'dom': store.put(text.encode()), 'encoding': encoding,
            'known_extraction_limits': limits, 'format': name,
            'status': 'unsupported' if binary else 'parsed',
            'blocks': blocks, 'tables': tables, 'links': links, 'outline': outline}
    return DocumentSnapshot(store.save(data), data)


def parse_document(source, store):
    from lxml import etree

    if not isinstance(source.body, bytes) or not isinstance(source.source.get('url'), str):
        raise SecError('invalid_source', 'Source requires received bytes and an original URL.',
                       'Pass the received document body and source metadata.')
    key = store.put(source.body)
    if source.source.get('sha256', key) != key:
        raise SecError('source_mismatch', 'Source hash does not match received bytes.',
                       'Pass the source metadata belonging to these bytes.')
    try:
        return _build(source, store)
    except SecError:
        raise
    except (ValueError, etree.LxmlError, RecursionError) as error:
        raise SecError('parse_failed',
                       f'Document parsing failed ({type(error).__name__}); original bytes remain saved.',
                       'Inspect the original source URL; no empty result was substituted.') from None


def load_snapshot(store, snapshot_id):
    if not re.fullmatch(r'[0-9a-f]{64}', snapshot_id or ''):
        raise SecError('invalid_snapshot', 'This is not a saved document snapshot identifier.',
                       'Use the snapshot_id returned by open, or open the source again.')
    try:
        data = json.loads(store.get(snapshot_id))
        version = data['version']
    except (ValueError, KeyError, TypeError):
        raise SecError('invalid_snapshot', 'Saved record is not a supported document snapshot.',
                       'Open the source again to create a document snapshot.') from None
    if version != SNAPSHOT_VERSION:
        # A v1 block number still resolves under v2, to different text. Refusing is the only way
        # the difference is visible.
        raise SecError('unsupported_snapshot_version',
                       f'This snapshot was saved in format {version}; this reader uses {SNAPSHOT_VERSION}.',
                       'Open the source again to create a snapshot in the current format.')
    try:
        if not all(isinstance(data[key], list) for key in ('blocks', 'tables', 'links', 'outline')):
            raise ValueError
        store.get(data['source']['sha256'])
        store.get(data['dom'])
    except (ValueError, KeyError, TypeError):
        raise SecError('invalid_snapshot', 'Saved record is not a supported document snapshot.',
                       'Open the source again to create a document snapshot.') from None
    return DocumentSnapshot(snapshot_id, data)
