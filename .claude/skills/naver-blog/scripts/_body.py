"""Post HTML into text, and an honest account of how much of it survived.

The body is the only part of Naver Blog that is not JSON, so it is the only part that can
change shape without warning. Two things follow. Which container to read is decided by
looking for it rather than by trusting the editorversion attribute, because a document can
carry both containers and the attribute has been wrong. And every component is counted as
fully understood, reduced to text and images, or lost — that tally reaches the output, so
a summary of a shortened body cannot be written as though it were the whole post.
"""
from __future__ import annotations

import html as html_module
import json
import re
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser

from ._errors import NaverBlogError
from ._models import UNKNOWN, clean, stamp

VOID = {'br', 'img', 'hr', 'input', 'meta', 'link', 'source', 'area', 'base', 'col', 'embed', 'param'}
# Their text is never body text, but a script node's data-module attribute is where a video,
# an embed and a map keep everything worth reading, so the node itself is kept.
SKIP = {'script', 'style'}
BLOCK = {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'blockquote', 'section'}
# Every SmartEditor component carries exactly one family class alongside se-component.
FAMILY = re.compile(r'(?:^|\s)se-(?!component\b|section\b|module\b)([a-zA-Z]+)(?:\s|$)')


@dataclass
class Coverage:
    components: int = 0
    full: int = 0
    partial: int = 0
    empty: int = 0
    families: dict = field(default_factory=dict)
    unhandled: list = field(default_factory=list)

    @property
    def reduced(self):
        return self.partial + self.empty

    def label(self):
        if not self.components:
            return 'text[legacy]'
        if not self.reduced:
            return 'text[full]'
        return f'text[partial: {self.reduced} of {self.components} components reduced]'


@dataclass
class Body:
    blocks: list = field(default_factory=list)
    images: list = field(default_factory=list)
    links: list = field(default_factory=list)
    attachments: list = field(default_factory=list)
    coverage: Coverage = field(default_factory=Coverage)

    @property
    def text(self):
        return '\n'.join(block for block in self.blocks if block)

    def to_dict(self):
        return {'text': self.text, 'images': self.images, 'links': self.links,
                'attachments': self.attachments, 'coverage': asdict(self.coverage)}


@dataclass
class PostDoc:
    blog_id: str | None = None
    blog_no: str | None = None
    log_no: str | None = None
    viewer_id: str | None = None
    title: str = ''
    created_at: str | None = None
    category_no: str | None = None
    category_name: str | None = None
    # A list of tags, or "unknown" when the page carried no tag variable at all.
    tags: list | str = field(default_factory=list)
    comment_count: int | None = None
    open_type: str | None = None
    body: Body = field(default_factory=Body)

    def to_dict(self):
        payload = asdict(self)
        payload['body'] = self.body.to_dict()
        return payload


class Nodes(HTMLParser):
    """A minimal DOM: enough to find a container and own its top-level components."""

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.root = {'tag': 'root', 'attrs': {}, 'children': [], 'text': []}
        self.stack = [self.root]
        self.skipping = 0
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = {'tag': tag, 'attrs': dict(attrs), 'children': [], 'text': []}
        if not self.skipping:
            self.stack[-1]['children'].append(node)
        if tag in SKIP:
            self.skipping += 1
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if not self.skipping:
            self.stack[-1]['children'].append({'tag': tag, 'attrs': dict(attrs), 'children': [], 'text': []})

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skipping = max(0, self.skipping - 1)
        if tag in VOID:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]['tag'] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        # A script's own source is never body text, but the node stays for its attributes.
        if not self.skipping:
            self.stack[-1]['text'].append(data)

    def handle_entityref(self, name):
        self.handle_data(html_module.unescape('&' + name + ';'))

    def handle_charref(self, name):
        self.handle_data(html_module.unescape('&#' + name + ';'))


def classes(node):
    return set(str(node['attrs'].get('class') or '').split())


def find(node, predicate, *, into_components=True):
    """Depth-first search; stops descending into a component when ownership matters."""
    for child in node['children']:
        if predicate(child):
            yield child
        elif into_components or 'se-component' not in classes(child):
            yield from find(child, predicate, into_components=into_components)


def visible_text(node):
    if node['tag'] in SKIP:
        return ''
    parts = list(node['text'])
    for child in node['children']:
        if child['tag'] in SKIP:
            continue
        if child['tag'] == 'br':
            parts.append('\n')
        parts.append(visible_text(child))
        if child['tag'] in BLOCK:
            parts.append('\n')
    return ''.join(parts)


def tidy(value):
    value = re.sub(r'[^\S\n]+', ' ', html_module.unescape(value or ''))
    value = '\n'.join(line.strip() for line in value.split('\n'))
    return re.sub(r'\n{3,}', '\n\n', value).strip()


def image_url(node, enclosing=None):
    """data-lazy-src is the real image; src is a deliberately blurred placeholder.

    The link data that names the real file sits on the enclosing anchor, not on the img,
    so it is passed in rather than looked for on the wrong node.
    """
    attrs = node['attrs']
    for key in ('data-lazy-src', 'data-src'):
        if attrs.get(key):
            return attrs[key]
    for source in (attrs.get('data-linkdata'), enclosing):
        if source:
            try:
                value = json.loads(html_module.unescape(source)).get('src')
                if value:
                    return value
            except (ValueError, AttributeError):
                pass
    return attrs.get('src') or None


def module_data(node):
    for script in find(node, lambda child: bool(child['attrs'].get('data-module'))):
        try:
            return json.loads(html_module.unescape(script['attrs']['data-module']))
        except ValueError:
            # Broken module JSON reduces this one component; it does not fail the whole read.
            return None
    return None


def link_data(node):
    for child in find(node, lambda item: item['attrs'].get('data-linkdata')):
        try:
            return json.loads(html_module.unescape(child['attrs']['data-linkdata']))
        except ValueError:
            return None
    return None


def images_of(node, body, *, caption=None, enclosing=None):
    found = []
    enclosing = node['attrs'].get('data-linkdata') or enclosing
    for child in node['children']:
        if child['tag'] == 'img':
            url = image_url(child, enclosing)
            if url:
                body.images.append({'url': url, 'caption': caption})
                found.append(url)
        else:
            found += images_of(child, body, caption=caption, enclosing=enclosing)
    return found


def caption_of(node):
    for child in find(node, lambda item: 'se-caption' in classes(item)):
        text = tidy(visible_text(child))
        if text:
            return text
    return None


def links_of(node, body):
    for anchor in find(node, lambda child: child['tag'] == 'a'):
        href = anchor['attrs'].get('href') or ''
        if href.startswith(('http://', 'https://')):
            body.links.append({'url': href, 'text': tidy(visible_text(anchor)) or None})


def render_component(family, node, body):
    """Return (lines, quality). quality is 'full' when a family rule handled it."""
    if family in ('text', 'sectionTitle', 'documentTitle', 'quotation'):
        content = tidy(visible_text(node))
        if not content:
            return [], 'empty'
        if family == 'sectionTitle':
            return ['## ' + content.replace('\n', ' ')], 'full'
        if family == 'quotation':
            return ['> ' + content.replace('\n', ' ')], 'full'
        return [content], 'full'
    if family in ('image', 'imageStrip', 'imageGroup', 'sticker'):
        caption = caption_of(node)
        found = images_of(node, body, caption=caption)
        if family == 'sticker':
            return ['[sticker]'], 'full'
        if not found:
            return [], 'empty'
        return [f'[image: {caption}]' if caption else '[image]' for _ in found], 'full'
    if family == 'horizontalLine':
        return ['---'], 'full'
    if family == 'oglink':
        data = link_data(node)
        title = (data or {}).get('title') or tidy(visible_text(node))
        url = (data or {}).get('link') or (data or {}).get('url')
        links_of(node, body)
        return [f'link: {title} ({url})' if url else f'link: {title}'], 'full'
    if family == 'material':
        data = link_data(node) or {}
        kind = data.get('type') or 'material'
        title = data.get('title') or tidy(visible_text(node))
        url = data.get('link') or data.get('url')
        body.attachments.append({'kind': kind, 'title': title, 'url': url, 'thumbnail_url': None})
        return [f'[{kind}: {title} ({url})]' if url else f'[{kind}: {title}]'], 'full'
    if family == 'table':
        rows = []
        for row in find(node, lambda child: child['tag'] == 'tr'):
            cells = [tidy(visible_text(cell)).replace('\n', ' ')
                     for cell in find(row, lambda child: child['tag'] in ('td', 'th'))]
            if any(cells):
                rows.append(' | '.join(cells))
        return (rows, 'full') if rows else ([], 'empty')
    if family == 'placesMap':
        data = module_data(node) or {}
        name = data.get('name') or tidy(visible_text(node)).split('\n')[0]
        return ([f'[map: {name}]'], 'full') if name else ([], 'empty')
    if family == 'video':
        # A video component may carry only a thumbnail. Using that as the video URL would
        # hand back an image while calling it the video, so the url stays null instead.
        data = module_data(node) or {}
        title = data.get('title') or caption_of(node) or tidy(visible_text(node)).split('\n')[0] or 'video'
        url = data.get('videoUrl') or data.get('playUrl') or data.get('inputUrl')
        thumbnail = data.get('thumbnail') or data.get('thumbnailUrl')
        body.attachments.append({'kind': 'video', 'title': title, 'url': url,
                                 'thumbnail_url': thumbnail})
        return [f'[video: {title}]'], 'full'
    if family == 'oembed':
        # An oembed is a video, a social post or a map; naming it a video would be a guess.
        data = module_data(node) or {}
        url = data.get('inputUrl') or data.get('url')
        description = data.get('description') or data.get('title') or caption_of(node) or 'embed'
        body.attachments.append({'kind': 'embed', 'title': description, 'url': url,
                                 'thumbnail_url': data.get('thumbnailUrl')})
        return [f'[embed: {description} ({url})]' if url else f'[embed: {description}]'], 'full'
    # An unfamiliar family keeps whatever a general reading can save: text, images, links.
    content = tidy(visible_text(node))
    found = images_of(node, body)
    links_of(node, body)
    lines = ([content] if content else []) + ['[image]' for _ in found]
    return (lines, 'partial' if lines else 'empty')


def read_components(container, body):
    for node in find(container, lambda child: 'se-component' in classes(child), into_components=False):
        names = FAMILY.findall(str(node['attrs'].get('class') or ''))
        family = next((name for name in names if name != 'component'), None) or 'unknown'
        body.coverage.components += 1
        body.coverage.families[family] = body.coverage.families.get(family, 0) + 1
        lines, quality = render_component(family, node, body)
        setattr(body.coverage, quality, getattr(body.coverage, quality) + 1)
        if quality != 'full' and family not in body.coverage.unhandled:
            body.coverage.unhandled.append(family)
        body.blocks.extend(lines)


def read_legacy(container, body):
    """Pre-SmartEditor markup has no components: block boundaries are all there is to go on."""
    content = tidy(visible_text(container))
    if content:
        body.blocks.extend(content.split('\n'))
    images_of(container, body)
    links_of(container, body)


def variable(source, name):
    match = re.search(r'var\s+' + name + r'\s*=\s*("(?:\\.|[^"\\])*")', source)
    if not match:
        return None
    try:
        return json.loads(match[1])
    except ValueError:
        return None


def parse(source):
    """Post HTML in, PostDoc out. A pure function: it never touches the network or the disk."""
    if not isinstance(source, str) or not source.strip():
        raise NaverBlogError(6, 'The post page was empty.', error='envelope_drift')
    tree = Nodes(source)

    doc = PostDoc(blog_id=variable(source, 'blogId'), blog_no=variable(source, 'blogNo'),
                  viewer_id=variable(source, 'userId'), open_type=variable(source, 'openType'),
                  category_name=clean(variable(source, 'gsCategoryName')),
                  title=clean(variable(source, 'postTitle')) or '')
    property_node = next(find(tree.root, lambda node: node['attrs'].get('id') == '_post_property'), None)
    if property_node:
        attrs = property_node['attrs']
        doc.log_no = attrs.get('logno') or attrs.get('logNo') or doc.log_no
        doc.created_at = stamp(attrs.get('adddate'))
        doc.category_no = attrs.get('categoryno')
        count = attrs.get('commentcount')
        doc.comment_count = int(count) if str(count).isdigit() else None
        if not doc.title:
            doc.title = clean(attrs.get('browsertitle')) or ''
    if not doc.log_no:
        doc.log_no = re.search(r'logNo=(\d+)', source) and re.search(r'logNo=(\d+)', source)[1]

    # An absent tag variable means this reader could not find out, which is not "no tags".
    raw_tags = variable(source, 'gsTagName')
    if raw_tags is None:
        doc.tags = UNKNOWN
    else:
        doc.tags = [tag.strip() for tag in raw_tags.split(',') if tag.strip()]

    body = Body()
    container = next(find(tree.root, lambda node: 'se-main-container' in classes(node)), None)
    if container is not None and any(find(container, lambda node: 'se-component' in classes(node))):
        read_components(container, body)
    else:
        # editorversion has been wrong and both containers can coexist, so the fallback is
        # chosen by finding it, not by believing an attribute.
        legacy = next(find(tree.root, lambda node: node['attrs'].get('id') == 'viewTypeSelector'
                           or 'post_ct' in classes(node)), None)
        if legacy is None:
            raise NaverBlogError(6, 'The post page carried neither body container.',
                                 'Open the post in Aside once; the page layout may have changed.',
                                 error='envelope_drift')
        read_legacy(legacy, body)
        if not body.blocks and not body.images:
            raise NaverBlogError(6, 'The post body container held nothing this reader could extract.',
                                 'Open the post in Aside once; the page layout may have changed.',
                                 error='envelope_drift')
    doc.body = body
    return doc
