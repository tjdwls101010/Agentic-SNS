"""What the document did to make a passage stand out, and what that is evidence of.

Two layers. The observation layer is every block carrying an emphasis signal, with the signals
it was judged on. The navigation layer is the subset whose signals are strong enough to be
section boundaries. Nothing here becomes a heading level: the measured filings declare no
`<h1>`-`<h6>` at all, so a level would be invented rather than read.
"""

import re

from snapshot import LAYOUT

# A browser's default text size, used only to resolve a relative unit when nothing above it
# declared an absolute one.
DEFAULT_POINTS = 12.0
BOLD = 600
# Measured: Apple's body runs at 9pt and Microsoft's at 10pt, so "12pt or larger" calls every
# line of one document a heading and no line of the other. The ratio is against the document's
# own body size; 1.15 is the smallest step the measured filings actually use for a heading.
LARGER = 1.15
# A run of links is a contents row pointing at sections, not a section.
LINK_LIMIT = 0.8
# A size or capitalization signal describes the block only if it covers most of it.
COVERAGE = 0.8
# A body paragraph, long enough that its size is the document's running text rather than a label.
BODY_CHARS = 200

BASE = {'weight': 400, 'size': None, 'align': None, 'italic': False, 'underline': False,
        'heading': False, 'root': None}
# The <font size> scale, which is relative rather than absolute: 3 is the default size.
FONT_SIZES = {1: 0.63, 2: 0.82, 3: 1.0, 4: 1.13, 5: 1.5, 6: 2.0, 7: 3.0}
SECTION = re.compile(r'^\s*(item|part|note)\s+(\d+\s*[a-c]?|[ivx]+)\b', re.IGNORECASE)
WEIGHTS = {'bold': 700, 'bolder': 700, 'normal': 400, 'lighter': 400}
HEADING_TAGS = frozenset({'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})
BOLD_TAGS = frozenset({'b', 'strong'})
ITALIC_TAGS = frozenset({'i', 'em'})


def _points(value, inherited, root=None):
    match = re.fullmatch(r'\s*(\d*\.?\d+)\s*(pt|px|em|rem|%)\s*', value or '', re.IGNORECASE)
    if not match:
        return inherited
    amount, unit = float(match[1]), match[2].lower()
    if unit == 'pt':
        return amount
    if unit == 'px':
        return amount * 0.75
    if unit == 'rem':
        # rem is the root's size, not the parent's: inside a 20pt block, 1rem is still body size.
        return amount * (root or DEFAULT_POINTS)
    base = inherited if inherited else DEFAULT_POINTS
    return amount * base if unit == 'em' else amount / 100 * base


def restyle(node, tag, inherited):
    """The style in force inside this element, given the style in force outside it."""
    style = dict(inherited)
    if tag in BOLD_TAGS:
        style['weight'] = 700
    if tag in ITALIC_TAGS:
        style['italic'] = True
    if tag == 'u':
        style['underline'] = True
    if tag in HEADING_TAGS:
        style['weight'] = max(style['weight'], 700)
        style['heading'] = True
    if tag == 'font' and node.get('size'):
        # Unexercised by the measured filings, which declare no size attribute at all. The scale
        # is relative, so with nothing declared above it the base is the browser's own default,
        # which is what the reader would see.
        step = FONT_SIZES.get(_number(node.get('size').lstrip('+'), 3))
        if step is not None:
            style['size'] = (style['size'] or style['root'] or DEFAULT_POINTS) * step
    for declaration in (node.get('style') or '').split(';'):
        name, separator, value = declaration.partition(':')
        if not separator:
            continue
        name, value = name.strip().lower(), value.strip()
        if name == 'font-weight':
            style['weight'] = WEIGHTS.get(value.lower(), _number(value, style['weight']))
        elif name == 'font-size':
            style['size'] = _points(value, style['size'], style['root'])
            if tag == 'html':
                style['root'] = style['size']
        elif name == 'text-align':
            style['align'] = value.lower() or None
        elif name == 'font-style':
            style['italic'] = value.lower() in ('italic', 'oblique')
        elif name == 'text-decoration' or name == 'text-decoration-line':
            style['underline'] = 'underline' in value.lower()
    return style


def _number(value, fallback):
    try:
        return int(float(value))
    except ValueError:
        return fallback


class Signals:
    """Accumulate one block's emphasis evidence, one text fragment at a time.

    Counting per fragment is what keeps a parent and its child from both reporting the same
    characters: Microsoft splits a line into many nested spans, and double counting there would
    put bold_fraction above one and multiply the observation count.
    """

    def __init__(self):
        self.chars = self.bold = self.italic = self.underline = self.link = 0
        self.sizes = []
        self.aligns = {}
        self.heading = False
        self.emphasized = []

    def add(self, text, style, in_link):
        # A layout character is not a character the reader sees. Counting it made a row of
        # ordinary weight read as partly bold, and a fully bold row as half bold, wherever a
        # filing pads its layout with U+200B.
        text = text.replace(LAYOUT, '')
        count = len(text)
        if not count:
            return
        self.chars += count
        bold = style['weight'] >= BOLD or style['heading']
        if bold:
            self.bold += count
        if style['italic']:
            self.italic += count
        if style['underline']:
            self.underline += count
        # Emphasis is whatever the document did to set this run apart, not bold alone: one
        # measured filing marks every accounting note by underlining it at body weight and body
        # size, so a bold-only reading loses all eighteen of them.
        if bold or style['italic'] or style['underline']:
            self.emphasized.append(text)
        if in_link:
            self.link += count
        if style['size'] is not None:
            self.sizes.append((style['size'], count))
        if style['align']:
            self.aligns[style['align']] = self.aligns.get(style['align'], 0) + count
        self.heading = self.heading or style['heading']

    def observed(self, body_size):
        """Whether the document did anything to this block to set it apart."""
        larger = body_size and any(size > body_size for size, _ in self.sizes)
        return bool(self.chars) and bool(self.bold or self.italic or self.underline or self.heading or larger)

    def report(self, body_size, text):
        return {'bold_fraction': round(self.bold / self.chars, 4) if self.chars else 0.0,
                'font_size_ratio': round(self.median() / body_size, 4) if body_size and self.sizes else None,
                'alignment': max(self.aligns, key=self.aligns.get) if self.aligns else None,
                'all_caps': _all_caps(text)}

    def median(self):
        return weighted_median(self.sizes)

    def navigation(self, body_size, text):
        """Whether these signals are strong enough to read as a section boundary."""
        if self.chars and self.link / self.chars >= LINK_LIMIT:
            return False
        size = self.median()
        if body_size and size is not None and size < body_size:
            # Set smaller than the document's own running text: a page mark, not a section. One
            # filing prints PART I and PART II this way 88 times between them.
            return False
        if self.heading:
            return True
        if SECTION.match(' '.join(self.emphasized)):
            return True
        if body_size:
            large = sum(count for size, count in self.sizes if size >= body_size * LARGER)
            if large >= self.chars * COVERAGE:
                return True
        return _all_caps(text) and self.bold >= self.chars * COVERAGE


def _all_caps(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def weighted_median(pairs):
    if not pairs:
        return None
    total = sum(count for _, count in pairs)
    seen = 0
    for size, count in sorted(pairs):
        seen += count
        if seen * 2 >= total:
            return size
    return pairs[-1][0]


def body_size(blocks):
    """The document's own running-text size: the character-weighted median over its body prose.

    Blocks inside tables and short blocks are excluded because a label's size says nothing about
    what the document treats as ordinary text. When no block qualifies there is no size signal
    at all rather than a guessed one.
    """
    pairs = []
    for signals in blocks:
        sized = sum(count for _, count in signals.sizes)
        # A block whose size is mostly undeclared does not speak for the document: one 20pt
        # character at the end of a 220-character unsized paragraph would otherwise make 20pt
        # the body size and every real heading smaller than it.
        if signals.chars >= BODY_CHARS and sized >= signals.chars * COVERAGE:
            pairs.extend(signals.sizes)
    return weighted_median(pairs)
