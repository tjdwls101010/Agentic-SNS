"""X's timeline instructions read in X's order: entries, the next-page cursor, collapsed branches and hidden replies,
and the records of a list page.

A Bottom termination ends the timeline even when a Bottom cursor is still sent (later pages come back empty).
"""
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from twitter.x_web.records.places import community_record, list_record, notification_record
from twitter.x_web.records.posts import account_record, post_record

HIDDEN_CURSORS = ('ShowMoreThreads', 'ShowMoreThreadsPrompt')


@dataclass
class Entry:
    kind: str            # post | account | trend | event | notification | list | community | branch
    ident: str | None
    node: dict
    entry_id: str
    module: str | None = None
    index: int = 0
    pinned: bool = False
    social: dict = field(default_factory=dict)


@dataclass
class Branch:
    module: str
    cursor_type: str
    value: str


@dataclass
class Page:
    entries: list = field(default_factory=list)
    bottom: str | None = None
    branches: list = field(default_factory=list)   # ShowMore cursors inside a module: more of a collapsed branch
    hidden: list = field(default_factory=list)     # ShowMoreThreads* cursors outside modules: replies X hid
    terminated: bool = False
    cleared: bool = False
    promoted: int = 0
    other: int = 0
    unreadable: int = 0     # entries of a known kind this skill could not turn into a record (a shape change)


@dataclass
class ListPage:
    records: list
    cursor: str | None
    has_next: bool
    promoted: int = 0
    other: int = 0
    terminated: bool = False
    unreadable: int = 0


def _dict(value):
    return value if isinstance(value, dict) else {}


def _promoted(identity, content):
    # live trends spell it promoted_metadata, posts and events promotedMetadata
    return identity.startswith(('promoted-', 'promotedTweet-')) or bool(content.get('promotedMetadata') or
                                                                        content.get('promoted_metadata'))


def _ident(kind, content, identity):
    if kind == 'post':
        result = _dict(_dict(content.get('tweet_results')).get('result'))
        if result.get('__typename') == 'TweetWithVisibilityResults':
            result = _dict(result.get('tweet'))
        if result.get('rest_id'):
            return str(result['rest_id'])
        return identity.rsplit('tweet-', 1)[-1] if 'tweet-' in identity else None
    if kind == 'account':
        return _dict(_dict(content.get('user_results')).get('result')).get('rest_id')
    if kind == 'list':
        return _dict(content.get('list')).get('id_str')
    if kind == 'community':
        return _dict(_dict(content.get('community_results')).get('result')).get('rest_id')
    return identity


def walk(instructions):
    """The entries of one page of instructions, in order (see the module docstring)."""
    page = Page()

    def item(content, identity, module=None, index=0, pinned=False):
        content = _dict(content)
        if _promoted(identity, content):
            page.promoted += 1
            return
        cursor = content.get('cursorType')
        if cursor:
            value = content.get('value')
            if module is None:
                if cursor == 'Bottom':
                    page.bottom = value
                elif cursor in HIDDEN_CURSORS:
                    page.hidden.append(value)
            elif cursor.startswith('ShowMore'):
                page.branches.append(Branch(module, cursor, value))
                page.entries.append(Entry('branch', value, content, identity, module, index, pinned))
            return
        for key, kind in (('tweet_results', 'post'), ('user_results', 'account'), ('list', 'list'),
                          ('community_results', 'community')):
            if key in content:
                page.entries.append(Entry(kind, _ident(kind, content, identity), content, identity, module, index,
                                          pinned, _dict(content.get('socialContext'))))
                return
        kind = {'TimelineTrend': 'trend', 'TimelineEventSummary': 'event',
                'TimelineNotification': 'notification'}.get(content.get('itemType'))
        if kind:
            page.entries.append(Entry(kind, identity, content, identity, module, index, pinned))
        else:
            page.other += 1

    def entry(raw, pinned=False):
        raw = _dict(raw)
        identity, content = raw.get('entryId', ''), _dict(raw.get('content'))
        if _promoted(identity, content):
            page.promoted += 1
            return
        if isinstance(content.get('items'), list):
            for index, child in enumerate(content['items']):
                child = _dict(child)
                item(_dict(child.get('item')).get('itemContent'), child.get('entryId', identity), identity, index, pinned)
        else:
            item(content.get('itemContent', content), identity, pinned=pinned)

    for instruction in instructions if isinstance(instructions, list) else []:
        instruction = _dict(instruction)
        kind = instruction.get('type')
        if kind == 'TimelineTerminateTimeline':
            page.terminated = page.terminated or instruction.get('direction') in (None, 'Bottom')
        elif kind == 'TimelineClearCache':
            page.cleared = True
        elif kind == 'TimelinePinEntry':
            entry(instruction.get('entry'), True)
        elif kind in ('TimelineAddEntries', 'TimelineReplaceEntry'):
            for raw in instruction.get('entries') or ([instruction['entry']] if 'entry' in instruction else []):
                entry(raw)
        elif kind == 'TimelineAddToModule':
            for index, child in enumerate(instruction.get('moduleItems') or []):
                child = _dict(child)
                item(_dict(child.get('item')).get('itemContent'), child.get('entryId', ''),
                     instruction.get('moduleEntryId'), index)
    return page


def _search_query(url):
    """The search words in X's own trend link (twitter://search/?query=...), or None."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ('twitter', 'https') or 'search' not in (parts.netloc + parts.path):
        return None
    query = parse_qs(parts.query).get('query') or parse_qs(parts.query).get('q')
    return query[0] if query and query[0].strip() else None


def trend_record(node, identity, event=False):
    """A trend (its words, X's label and rank, the search that reads it) or an event (its title and page)."""
    metadata = _dict(node.get('trendMetadata') or node.get('trend_metadata'))
    link = node.get('url') or node.get('trend_url') or node.get('eventSummaryUrl')
    url = _dict(link).get('url') if isinstance(link, dict) else link
    url = url if isinstance(url, str) else None
    name = node.get('name') or node.get('title') or ''
    rank = node.get('rank')
    rank = int(rank) if isinstance(rank, str) and rank.isdigit() else rank if type(rank) is int else None
    query = _search_query(url) if url and not event else None
    return {'id': identity, 'kind': 'event' if event else 'trend', 'name': name, 'rank': rank,
            'context': metadata.get('domainContext') or metadata.get('domain_context'),
            'description': metadata.get('metaDescription') or metadata.get('meta_description') or node.get('subtitle'),
            # an event's own link is a twitter:// deep link (P4 review): its title is the search that reads it
            'query': query or (name or None),
            'url': url if url and url.startswith('https://') else None}


def records_of(page):
    """The records of a walked page: posts and accounts with their unit (module or entry) and place, trends and
    events; branches are not records."""
    records = []
    for entry in page.entries:
        if entry.kind == 'post':
            record = post_record(_dict(entry.node.get('tweet_results')).get('result') or {}, entry_id=entry.entry_id)
        elif entry.kind == 'account':
            record = account_record(_dict(entry.node.get('user_results')).get('result'))
        elif entry.kind in ('trend', 'event'):
            record = trend_record(entry.node, entry.entry_id, entry.kind == 'event')
        elif entry.kind == 'list':
            record = list_record(entry.node.get('list'))
        elif entry.kind == 'notification':
            record = notification_record(entry.node)
        elif entry.kind == 'community':
            record = community_record(_dict(entry.node.get('community_results')).get('result'))
        else:
            continue
        if record is None or not (record.get('id') or record.get('username') or record.get('url') or
                                  record.get('unavailable')):
            page.unreadable += 1  # nothing to name it by: counted, not shown
            continue
        record['unit'] = entry.module or entry.entry_id
        if entry.pinned and entry.kind == 'post':
            record['is_pinned'] = True
        if entry.module and entry.module.startswith(('communityModerators', 'communityMembers')):
            record['role'] = 'moderator' if entry.module.startswith('communityModerators') else 'member'
        landing = entry.social.get('landingUrl')
        if landing:
            record['community_url'] = _dict(landing).get('url') if isinstance(landing, dict) else landing
        records.append(record)
    return records


def list_page(instructions):
    """One page of a list surface: its records, the next cursor and whether X says there is a next page."""
    page = walk(instructions)
    records = records_of(page)
    return ListPage(records=records, cursor=page.bottom, has_next=bool(page.bottom) and not page.terminated,
                    promoted=page.promoted, other=page.other, terminated=page.terminated, unreadable=page.unreadable)
