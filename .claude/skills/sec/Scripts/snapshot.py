"""Build immutable reading snapshots from already received SEC source bytes."""

import re

# Workiva fills layout cells with &#8203;. Python's \s does not match U+200B, so a layout cell
# reached storage as a truthy string that renders as nothing: 51% of NBIS blocks, and 78 of its
# 79 table headers. U+00A0, U+202F and U+2007 are already whitespace to \s and need no rule.
LAYOUT = '\u200b'


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
