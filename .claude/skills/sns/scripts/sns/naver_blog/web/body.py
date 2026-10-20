"""Post HTML into text, and an honest account of how much of it survived.

The body is the only part of Naver Blog that is not JSON, so it is the part that can change shape without warning.
Which container to read is decided by looking for it rather than by trusting the editorversion attribute, because a
page can carry both containers. Every SmartEditor component is counted as read in full, reduced to its text and
pictures, or lost; that tally reaches the output, so a summary of a shortened body cannot pass for the whole post.
Pictures are numbered in document order (images <post> N fetches one), and every link keeps its host and, for the
commercial link hosts, its id.
"""
from __future__ import annotations

import html as html_module
import json
import re
from dataclasses import dataclass, field, fields
from html.parser import HTMLParser
from urllib.parse import urlsplit

from sns.errors import SnsError

from sns.naver_blog.web.records import UNKNOWN, clean, stamp

VOID = {'br', 'img', 'hr', 'input', 'meta', 'link', 'source', 'area', 'base', 'col', 'embed', 'param', 'wbr'}
# Their text is never body text, but a script's data-module attribute is where a video, an embed and a map keep
# everything worth reading, so the node itself is kept.
SKIP = {'script', 'style'}
BLOCK = {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'blockquote', 'section'}
CELL = {'td', 'th'}
# Elements that never end a paragraph, so an open <p> can still be found underneath them.
INLINE = {'span', 'b', 'strong', 'i', 'em', 'u', 's', 'a', 'font', 'small', 'sub', 'sup', 'mark', 'code', 'abbr',
          'cite', 'q', 'label'}
FAMILY = re.compile(r'(?:^|\s)se-(?!component\b|section\b|module\b|l-)([a-zA-Z]+)(?:\s|$)')
KNOWN = {'text', 'sectionTitle', 'documentTitle', 'quotation', 'image', 'imageStrip', 'imageGroup', 'sticker',
         'horizontalLine', 'oglink', 'material', 'table', 'placesMap', 'video', 'oembed'}
_TITLE_SUFFIX = re.compile(r'\s*:\s*네이버\s*블로그\s*$')
# Commercial link hosts whose path carries an id worth comparing across posts.
_LINK_IDS = {'mkt.shopping.naver.com': r'/link/([A-Za-z0-9]+)', 'link.coupang.com': r'/a/([A-Za-z0-9]+)',
             'coupa.ng': r'/([A-Za-z0-9]+)$', 'naver.me': r'/([A-Za-z0-9]+)$',
             'brandconnect.naver.com': r'/((?:affiliates/)?[A-Za-z0-9]+(?:/[A-Za-z0-9]+)?)'}


@dataclass
class Coverage:
    components: int = 0
    full: int = 0
    partial: int = 0
    empty: int = 0
    families: dict = field(default_factory=dict)
    unhandled: list = field(default_factory=list)

    @property
    def label(self):
        if not self.components:
            return 'text[legacy]'
        reduced = self.partial + self.empty
        return 'text[full]' if not reduced else f'text[partial: {reduced} of {self.components} components reduced]'

    def to_dict(self):
        return {'components': self.components, 'full': self.full, 'partial': self.partial, 'empty': self.empty,
                'label': self.label, 'families': dict(self.families), 'unhandled': list(self.unhandled)}


@dataclass
class PostDoc:
    kind: str = 'post'
    id: str | None = None
    url: str | None = None
    created_at: str | None = None
    blog_id: str | None = None
    blog_no: str | None = None
    log_no: str | None = None
    title: str = ''
    category_no: str | None = None
    category_name: str | None = None
    tags: list | str = field(default_factory=list)   # a list, or "unknown" when the page carried no tag variable
    comment_count: int | None = None
    like_count: int | None = None     # the live reaction count, read apart from the page
    reactions: dict | None = None     # {reaction type: count}, read apart from the page
    own_money: bool | None = None
    own_money_cards: list = field(default_factory=list)
    has_product: bool | None = None
    product_count: int | None = None
    lines: list = field(default_factory=list)
    images: list = field(default_factory=list)
    links: list = field(default_factory=list)
    attachments: list = field(default_factory=list)
    coverage: Coverage = field(default_factory=Coverage)
    viewer_id: str | None = None   # the logged-in viewer, for the session only; never part of the record

    @property
    def text(self):
        return '\n'.join(self.lines)

    def to_dict(self):
        record = {f.name: getattr(self, f.name) for f in fields(self) if f.name not in ('viewer_id', 'coverage')}
        return {**record, 'tags': self.tags if isinstance(self.tags, str) else list(self.tags),
                'own_money_cards': list(self.own_money_cards), 'lines': list(self.lines),
                'images': list(self.images), 'links': list(self.links), 'attachments': list(self.attachments),
                'coverage': self.coverage.to_dict()}


def _node(tag, attrs=None):
    # parts interleaves strings and child nodes in document order; children holds the nodes alone, for searching.
    return {'tag': tag, 'attrs': dict(attrs or {}), 'children': [], 'parts': []}


class _Tree(HTMLParser):
    """A minimal DOM that keeps word order ("앞<strong>중간</strong>뒤" stays 앞중간뒤) and closes the elements HTML lets
    a page leave open — Naver's older posts rely on it, and nesting them builds a stack thousands deep."""

    IMPLIED = {
        'p': {'p', 'div', 'section', 'article', 'ul', 'ol', 'li', 'table', 'tr', 'td', 'th', 'blockquote', 'h1', 'h2',
              'h3', 'h4', 'h5', 'h6', 'hr', 'pre', 'form', 'header', 'footer', 'main', 'nav', 'aside', 'figure',
              'figcaption'},
        'li': {'li'}, 'td': {'td', 'th', 'tr'}, 'th': {'td', 'th', 'tr'}, 'tr': {'tr'}, 'option': {'option'},
        'dd': {'dd', 'dt'}, 'dt': {'dd', 'dt'},
    }

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.root = _node('root')
        self.stack = [self.root]
        self.skipping = 0
        self.feed(source)
        self.close()

    def _append(self, child):
        self.stack[-1]['children'].append(child)
        self.stack[-1]['parts'].append(child)

    def _close_implied(self, tag):
        """Close every element `tag` implicitly ends, inline markup notwithstanding: a new <tr> over [tr, td] closes
        the cell and then the row."""
        while True:
            for index in range(len(self.stack) - 1, 0, -1):
                open_tag = self.stack[index]['tag']
                if tag in self.IMPLIED.get(open_tag, ()):
                    del self.stack[index:]
                    break
                if open_tag not in INLINE:
                    return
            else:
                return

    def handle_starttag(self, tag, attrs):
        self._close_implied(tag)
        child = _node(tag, attrs)
        if not self.skipping:
            self._append(child)
        if tag in SKIP:
            self.skipping += 1
        if tag not in VOID:
            self.stack.append(child)

    def handle_startendtag(self, tag, attrs):
        if not self.skipping:
            self._append(_node(tag, attrs))

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skipping = max(0, self.skipping - 1)
        if tag in VOID:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]['tag'] == tag:
                del self.stack[index:]
                return
        # A stray closing tag is ignored: obeying it would close the body and hide every component after it.

    def handle_data(self, data):
        if not self.skipping:
            self.stack[-1]['parts'].append(data)

    def handle_entityref(self, name):
        self.handle_data(html_module.unescape('&' + name + ';'))

    def handle_charref(self, name):
        self.handle_data(html_module.unescape('&#' + name + ';'))


def _classes(item):
    return set(str(item['attrs'].get('class') or '').split())


def _find(root, predicate, *, into_components=True):
    """Depth-first, iteratively: post markup nests deeper than the stack allows."""
    stack = list(reversed(root['children']))
    while stack:
        child = stack.pop()
        if predicate(child):
            yield child
        elif into_components or 'se-component' not in _classes(child):
            stack.extend(reversed(child['children']))


def _text(root, image=None):
    """Text in document order, block boundaries as newlines, table cells apart; image(node) names a picture in place."""
    output, stack = [], [root]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            output.append(item)
            continue
        tag = item['tag']
        if tag in SKIP:
            continue
        if tag == 'br':
            output.append('\n')
            continue
        if tag == 'img':
            marker = image(item) if image else None
            if marker:
                output.append('\n' + marker + '\n')
            continue
        if tag in BLOCK:
            stack.append('\n')
        elif tag in CELL:
            stack.append(' ')
        stack.extend(reversed(item['parts']))
    return ''.join(output)


def _tidy(value):
    value = re.sub(r'[^\S\n]+', ' ', value or '')
    value = re.sub('[​-‍﻿]', '', value)
    value = re.sub('[\ud800-\udfff]', '', value)
    value = '\n'.join(line.strip() for line in value.split('\n'))
    return re.sub(r'\n{3,}', '\n\n', value).strip()


def _json_attr(item, name):
    try:
        value = json.loads(item['attrs'].get(name) or '')
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _image_url(item, enclosing=None):
    """data-lazy-src is the real picture; src is a blurred placeholder; the enclosing anchor's link data names it too."""
    attrs = item['attrs']
    for key in ('data-lazy-src', 'data-src'):
        if attrs.get(key):
            return attrs[key]
    for source in (attrs.get('data-linkdata'), enclosing):
        if source:
            try:
                payload = json.loads(source)
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get('src'):
                return payload['src']
    return attrs.get('src') or None


def _module_data(root):
    """A module wraps its fields as {"type": ..., "data": {...}}; broken JSON reduces this one component only."""
    for script in _find(root, lambda child: bool(child['attrs'].get('data-module'))):
        payload = _json_attr(script, 'data-module')
        data = payload.get('data') if payload else None
        return data if isinstance(data, dict) else None
    return None


def link_of(url, text=None):
    """A link as the record keeps it: the whole URL, its host, and the id a commercial link host puts in its path."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
    except ValueError:
        host, parts = '', None
    pattern = _LINK_IDS.get(host)
    match = re.match(pattern, parts.path) if pattern and parts else None
    return {'url': url, 'text': text or None, 'host': host or None, 'link_id': match[1] if match else None}


class _Reader:
    def __init__(self, doc):
        self.doc = doc

    def picture(self, url, caption=None, kind='photo'):
        number = len(self.doc.images) + 1
        try:
            host = (urlsplit(url).hostname or '').lower() or None
        except ValueError:
            host = None
        self.doc.images.append({'n': number, 'url': url, 'caption': caption, 'kind': kind, 'host': host})
        return number

    def label(self, number, caption=None):
        """[image N: caption], naming the host of a picture served from outside Naver (a campaign platform's
        banner is one)."""
        host = self.doc.images[number - 1].get('host') or ''
        naver = host == 'pstatic.net' or host.endswith('.pstatic.net')
        offsite = '' if naver else f' — hosted at {host or "?"}, outside Naver'
        return f'[image {number}' + (f': {caption}' if caption else '') + offsite + ']'

    def pictures(self, root, *, caption=None, kind='photo', skip=()):
        """Number every picture under root in document order, carrying the nearest anchor's link data down."""
        numbers, stack = [], [(root, root['attrs'].get('data-linkdata'))]
        while stack:
            item, link = stack.pop(0)
            if item['tag'] == 'img':
                url = _image_url(item, link)
                if url and url not in skip:
                    numbers.append(self.picture(url, caption, kind))
                continue
            inherited = item['attrs'].get('data-linkdata') or link
            stack = [(child, inherited) for child in item['children']] + stack
        return numbers

    def links(self, root):
        for anchor in _find(root, lambda child: child['tag'] == 'a'):
            href = anchor['attrs'].get('href') or ''
            if href.startswith(('http://', 'https://')):
                self.doc.links.append(link_of(href, _tidy(_text(anchor)) or None))

    def caption(self, root):
        for child in _find(root, lambda item: 'se-caption' in _classes(item)):
            text = _tidy(_text(child))
            if text:
                return text
        return None

    def component(self, family, item):
        """(lines, quality): quality is full when a rule written for the family read it."""
        if family in ('text', 'sectionTitle', 'documentTitle', 'quotation'):
            content = _tidy(_text(item))
            if not content:
                return [], 'empty'
            prefix = {'sectionTitle': '## ', 'quotation': '> '}.get(family)
            return ([prefix + content.replace('\n', ' ')] if prefix else [content]), 'full'
        if family == 'sticker':
            return [f'[sticker: image {n}]' for n in self.pictures(item, kind='sticker')] or ['[sticker]'], 'full'
        if family in ('image', 'imageStrip', 'imageGroup'):
            lines, groups = [], self.groups(item)
            shared = self.caption(item) if len(groups) <= 1 else None   # one caption must not label every picture
            for group in groups or [item]:
                caption = self.caption(group) or shared
                for n in self.pictures(group, caption=caption):
                    lines.append(self.label(n, caption))
            return (lines, 'full') if lines else ([], 'empty')
        if family == 'horizontalLine':
            return ['---'], 'full'
        if family == 'oglink':
            data = _json_attr(next(_find(item, lambda c: bool(c['attrs'].get('data-linkdata'))), {'attrs': {}}),
                              'data-linkdata') or {}
            title = data.get('title') or _tidy(_text(item))
            url = data.get('link') or data.get('url')
            line = f'link: {title} ({url})' if url else f'link: {title}'
            numbers = self.pictures(item, caption=title, kind='thumbnail')
            return [line + ''.join(f' · image {n}' for n in numbers)], 'full'
        if family == 'material':
            data = _json_attr(next(_find(item, lambda c: bool(c['attrs'].get('data-linkdata'))), {'attrs': {}}),
                              'data-linkdata') or {}
            kind, title = data.get('type') or 'material', data.get('title') or _tidy(_text(item))
            url = data.get('link') or data.get('url')
            numbers = self.pictures(item, caption=title, kind='cover')
            self.doc.attachments.append({'kind': kind, 'title': title, 'url': url, 'thumbnail_url': None})
            line = f'[{kind}: {title} ({url})]' if url else f'[{kind}: {title}]'
            return [line + ''.join(f' · image {n}' for n in numbers)], 'full'
        if family == 'table':
            rows = []
            for row in _find(item, lambda child: child['tag'] == 'tr'):
                cells = [_tidy(_text(cell)).replace('\n', ' ') for cell in _find(row, lambda c: c['tag'] in CELL)]
                if any(cells):
                    rows.append(' | '.join(cells))
            return (rows, 'full') if rows else ([], 'empty')
        if family == 'placesMap':
            link = next(_find(item, lambda c: bool(c['attrs'].get('data-linkdata'))), None)
            data = {**(_module_data(item) or {}), **((_json_attr(link, 'data-linkdata') or {}) if link else {})}
            name = data.get('name') or _tidy(_text(item)).split('\n')[0]
            if not name:
                return [], 'partial'
            place = name + (f' — {data["address"]}' if data.get('address') else '')
            numbers = self.pictures(item, caption=name, kind='map')
            return [f'[map: {place}' + ''.join(f' · image {n}' for n in numbers) + ']'], 'full'
        if family == 'video':
            # A video module may carry only a thumbnail: the url stays null rather than call the thumbnail the video.
            data = _module_data(item)
            if data is None:
                return [f'[video: {self.caption(item) or "video"}]'], 'partial'
            meta = data.get('mediaMeta') if isinstance(data.get('mediaMeta'), dict) else {}
            title = meta.get('title') or data.get('title') or self.caption(item) or 'video'
            self.doc.attachments.append({'kind': 'video', 'title': title,
                                         'url': data.get('videoUrl') or data.get('playUrl') or data.get('inputUrl'),
                                         'thumbnail_url': data.get('thumbnail') or data.get('thumbnailUrl')})
            return [f'[video: {title}]'], 'full'
        if family == 'oembed':
            # An oembed is a video, a social post or a map: calling it a video would be a guess.
            data = _module_data(item)
            if data is None:
                return ['[embed]'], 'partial'
            url = data.get('inputUrl') or data.get('url')
            title = data.get('description') or data.get('title') or self.caption(item) or 'embed'
            self.doc.attachments.append({'kind': 'embed', 'title': title, 'url': url,
                                         'thumbnail_url': data.get('thumbnailUrl')})
            return [f'[embed: {title} ({url})]' if url else f'[embed: {title}]'], 'full'
        card = next(_find(item, lambda c: 'not_sponsored_component' in _classes(c)), None)
        if family == 'custom' and card is not None:
            return [self.own_money_card(card)], 'full'
        # An unfamiliar family keeps what a general reading saves: its text and its pictures.
        content = _tidy(_text(item))
        lines = ([content] if content else []) + [self.label(n) for n in self.pictures(item)]
        return lines, 'partial' if lines else 'empty'

    def own_money_card(self, card):
        """Naver's 내돈내산 인증 card: a purchase or visit Naver recorded, which the writer attached."""
        def part(name):
            node = next(_find(card, lambda c: name in _classes(c)), None)
            return _tidy(_text(node)).replace('\n', ' ') if node else None
        link = next(_find(card, lambda c: c['tag'] == 'a' and 'link' in _classes(c)), None)
        url = link['attrs'].get('href') if link else None
        kinds = re.findall(r"buy_with_my_own_money_(\w+?)'", ' '.join(str(c['attrs'].get('onclick') or '')
                                                                    for c in _find(card, lambda c: True)))
        kind = next((k for k in kinds if not k.endswith('_more')), None)
        date = re.sub(r'\s+', ' ', (part('date') or '').replace('.구', '. 구')).strip() or None
        entry = {'kind': kind, 'category': part('category'), 'title': part('title'), 'date': date, 'url': url}
        self.doc.own_money_cards.append(entry)
        self.doc.own_money = True
        return '[own-money card: ' + ' · '.join(v for v in (entry['category'], entry['title'], date, url) if v) + ']'

    @staticmethod
    def groups(item):
        """The smallest nodes holding exactly one picture, so each caption stays with its own picture."""
        groups, stack = [], list(item['children'])
        while stack:
            child = stack.pop(0)
            count = sum(1 for _ in _find(child, lambda c: c['tag'] == 'img')) + (child['tag'] == 'img')
            if count == 1:
                groups.append(child)
            elif count > 1:
                stack = child['children'] + stack
        return groups

    def components(self, container):
        coverage = self.doc.coverage
        for component in _find(container, lambda child: 'se-component' in _classes(child), into_components=False):
            family = next(iter(FAMILY.findall(str(component['attrs'].get('class') or ''))), None) or 'unknown'
            coverage.components += 1
            coverage.families[family] = coverage.families.get(family, 0) + 1
            present = sum(1 for _ in _find(component, lambda c: c['tag'] == 'img'))
            nested = list(_find(component, lambda c: 'se-component' in _classes(c)))
            modules = any(True for _ in _find(component, lambda c: bool(c['attrs'].get('data-module'))))
            before = len(self.doc.images)
            lines, quality = self.component(family, component)
            missing = [t for t in (_tidy(_text(child)) for child in nested) if t and t not in '\n'.join(lines)]
            if len(self.doc.images) - before < present or missing or (nested and modules):
                # What the family's rule did not reach is salvaged, and the tally says so.
                taken = {image['url'] for image in self.doc.images[before:]}
                lines += [self.label(n) for n in self.pictures(component, skip=taken)]
                lines += missing
                for child in nested:
                    data = _module_data(child)
                    if data:
                        label = ((data.get('mediaMeta') or {}).get('title') or data.get('description')
                                 or data.get('inputUrl') or 'media')
                        lines.append(f'[media: {label}]')
                        self.doc.attachments.append({'kind': 'media', 'title': label, 'url': data.get('inputUrl'),
                                                     'thumbnail_url': data.get('thumbnail')})
                quality = 'partial'
            if (quality == 'empty' and family in KNOWN and not _tidy(_text(component)) and not present and not nested
                    and not modules):
                quality = 'full'   # a known family holding nothing is a spacer, not something this reader missed
            setattr(coverage, quality, getattr(coverage, quality) + 1)
            if quality != 'full' and family not in coverage.unhandled:
                coverage.unhandled.append(family)
            self.links(component)
            self.doc.lines += lines

    def legacy(self, container):
        """Pre-SmartEditor markup has no components: block boundaries and pictures in place are all there is."""
        def marker(item):
            url = _image_url(item)
            return self.label(self.picture(url)) if url else None
        self.doc.lines += [line for line in _tidy(_text(container, marker)).split('\n') if line]
        self.links(container)


_QUOTED = r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')"""


def _unquote(token):
    body = token[1:-1]
    if token[0] == "'":
        body = body.replace("\\'", "'").replace('"', '\\"')
    try:
        return json.loads('"' + body + '"')
    except ValueError:
        return body


def _variable(source, name):
    """The value of `var name = …;` in the forms post pages use: a quoted string (either quote), a number, true/false,
    or a comparison of two quoted strings ('false' === 'true'), read as its boolean result."""
    head = re.search(r'var\s+' + re.escape(name) + r'\s*=\s*', source)
    if not head:
        return None
    rest = source[head.end():]
    comparison = re.match(_QUOTED + r'\s*===?\s*' + _QUOTED, rest)
    if comparison:
        return _unquote(comparison[1]) == _unquote(comparison[2])
    quoted = re.match(_QUOTED, rest)
    if quoted:
        return _unquote(quoted[1])
    bare = re.match(r'(-?\d+|true|false)\s*[;\n]', rest)
    if not bare:
        return None
    return int(bare[1]) if bare[1].lstrip('-').isdigit() else bare[1] == 'true'


def _text_of(value):
    return None if value is None or isinstance(value, bool) else str(value)


def _flag(value):
    if isinstance(value, bool):
        return value
    if value in ('true', 'false'):
        return value == 'true'
    return None


def parse(source, *, blog_id=None, log_no=None):
    """Post HTML in, PostDoc out; pure. A page for another post number is refused; another blog id beside the right
    post number is Naver resolving a domain address, and the page's id wins."""
    if not isinstance(source, str) or not source.strip():
        raise SnsError('failed', 'The post page was empty.', 'Retry later; run doctor if it repeats.', reason='drift')
    tree = _Tree(source)
    doc = PostDoc(blog_id=_text_of(_variable(source, 'blogId')) or blog_id, blog_no=_text_of(_variable(source, 'blogNo')),
                  viewer_id=_text_of(_variable(source, 'userId')),
                  category_name=clean(_text_of(_variable(source, 'gsCategoryName'))),
                  title=_TITLE_SUFFIX.sub('', clean(_text_of(_variable(source, 'postTitle'))) or ''),
                  # isBuyWithMyOwnMoneyPost stays false beside a 내돈내산 인증 card, so only the card counts.
                  own_money=False,
                  has_product=_flag(_variable(source, 'hasProduct')))
    count = _variable(source, 'productCount')
    doc.product_count = int(count) if str(count).isdigit() else None
    found = next(_find(tree.root, lambda item: item['attrs'].get('id') == '_post_property'), None)
    attrs = found['attrs'] if found else {}
    doc.log_no = attrs.get('logno') or (re.search(r'logNo=(\d+)', source) or [None, None])[1]
    doc.created_at = stamp(attrs.get('adddate'))
    doc.category_no = attrs.get('categoryno')
    comments = attrs.get('commentcount')
    doc.comment_count = int(comments) if str(comments).isdigit() else None
    if not doc.title:
        doc.title = _TITLE_SUFFIX.sub('', clean(attrs.get('browsertitle')) or '')
    if log_no is not None and doc.log_no and str(doc.log_no) != str(log_no):
        raise SnsError('failed', f'That page is post {doc.log_no}, not {log_no}.',
                       'Open the URL in Aside and pass the post number it lands on.', reason='drift')
    doc.log_no = str(doc.log_no or log_no or '') or None
    if doc.blog_id and doc.log_no:
        doc.id, doc.url = f'post:{doc.blog_id}/{doc.log_no}', f'https://blog.naver.com/{doc.blog_id}/{doc.log_no}'
    tags = _variable(source, 'gsTagName')
    doc.tags = UNKNOWN if tags is None else [tag.strip() for tag in str(tags).split(',') if tag.strip()]
    reader = _Reader(doc)
    container = next(_find(tree.root, lambda item: 'se-main-container' in _classes(item)), None)
    if container is not None and any(_find(container, lambda item: 'se-component' in _classes(item))):
        reader.components(container)
    else:
        legacy = next(_find(tree.root, lambda item: item['attrs'].get('id') == 'viewTypeSelector'
                            or 'post_ct' in _classes(item)), None)
        if legacy is None:
            raise SnsError('failed', 'The post page carried neither body container.',
                           'Open the post in Aside once; the page layout may have changed.', reason='drift')
        reader.legacy(legacy)
        if not doc.lines and not doc.images:
            raise SnsError('failed', 'The post body held nothing this reader could extract.',
                           'Open the post in Aside once; the page layout may have changed.', reason='drift')
    return doc


NOTES = {
    '__doc__': 'One post read in full (post): its page, body, pictures and links.',
    'id': 'post:<blogId>/<logNo>', 'url': 'https://blog.naver.com/<blogId>/<logNo>',
    'created_at': 'KST minute',
    'like_count': 'the post\'s live reaction count (list surfaces can lag it); null when its section failed',
    'reactions': '{reaction type: count} (like, impressive, thanks ...); null when its section failed',
    'lines': 'the body as text lines in document order: [image N: caption], [sticker: image N], ## section titles, '
             '> quotes, link: cards, [map: …], [video: …], [embed: …]; never clipped',
    'images': '{n, url, caption, kind}: every picture in order (photo, sticker, cover, thumbnail); images <post> N saves '
              'one. A sticker can be a disclosure banner the text never states',
    'links': '{url, text, host, link_id}: every outbound link; link_id is the id a commission or marketing host puts in '
             'its path (mkt.shopping.naver.com/link/<id> is a seller\'s marketing link, link.coupang.com/a/<id> Coupang '
             'Partners, naver.me/<code> a short link, brandconnect.naver.com a creator\'s shopping-connect link)',
    'coverage': 'components and how many were read in full, reduced to text and pictures (partial), or yielded '
                'nothing (empty); label is text[full], text[partial: k of n components reduced] or text[legacy]. A '
                'summary of a reduced body says so',
    'tags': 'a list, or "unknown" when the page carried no tag variable (not the same as a post with no tags)',
    'own_money': 'true when the post carries Naver\'s 내돈내산 인증 card (a purchase or visit Naver recorded — a shopping '
                 'order, reservation, receipt or payment — that the writer attached; what search --own-money matches); '
                 'false when it carries none. The card proves a recorded purchase, not who paid for it',
    'own_money_cards': '{kind, category, title, date, url} of each such card',
    'has_product': 'the post carries Naver product cards', 'product_count': 'how many',
    'blog_no': 'the blog\'s internal number', 'comment_count': 'the page\'s own comment count',
}
