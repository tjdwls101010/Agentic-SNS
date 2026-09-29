"""What the output means, by topic: record fields come from the same dataclasses the records are built from."""
import types
from typing import get_args, get_origin, get_type_hints
from ..graphql.responses.records import User, List, Community, Trend, Tweet, Media

RECORDS = {'tweet': Tweet, 'user': User, 'media': Media, 'list': List, 'community': Community, 'trend': Trend}
ABOUT = {
    'tweet': 'a post row, a repost row or a thread member',
    'user': 'an account card or row',
    'media': 'a photo or video on a post',
    'list': 'a list card',
    'community': 'a community card',
    'trend': 'a trend or event row',
    'envelope': 'the result document: fields, stop reasons, exit codes, error classes',
    'export': 'the --out NDJSON lines and how a run resumes',
}
NULL_COUNT = 'Count as X reported it; null means X did not report it, not zero.'
MEANINGS = {
    'tweet': {
        'id': 'Stable post ID; join and deduplicate by it, never by handle. A repost row has the repost\'s own ID.',
        'author': 'Who acted: for a repost row, the reposter, not the writer (see retweeted_tweet).',
        'text': 'Full text, long posts included, with t.co links expanded and media links removed. A repost row carries the original text.',
        'url': 'Next hop to open; a repost row points at the original post.',
        'created_at': 'UTC time of this row; a repost row\'s is when it was reposted.',
        'retweeted_tweet': 'The original behind a repost row; its author wrote the text and earned the counts shown on the row.',
        'quoted_tweet': 'The quoted post when X embedded it.',
        'quoted_tweet_id': 'Quoted post ID even when X left out its body; open it with post.',
        'in_reply_to_id': 'Parent post ID; the parent may not be on this page.',
        'mentions': 'Mentioned handles without @, in order of appearance, each once.',
        'urls': 'Expanded link targets.',
        'is_pinned': 'Pinned to the profile; an old pin never ends a date window early, though --since/--until still drop it when it falls outside.',
        'limited_actions': 'Actions X restricts on this post, such as Reply.',
        'is_note_tweet': 'A long post whose full text came from X\'s note.',
        **{key: NULL_COUNT for key in ('reply_count', 'retweet_count', 'quote_count', 'like_count', 'bookmark_count', 'view_count')},
    },
    'user': {
        'id': 'Stable account ID; handles change, so join by this.',
        'is_blue_verified': 'Paid subscription marker, not identity verification.',
        'verified_type': 'Business or Government: an organisation badge, unlike the paid check.',
        'description': 'Bio with links expanded.',
        'following': 'You follow this account; null when X did not say.',
        'followed_by': 'This account follows you; null when X did not say.',
        **{key: NULL_COUNT for key in ('followers_count', 'following_count', 'tweet_count', 'media_count', 'favorites_count')},
    },
    'media': {'kind': 'photo, video or animated_gif.', 'url': 'Highest-bitrate MP4 for video, otherwise the image.'},
    'list': {'mode': 'Public or Private.'},
    'community': {'role': 'Your own role in the community.'},
    'trend': {'id': 'The entry identifier on this Explore page, not a stable trend ID.', 'kind': 'trend or event.'},
}
DYNAMIC = {
    'tweet': {
        'role': 'In a thread: parent (above the opened post), focal (the opened post) or reply.',
        'depth': 'Reply nesting below the direct replies; 0 for a direct reply.',
        'module': 'The timeline module X grouped the row in, such as a conversation thread.',
        'index_in_module': 'Position inside that module.',
        'community_url': 'The community a communities-browse post belongs to.',
    },
    'user': {
        'role': 'On community --tab about: moderator or member.',
        'module': 'The timeline module X grouped the row in.',
    },
}
ENVELOPE = {
    'ok': 'false when the run stopped on an error, even with partial results.',
    'results': 'Records in the order X gave them; kind names each record\'s topic.',
    'shown': 'How many records this run returned.',
    'stored': 'With --out: records committed to the file so far.',
    'stop_reason': 'Why collecting stopped; see stop reasons.',
    'next': 'The more: command that continues this query, or null.',
    'next_handle': 'The --after handle inside next; it expires 24 hours after issue.',
    'card': 'The profile, list or community the listing belongs to.',
    'operation': 'The X operation whose rate bucket the main request spent.',
    'budget': 'operations: each bucket used ({limit, remaining, reset_at}); window: this account\'s requests in 10 minutes (of 200); requests: this run\'s.',
    'warnings': 'Errors X returned alongside valid data.',
    'viewer_id': 'The account the browser is logged in as.',
    'viewer_changed': 'The browser switched accounts since the cache; continuations were dropped.',
    'error / message / fix': 'On failure: the error class, what happened, and what to do.',
    'reported / direct_shown / nested_shown / hidden_branches': 'Thread completeness: replies X counted, direct and nested replies shown, and reply branches X collapsed (not followed).',
    'other_items / promoted': 'Trends: Explore items that are neither trends nor events, and ads, both left out.',
    'unresolved': 'about: handles X returned no card for.',
    'already_complete': 'With --out: the file already holds the whole listing; no page was requested.',
}
STOPS = {
    'limit_reached': 'The display target was met; when the result carries a more: line, it continues with the cached items first.',
    'exhausted': 'X has no further page.',
    'window_reached': 'Profile posts went past --since; only profile posts are ordered enough to prove this.',
    'not_paginable': 'A single lookup or a one-page surface.',
    'terminated': 'X ended the timeline.',
    'empty_pages': 'An account list returned three empty pages in a row.',
    'budget': 'This run spent its request cap (10, or 40 with --limit, --since or --out); more: continues.',
    'blocked': 'A rate limit, the account window or a block stopped a later page; results so far are kept.',
    'query_failure': 'A later page failed; results so far are kept.',
}
ERRORS = {
    'arguments': (2, 'An argument or local file must change; the fix names it.'),
    'viewer_changed': (2, 'The browser switched accounts mid-run; start the query again.'),
    'aside_unavailable': (3, 'Aside did not run or answered with an invalid envelope.'),
    'session': (4, 'No logged-in X session in Aside.'),
    'csrf': (4, 'X refused the session token twice.'),
    'challenge': (5, 'X showed a browser challenge; every request stays blocked until doctor --unblock.'),
    'account_locked': (5, 'X locked the account; every request stays blocked until doctor --unblock.'),
    'rate_limit': (5, 'This operation\'s bucket is empty until its reset.'),
    'window': (5, 'The account made 200 requests in 10 minutes.'),
    'transient': (6, 'X failed without a lasting cause; retry later.'),
    'transaction_rejected': (6, 'X rejected the request signature even after new material.'),
    'transaction_unavailable': (6, 'Signature material could not be built.'),
    'operation_rotated': (6, 'X changed a query ID or feature switch; refresh repairs it.'),
    'contract_drift': (6, 'X changed a query\'s variables; the code must change.'),
    'envelope_drift': (6, 'X changed a response\'s shape; the code must change.'),
    'empty': (7, 'A valid response with no matching items.'),
    'budget': (8, 'This run\'s request cap stopped it; more: continues.'),
    'partial': (8, 'Local output or cache input/output failed.'),
    'cache_unreadable': (5, 'A file in the skill\'s cache could not be read; nothing was requested.'),
    'unavailable': (9, 'The target is deleted, suspended or unavailable.'),
    'protected': (9, 'A protected profile you do not follow.'),
}
EXPORT = [
    ('header', 'First line: {"kind": "header", "format": 2, ...query context and viewer_id}. A later run resumes the file only for the same query, viewer and format 2.'),
    ('record', 'One line per record, the same objects as results; a page\'s records come before its page line.'),
    ('page', '{"kind": "page", "ids", "n", "state", "stop_reason"} (a thread adds reported, direct_shown, nested_shown, hidden_branches) commits the records above it.'),
    ('resume', 'Run the same command with the same --out: records after the last page line are dropped and collecting continues from that page\'s state. The file is complete when a page line\'s stop_reason is exhausted, window_reached, not_paginable or terminated.'),
    ('window', 'Only records inside --since/--until are written, but every seen ID is remembered, so stored and shown can differ.'),
]


def json_type(annotation):
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin is types.UnionType:
        return {'anyOf': [json_type(item) for item in arguments]}
    if origin is list or annotation is list:
        return {'type': 'array', 'items': json_type(arguments[0]) if arguments else {}}
    if origin is dict or annotation is dict:
        return {'type': 'object'}
    if annotation in (str, int, bool, float, type(None)):
        return {'type': {str: 'string', int: 'integer', bool: 'boolean', float: 'number', type(None): 'null'}[annotation]}
    return {'$ref': '#/$defs/' + annotation.__name__}


def definition(topic):
    cls = RECORDS[topic]
    hints = get_type_hints(cls)
    properties = {key: {**({'description': MEANINGS[topic][key]} if key in MEANINGS[topic] else {}), **json_type(hints[key])}
                  for key in cls().to_dict()}
    for key, meaning in DYNAMIC.get(topic, {}).items():
        properties[key] = {'description': 'Only on some rows. ' + meaning}
    return {'type': 'object', 'properties': properties, 'required': list(cls().to_dict())}


def referenced(topic):
    """The topic's record class and every record class its fields refer to, each once."""
    found, queue = [], [RECORDS[topic]]
    while queue:
        cls = queue.pop(0)
        if cls not in found:
            found.append(cls)
            queue += [c for hint in get_type_hints(cls).values() for c in records_in(hint)]
    return found


def records_in(hint):
    if hint in RECORDS.values():
        yield hint
    for argument in get_args(hint):
        yield from records_in(argument)


def schema(topic=None, exits=None, text=True):
    """No topic: the table of contents. A record topic: its fields. envelope and export: the result and file contracts."""
    if topic is None:
        counts = {name: len(cls().to_dict()) + len(DYNAMIC.get(name, {})) for name, cls in RECORDS.items()}
        if not text:
            return {'ok': True, 'topics': {name: dict(about=about, **({'fields': counts[name]} if name in counts else {}))
                                           for name, about in ABOUT.items()}, 'usage': 'schema <topic> [--json]'}
        lines = ['schema topics; read one with: schema <topic> [--json]']
        lines += [f'{name:<10} {str(counts[name]) + " fields" if name in counts else "":<10} {about}' for name, about in ABOUT.items()]
        return {'ok': True, 'summary': '\n'.join(lines)}
    if topic in RECORDS:
        defs = {cls.__name__: definition(next(n for n, c in RECORDS.items() if c is cls)) for cls in referenced(topic)}
        if not text:
            return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$ref': '#/$defs/' + RECORDS[topic].__name__, '$defs': defs}
        own = defs[RECORDS[topic].__name__]['properties']
        lines = [f'{topic}: {ABOUT[topic]}; name type meaning (a field without a meaning is what its name says)']
        if any(spec.get('description') == NULL_COUNT for spec in own.values()):
            lines.append('*_count fields: ' + NULL_COUNT)
        for key, spec in own.items():
            kind = spec.get('type') or ' | '.join(a.get('type') or a['$ref'].split('/')[-1] for a in spec.get('anyOf', [])) or spec.get('$ref', '').split('/')[-1] or 'any'
            if kind == 'array':
                kind = 'list of ' + (spec['items'].get('type') or spec['items'].get('$ref', '').split('/')[-1] or 'any')
            meaning = '' if spec.get('description') == NULL_COUNT else spec.get('description', '')
            lines.append(f'{key} {kind if key not in DYNAMIC.get(topic, {}) else "(dynamic)"} {meaning}'.rstrip())
        return {'ok': True, 'summary': '\n'.join(lines)}
    if topic == 'envelope':
        if not text:
            return envelope_schema(exits or {})
        lines = ['envelope: every JSON result; text output shows the same facts in its header and closing lines', 'fields:']
        lines += [f'  {name}: {meaning}' for name, meaning in ENVELOPE.items()]
        lines += ['stop reasons:'] + [f'  {name}: {meaning}' for name, meaning in STOPS.items()]
        lines += ['exit codes:'] + [f'  exit {code}: {meaning}' for code, meaning in (exits or {}).items()]
        lines += ['error classes:'] + [f'  {name} (exit {code}): {meaning}' for name, (code, meaning) in ERRORS.items()]
        return {'ok': True, 'summary': '\n'.join(lines)}
    if not text:
        return export_schema()
    return {'ok': True, 'summary': '\n'.join(['export: --out writes private NDJSON, format 2'] + [f'{name}: {rule}' for name, rule in EXPORT])}


def envelope_schema(exits):
    properties = {}
    for names, meaning in ENVELOPE.items():
        for name in names.split(' / '):
            properties[name] = {'description': meaning}
    properties['stop_reason'] = {'type': 'string', 'enum': list(STOPS),
                                 'description': ' '.join(f'{name}: {meaning}' for name, meaning in STOPS.items())}
    properties['error'] = {'type': 'string', 'enum': list(ERRORS),
                           'description': ' '.join(f'{name} (exit {code}): {meaning}' for name, (code, meaning) in ERRORS.items())}
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'title': 'result envelope', 'type': 'object',
            'description': 'Exit codes: ' + '; '.join(f'{code} {meaning}' for code, meaning in exits.items()),
            'properties': properties, 'required': ['ok']}


def export_schema():
    rules = dict(EXPORT)
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'title': '--out NDJSON line', 'description': rules['resume'] + ' ' + rules['window'],
            'oneOf': [
                {'description': rules['header'], 'type': 'object', 'required': ['kind', 'format'],
                 'properties': {'kind': {'const': 'header'}, 'format': {'const': 2}}},
                {'description': rules['page'], 'type': 'object', 'required': ['kind', 'ids', 'n', 'state', 'stop_reason'],
                 'properties': {'kind': {'const': 'page'}, 'ids': {'type': 'array', 'items': {'type': 'string'}}, 'n': {'type': 'integer'},
                                'state': {'type': 'object'}, 'stop_reason': {'enum': list(STOPS)}}},
                {'description': rules['record'] + ' See schema tweet, user, list, community or trend.', 'type': 'object',
                 'required': ['kind'], 'properties': {'kind': {'enum': ['tweet', 'user', 'list', 'community', 'trend', 'event']}}}]}
