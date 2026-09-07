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
# Elements that never end a paragraph, so an open <p> can still be found underneath them.
INLINE = {'span', 'b', 'strong', 'i', 'em', 'u', 's', 'a', 'font', 'small', 'sub', 'sup',
          'mark', 'code', 'abbr', 'cite', 'q', 'label', 'wbr'}
# Every SmartEditor component carries exactly one family class alongside se-component.
FAMILY = re.compile(r'(?:^|\s)se-(?!component\b|section\b|module\b)([a-zA-Z]+)(?:\s|$)')
# The families with a rule written for them; everything else goes through the general fallback.
KNOWN = {'text', 'sectionTitle', 'documentTitle', 'quotation', 'image', 'imageStrip', 'imageGroup',
         'sticker', 'horizontalLine', 'oglink', 'material', 'table', 'placesMap', 'video', 'oembed'}


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


def node(tag, attrs=None):
    # `parts` interleaves strings and child nodes in document order; `children` is the same
    # child list, kept separately only so searching does not have to filter strings.
    return {'tag': tag, 'attrs': dict(attrs or {}), 'children': [], 'parts': []}


class Nodes(HTMLParser):
    """A minimal DOM: enough to find a container, own its components, and keep word order.

    Two rules of real HTML matter here and neither is optional. Text and elements are kept
    interleaved, because "앞<strong>중간</strong>뒤" read as text-then-elements comes out as
    "앞뒤중간". And a <p> is closed by the next block-level tag, because Naver's older posts
    leave them open and treating that as nesting builds a stack thousands of levels deep.
    """

    # Tags whose end tag HTML lets you leave out; a new one of these closes the open one.
    # Naver's older posts rely on this, and treating it as nesting builds a stack deep
    # enough to overflow and puts two table cells inside each other.
    IMPLIED = {
        'p': {'p', 'div', 'section', 'article', 'ul', 'ol', 'li', 'table', 'tr', 'td', 'th',
              'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'pre', 'form', 'header',
              'footer', 'main', 'nav', 'aside', 'figure', 'figcaption'},
        'li': {'li'},
        'td': {'td', 'th', 'tr'},
        'th': {'td', 'th', 'tr'},
        'tr': {'tr'},
        'option': {'option'},
        'dd': {'dd', 'dt'},
        'dt': {'dd', 'dt'},
    }

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.root = node('root')
        self.stack = [self.root]
        self.skipping = 0
        self.feed(source)
        self.close()

    def _append(self, child):
        parent = self.stack[-1]
        parent['children'].append(child)
        parent['parts'].append(child)

    def _close_implied(self, tag):
        """Close the innermost element this tag implicitly ends, inline markup notwithstanding.

        `<p><span>one<p>two` leaves the p open under a span, so looking only at the top of
        the stack never closes it — and a page with a thousand of them nests a thousand deep.
        """
        for index in range(len(self.stack) - 1, 0, -1):
            open_tag = self.stack[index]['tag']
            if tag in self.IMPLIED.get(open_tag, ()):
                del self.stack[index:]
                return
            if open_tag not in INLINE:
                return

    def handle_starttag(self, tag, attrs):
        self._close_implied(tag)
        child = node(tag, attrs)
        if not self.skipping:
            self._append(child)
        if tag in SKIP:
            self.skipping += 1
        if tag not in VOID:
            self.stack.append(child)

    def handle_startendtag(self, tag, attrs):
        if not self.skipping:
            self._append(node(tag, attrs))

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skipping = max(0, self.skipping - 1)
        if tag in VOID:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]['tag'] == tag:
                del self.stack[index:]
                return
        # A stray closing tag with nothing open to match is discarded, not obeyed: obeying it
        # would close the body container and hide every component after it.

    def handle_data(self, data):
        # A script's own source is never body text, but the node stays for its attributes.
        if not self.skipping:
            self.stack[-1]['parts'].append(data)

    def handle_entityref(self, name):
        self.handle_data(html_module.unescape('&' + name + ';'))

    def handle_charref(self, name):
        self.handle_data(html_module.unescape('&#' + name + ';'))


def classes(item):
    return set(str(item['attrs'].get('class') or '').split())


def find(root, predicate, *, into_components=True):
    """Depth-first search, iteratively: post markup nests deeper than the stack allows."""
    stack = list(reversed(root['children']))
    while stack:
        child = stack.pop()
        if predicate(child):
            yield child
        elif into_components or 'se-component' not in classes(child):
            stack.extend(reversed(child['children']))


def visible_text(root):
    """Text in document order, with block boundaries as newlines. Iterative: markup nests deeply."""
    output = []
    stack = [root]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            output.append(item)
            continue
        if item['tag'] in SKIP:
            continue
        if item['tag'] == 'br':
            output.append('\n')
            continue
        after = '\n' if item['tag'] in BLOCK else ''
        if after:
            stack.append(after)
        for part in reversed(item['parts']):
            stack.append(part)
    return ''.join(output)


def tidy(value):
    """Normalize once. Entities are already resolved by the parser, so they are not undone again."""
    value = re.sub(r'[^\S\n]+', ' ', value or '')
    # Zero-width marks and the half-character Naver leaves when it truncates mid-emoji: a lone
    # surrogate cannot be encoded as UTF-8 and would fail the write rather than the read.
    value = re.sub(r'[\u200b-\u200d\ufeff]', '', value)
    value = re.sub('[\ud800-\udfff]', '', value)
    value = '\n'.join(line.strip() for line in value.split('\n'))
    return re.sub(r'\n{3,}', '\n\n', value).strip()


def image_url(item, enclosing=None):
    """data-lazy-src is the real image; src is a deliberately blurred placeholder.

    The link data that names the real file sits on the enclosing anchor, not on the img,
    so it is passed in rather than looked for on the wrong node.
    """
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


def module_data(root):
    """A module wraps its fields as {"type": ..., "data": {...}}; the fields are inside data."""
    for script in find(root, lambda child: bool(child['attrs'].get('data-module'))):
        try:
            payload = json.loads(script['attrs']['data-module'])
        except ValueError:
            # Broken module JSON reduces this one component; it does not fail the whole read.
            return None
        if not isinstance(payload, dict):
            return None
        # No flat module has ever been observed, so a payload without data is unreadable
        # rather than a module whose fields happen to sit one level up.
        data = payload.get('data')
        return data if isinstance(data, dict) else None
    return None


def link_data(root):
    for child in find(root, lambda item: item['attrs'].get('data-linkdata')):
        try:
            payload = json.loads(child['attrs']['data-linkdata'])
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def is_image(item):
    return item['tag'] == 'img'


def image_groups(item):
    """The smallest nodes that hold exactly one picture, so each caption stays with its own."""
    groups, stack = [], list(item['children'])
    while stack:
        child = stack.pop(0)
        pictures = sum(1 for _ in find(child, is_image)) + (1 if child['tag'] == 'img' else 0)
        if pictures == 1:
            groups.append(child)
        elif pictures > 1:
            stack = child['children'] + stack
    return groups


def images_of(root, body, *, caption=None, enclosing=None, skip=None):
    """Collect pictures in document order, iteratively, carrying the nearest link data down."""
    found = []
    stack = [(root, root['attrs'].get('data-linkdata') or enclosing)]
    while stack:
        item, link = stack.pop(0)
        if item['tag'] == 'img':
            url = image_url(item, link)
            if url and not (skip and url in skip):
                body.images.append({'url': url, 'caption': caption})
                found.append(url)
            continue
        inherited = item['attrs'].get('data-linkdata') or link
        stack = [(child, inherited) for child in item['children']] + stack
    return found


def caption_of(root):
    for child in find(root, lambda item: 'se-caption' in classes(item)):
        text = tidy(visible_text(child))
        if text:
            return text
    return None


def links_of(root, body):
    for anchor in find(root, lambda child: child['tag'] == 'a'):
        href = anchor['attrs'].get('href') or ''
        if href.startswith(('http://', 'https://')):
            body.links.append({'url': href, 'text': tidy(visible_text(anchor)) or None})


def render_component(family, item, body):
    """Return (lines, quality). quality is 'full' when a family rule handled it."""
    if family in ('text', 'sectionTitle', 'documentTitle', 'quotation'):
        content = tidy(visible_text(item))
        if not content:
            return [], 'empty'
        if family == 'sectionTitle':
            return ['## ' + content.replace('\n', ' ')], 'full'
        if family == 'quotation':
            return ['> ' + content.replace('\n', ' ')], 'full'
        return [content], 'full'
    if family in ('image', 'imageStrip', 'imageGroup', 'sticker'):
        if family == 'sticker':
            images_of(item, body)
            return ['[sticker]'], 'full'
        lines, before = [], len(body.images)
        # A group holds several pictures with a caption each; one caption for all of them
        # would attach the first picture's words to every other picture.
        groups = image_groups(item)
        # A group with its own caption keeps it; one without falls back to the component's,
        # which is where a single picture's caption lives.
        shared = caption_of(item) if len(groups) <= 1 else None
        for group in (groups or [item]):
            caption = caption_of(group) or shared
            for _ in images_of(group, body, caption=caption):
                lines.append(f'[image: {caption}]' if caption else '[image]')
        return (lines, 'full') if len(body.images) > before else ([], 'empty')
    if family == 'horizontalLine':
        return ['---'], 'full'
    if family == 'oglink':
        data = link_data(item)
        title = (data or {}).get('title') or tidy(visible_text(item))
        url = (data or {}).get('link') or (data or {}).get('url')
        images_of(item, body, caption=title)
        links_of(item, body)
        return [f'link: {title} ({url})' if url else f'link: {title}'], 'full'
    if family == 'material':
        data = link_data(item) or {}
        kind = data.get('type') or 'material'
        title = data.get('title') or tidy(visible_text(item))
        url = data.get('link') or data.get('url')
        # A book or film card carries its cover; it belongs to this component, not to nothing.
        images_of(item, body, caption=title)
        body.attachments.append({'kind': kind, 'title': title, 'url': url, 'thumbnail_url': None})
        return [f'[{kind}: {title} ({url})]' if url else f'[{kind}: {title}]'], 'full'
    if family == 'table':
        rows = []
        for row in find(item, lambda child: child['tag'] == 'tr'):
            cells = [tidy(visible_text(cell)).replace('\n', ' ')
                     for cell in find(row, lambda child: child['tag'] in ('td', 'th'))]
            if any(cells):
                rows.append(' | '.join(cells))
        return (rows, 'full') if rows else ([], 'empty')
    if family == 'placesMap':
        data = module_data(item) or {}
        name = data.get('name') or tidy(visible_text(item)).split('\n')[0]
        return ([f'[map: {name}]'], 'full') if name else ([], 'partial')
    if family == 'video':
        # A video component may carry only a thumbnail. Using that as the video URL would
        # hand back an image while calling it the video, so the url stays null instead.
        data = module_data(item)
        if data is None:
            return ([f'[video: {caption_of(item) or "video"}]'], 'partial')
        meta = data.get('mediaMeta') if isinstance(data.get('mediaMeta'), dict) else {}
        title = (meta.get('title') or data.get('title') or caption_of(item)
                 or tidy(visible_text(item)).split('\n')[0] or 'video')
        url = data.get('videoUrl') or data.get('playUrl') or data.get('inputUrl')
        thumbnail = data.get('thumbnail') or data.get('thumbnailUrl')
        body.attachments.append({'kind': 'video', 'title': title, 'url': url,
                                 'thumbnail_url': thumbnail})
        return [f'[video: {title}]'], 'full'
    if family == 'oembed':
        # An oembed is a video, a social post or a map; naming it a video would be a guess.
        data = module_data(item)
        if data is None:
            return (['[embed]'], 'partial')
        url = data.get('inputUrl') or data.get('url')
        description = data.get('description') or data.get('title') or caption_of(item) or 'embed'
        body.attachments.append({'kind': 'embed', 'title': description, 'url': url,
                                 'thumbnail_url': data.get('thumbnailUrl')})
        return [f'[embed: {description} ({url})]' if url else f'[embed: {description}]'], 'full'
    # An unfamiliar family keeps whatever a general reading can save: text, images, links.
    content = tidy(visible_text(item))
    before = len(body.links)
    found = images_of(item, body)
    links_of(item, body)
    lines = ([content] if content else []) + ['[image]' for _ in found]
    saved = bool(lines) or len(body.links) > before
    return (lines, 'partial' if saved else 'empty')


def read_components(container, body):
    for component in find(container, lambda child: 'se-component' in classes(child),
                          into_components=False):
        names = FAMILY.findall(str(component['attrs'].get('class') or ''))
        family = next((name for name in names if name != 'component'), None) or 'unknown'
        body.coverage.components += 1
        body.coverage.families[family] = body.coverage.families.get(family, 0) + 1
        # Owning a nested component means reading it too. A rule that saw a component's text
        # but not the pictures inside it has reduced that component, however sure the rule was.
        present = sum(1 for _ in find(component, is_image))
        nested = list(find(component, lambda child: 'se-component' in classes(child)))
        before = len(body.images)
        lines, quality = render_component(family, component, body)
        taken = len(body.images) - before
        unread = [tidy(visible_text(child)) for child in nested]
        missing = [content for content in unread if content and content not in '\n'.join(lines)]
        modules = any(True for _ in find(component, lambda child: bool(child['attrs'].get('data-module'))))
        if taken < present or missing or (nested and modules):
            # Whatever the owner's rule did not reach is salvaged, and the tally says so:
            # a video inside a text component is content, not a detail of the text.
            for _ in images_of(component, body, skip={image['url'] for image in body.images[before:]}):
                lines.append('[image]')
            lines.extend(missing)
            for child in nested:
                data = module_data(child)
                if data:
                    label = (data.get('mediaMeta') or {}).get('title') or data.get('description') \
                        or data.get('inputUrl') or 'media'
                    lines.append(f'[media: {label}]')
                    body.attachments.append({'kind': 'media', 'title': label,
                                             'url': data.get('inputUrl'),
                                             'thumbnail_url': data.get('thumbnail')})
            quality = 'partial'
        if (quality == 'empty' and family in KNOWN and not tidy(visible_text(component))
                and not present and not nested and not modules):
            # A known family holding literally nothing is a spacer, not something this reader
            # missed. Anything with a child component or a module in it gets no such benefit.
            quality = 'full'
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
    property_node = next(find(tree.root, lambda item: item['attrs'].get('id') == '_post_property'), None)
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
    container = next(find(tree.root, lambda item: 'se-main-container' in classes(item)), None)
    if container is not None and any(find(container, lambda item: 'se-component' in classes(item))):
        read_components(container, body)
    else:
        # editorversion has been wrong and both containers can coexist, so the fallback is
        # chosen by finding it, not by believing an attribute.
        legacy = next(find(tree.root, lambda item: item['attrs'].get('id') == 'viewTypeSelector'
                           or 'post_ct' in classes(item)), None)
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
