"""Pure instruction walker retaining module boundaries and continuation evidence."""
from dataclasses import dataclass, field
from ._errors import TwitterError


@dataclass
class Entry:
    node: dict
    entry_id: str
    module_id: str | None = None
    index_in_module: int = 0
    pinned: bool = False
    kind: str = 'tweet'
    social_context: dict = field(default_factory=dict)


@dataclass
class Page:
    entries: list[Entry] = field(default_factory=list)
    bottom_cursor: str | None = None
    module_cursors: list[Entry] = field(default_factory=list)
    terminated: bool = False
    cleared: bool = False
    promoted: int = 0
    other_items: int = 0


def walk(instructions):
    if not isinstance(instructions, list):
        raise TwitterError(6, 'Timeline instructions are not a list.', 'Update the envelope parser.', 'envelope_drift')
    page = Page()

    def item(content, identity, module=None, index=0, pinned=False):
        if identity.startswith(('promoted-', 'promotedTweet-')) or content.get('promotedMetadata'):
            page.promoted += 1
            return
        if content.get('cursorType'):
            entry = Entry(content, identity, module, index, pinned, 'cursor')
            if content['cursorType'] == 'Bottom' and module is None:
                page.bottom_cursor = content.get('value')
            elif content['cursorType'].startswith('ShowMore'):
                page.module_cursors.append(entry)
                page.entries.append(entry)
            return
        for key, kind in (('tweet_results', 'tweet'), ('user_results', 'user')):
            if key in content:
                page.entries.append(Entry(content[key].get('result', {}), identity, module, index, pinned, kind, content.get('socialContext', {})))
                return
        kind = {'TimelineTrend': 'trend', 'TimelineEventSummary': 'event'}.get(content.get('itemType'))
        if kind:
            page.entries.append(Entry(content, identity, module, index, pinned, kind))
        else:
            page.other_items += 1

    def entry(raw, pinned=False):
        identity, content = raw.get('entryId', ''), raw.get('content', {})
        if identity.startswith(('promoted-', 'promotedTweet-')):
            page.promoted += 1
            return
        if 'items' in content:
            for index, child in enumerate(content['items']):
                item(child.get('item', {}).get('itemContent', {}), child.get('entryId', identity), identity, index, pinned)
        else:
            item(content.get('itemContent', content), identity, pinned=pinned)

    for instruction in instructions:
        kind = instruction.get('type')
        if kind == 'TimelineTerminateTimeline':
            page.terminated = page.terminated or instruction.get('direction') in (None, 'Bottom')
        elif kind == 'TimelineClearCache':
            page.cleared = True
        elif kind == 'TimelinePinEntry':
            entry(instruction.get('entry', {}), True)
        elif kind in ('TimelineAddEntries', 'TimelineReplaceEntry'):
            for raw in instruction.get('entries', [instruction['entry']] if 'entry' in instruction else []):
                entry(raw)
        elif kind == 'TimelineAddToModule':
            for index, child in enumerate(instruction.get('moduleItems', [])):
                item(child.get('item', {}).get('itemContent', {}), child.get('entryId', ''), instruction.get('moduleEntryId'), index)
    return page
