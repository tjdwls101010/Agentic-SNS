"""The shapes the CLI prints and writes: records from the model's dataclasses, results and --out lines declared here."""
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from ..model import Completeness, Counts, Media, Post, User

RECORDS = {'Post': Post, 'User': User, 'Counts': Counts, 'Media': Media, 'Completeness': Completeness}
# What a field means beyond its name; a field whose name says it all has no entry.
MEANING = {
    ('Post', 'id'): 'Numeric Threads identity; handles and URLs can change, this does not.',
    ('Post', 'code'): 'The shortcode in the post URL.',
    ('Post', 'created_at'): 'When the post was written (UTC ISO). A repost carries the original post\'s time, not '
                            'when it was reposted.',
    ('Post', 'text'): 'The full text as Threads sent it; text output clips it at --chars.',
    ('Post', 'like_count'): 'Null when the author hides counts.',
    ('Post', 'reply_count'): 'Direct replies Threads reports; a post read shows only its first batch.',
    ('Post', 'is_reply'): 'The post answers another post.',
    ('Post', 'reply_to_id'): 'The post this one answers, only when Threads says so; never inferred from order.',
    ('Post', 'root_post_id'): 'The first post of the thread this one belongs to.',
    ('Post', 'quoted_post'): 'The quoted post, attributed to its own author; its unavailability does not hide this post.',
    ('Post', 'reposted_post'): 'The original post a repost shares, attributed to its own author.',
    ('Post', 'link_preview'): 'The linked page: {url, title}; url is the destination, not Threads\' redirect.',
    ('Post', 'is_pinned'): 'Pinned to the author\'s profile, so it sits first whatever its date.',
    ('Post', 'unavailable'): 'A tombstone: deleted, hidden or not visible to this account.',
    ('Post', 'role'): 'In a post read: parent (above the post), post, or reply.',
    ('Post', 'depth'): 'Nesting under the post in a post read; 0 for the post, its parents and direct replies.',
    ('Post', 'relation'): 'For a nested reply: reply-to=<id>, or thread continuation when the author continued.',
    ('User', 'id'): 'Numeric Threads identity; the handle can change, this does not.',
    ('User', 'private'): 'A private profile shows its posts only to accepted followers.',
    ('User', 'follower_count'): 'As the profile reports it.',
    ('User', 'friendship_status'): 'The logged-in account\'s relation to this profile, as Threads sends it.',
    ('User', 'counts'): 'On a profile card only.',
    ('Counts', 'following'): 'Threads does not publish it; null is unknown, and graph following lists the accounts.',
    ('Counts', 'mutuals'): 'Threads does not publish it; null is unknown.',
    ('Media', 'kind'): 'photo, video, carousel or unknown.',
    ('Completeness', 'reported_direct'): 'Direct replies Threads reports for the post; null when it reports none.',
    ('Completeness', 'received_direct'): 'Readable direct replies in the one batch the page carries.',
    ('Completeness', 'shown_direct'): 'Received direct replies shown within --limit.',
    ('Completeness', 'shown_descendants'): 'Replies shown nested under the shown direct replies.',
    ('Completeness', 'unshown_received'): 'Received but beyond --limit; reading the post again with a larger --limit '
                                          'shows them (one request).',
    ('Completeness', 'unavailable'): 'Direct replies received as tombstones.',
    ('Completeness', 'unfetched'): 'About how many direct replies never arrived: reported minus received minus '
                                    'unavailable; null when that would be negative or nothing is reported. Opening a '
                                    'reply does not fetch its missing siblings.',
    ('Completeness', 'unfetched_is_estimate'): 'True whenever unfetched is a number: it is arithmetic, not a count.',
}
STOPS = {
    'limit_reached': '--limit records were shown; more: continues',
    'exhausted': 'the surface ended',
    'window_reached': 'a newest-first tab passed the date window\'s start',
    'not_paginable': 'this surface returns one batch (a post\'s replies, account search, liked, saved)',
    'server_capped': 'Threads returned its own sample (followers); not the whole list',
    'budget': '--max-requests was spent; more: continues',
    'blocked': 'a checkpoint, rate limit or login stopped the read',
    'query_failure': 'a request failed; error, message and fix say why',
}
ERRORS = {
    'arguments': 'the command line cannot be run as given',
    'aside': 'Aside is unavailable or answered with something other than one response',
    'login': 'Threads needs a login in Aside',
    'blocked': 'account protection refuses requests (see message)',
    'checkpoint': 'Threads asked for a checkpoint; nothing runs until doctor --unblock succeeds',
    'rate_limit': 'Threads (or the local 10-minute window) limited this account; it expires by itself',
    'transient': 'a request failed (HTTP or incomplete data); retrying later may work',
    'operation_rotated': 'Threads no longer answers this query as registered; fix names the refresh to run',
    'shape_changed': 'a response lacked what the reader reads; only a new version of the skill fixes it',
    'registry': 'the local query registry or its override cannot be read',
    'budget': '--max-requests was reached; more: continues',
    'empty': 'Threads returned nothing for this target or window',
    'partial': 'records were read, then something failed; for refresh, some queries were verified and others not',
    'unavailable': 'deleted, private and not followed, or redirected away from the post',
    'role_mismatch': 'refresh: a renamed query\'s replay was not the list it claimed to be',
    'unverified': 'refresh verified no query; the previous registry is kept',
}


def field_type(annotation):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        return {'anyOf': [field_type(arg) for arg in args]}
    if annotation in RECORDS.values():
        return {'$ref': '#/$defs/' + annotation.__name__}
    if origin is list or annotation is list:
        return {'type': 'array', 'items': field_type(args[0]) if args else {}}
    if origin is dict or annotation is dict:
        return {'type': 'object'}
    return {'type': {str: 'string', int: 'integer', bool: 'boolean', type(None): 'null'}[annotation]}


def record(name):
    cls = RECORDS[name]
    hints = get_type_hints(cls)
    sample = cls('image', '').to_dict() if name == 'Media' else cls().to_dict()
    properties = {}
    for key in sample:
        properties[key] = field_type(hints[key])
        if (name, key) in MEANING:
            properties[key]['description'] = MEANING[(name, key)]
    return {'type': 'object', 'properties': properties, 'required': list(sample), 'additionalProperties': False}


def obj(properties, required, **extra):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False, **extra}


def described(rule, description):
    return {**rule, 'description': description}


STRING, INTEGER, BOOLEAN, OBJECT = {'type': 'string'}, {'type': 'integer'}, {'type': 'boolean'}, {'type': 'object'}
NULLABLE_STRING = {'type': ['string', 'null']}
FAILURE = {'error': {'$ref': '#/$defs/ErrorKind'}, 'message': STRING,
           'fix': described(STRING, 'What to do next. A command in backticks is this CLI invoked as more: writes it; '
                                    'replace a <placeholder> with a real value first.')}


def schema(exit_codes=None):
    definitions = {name: record(name) for name in RECORDS}
    definitions['User']['properties']['counts'] = {'anyOf': [{'$ref': '#/$defs/Counts'}, {'type': 'null'}],
                                                   'description': MEANING[('User', 'counts')]}
    definitions['ErrorKind'] = {'enum': list(ERRORS), 'description': '; '.join(f'{k}: {v}' for k, v in ERRORS.items())}
    definitions['StopReason'] = {'enum': list(STOPS), 'description': '; '.join(f'{k}: {v}' for k, v in STOPS.items())}
    definitions['Budget'] = obj({
        'kind': {'enum': ['local']},
        'limit': described(INTEGER, 'This command\'s cap, --max-requests.'), 'remaining': INTEGER,
        'window_used': described(INTEGER, 'Requests every command on this account made in the last window_seconds.'),
        'used': described(INTEGER, 'Requests this command made; with refresh --capture, the reservation for the tab, '
                                   'not its uncounted start-up traffic.'),
        'window_limit': INTEGER, 'window_seconds': INTEGER},
        ['kind', 'used', 'limit', 'remaining', 'window_used', 'window_limit', 'window_seconds'],
        description='Counted locally: Threads sends no rate headers, so this is not a server allowance.')
    definitions['Error'] = obj({'ok': {'const': False}, 'code': described(INTEGER, 'The exit code.'), **FAILURE},
                               ['ok', 'error', 'code', 'message', 'fix'],
                               description='What a command prints when it fails before it starts reading: arguments, '
                                           'Aside, login, a block, an unreadable route. A failure while reading a '
                                           'listing is a ReadResult with ok false and error, message and fix.')
    definitions['ReadResult'] = obj({
        'ok': described(BOOLEAN, 'False when something failed after records were read; error says what.'),
        'results': {'type': 'array', 'items': {'anyOf': [{'$ref': '#/$defs/Post'}, {'$ref': '#/$defs/User'}]},
                    'description': 'Empty when --out saved them to the file.'},
        'stop_reason': {'$ref': '#/$defs/StopReason'},
        'next': described(NULLABLE_STRING, 'The whole command that continues this read, to run as written.'),
        'next_handle': described(INTEGER, 'The numbered handle next continues from.'),
        'context': described(OBJECT, 'The query\'s identity; a handle or --out file resumes only the same query.'),
        'budget': {'$ref': '#/$defs/Budget'}, 'fetched_bytes': INTEGER,
        'completeness': {'$ref': '#/$defs/Completeness'},
        'post_id': described(STRING, 'post: the numeric id of the post read.'),
        'reported_total': described({'type': ['integer', 'null']}, 'followers: the total Threads reports; the '
                                                                    'batch can hold fewer.'),
        'window': obj({'since': NULLABLE_STRING, 'until': NULLABLE_STRING,
                       'complete': described(BOOLEAN, 'The whole window was read: the surface ended, or a '
                                                      'newest-first tab passed its start.')},
                      ['since', 'until', 'complete']),
        'out': described(STRING, 'The --out file.'), 'count': described(INTEGER, 'Records in the --out file.'),
        'already_complete': described(BOOLEAN, 'The --out file was already complete; nothing was requested.'),
        **FAILURE}, ['ok', 'results', 'stop_reason', 'next', 'budget', 'fetched_bytes'],
        description='home, user, about, post, graph, search and me.')
    definitions['Doctor'] = obj({
        'ok': BOOLEAN, 'viewer': described(STRING, 'The logged-in handle.'), 'blocked': BOOLEAN,
        'capture_cleanup_uncertain': described(BOOLEAN, 'A capture tab may still be open in Aside.'),
        'registry_age_days': described(INTEGER, 'Days since the oldest query id was verified.'),
        'budget': {'$ref': '#/$defs/Budget'}, 'fetched_bytes': INTEGER},
        ['ok', 'viewer', 'blocked', 'capture_cleanup_uncertain', 'registry_age_days', 'budget', 'fetched_bytes'])
    definitions['Refresh'] = obj({
        'ok': BOOLEAN, 'results': {'type': 'array', 'maxItems': 0},
        'updated': described({'type': 'array', 'items': STRING}, 'Queries whose new id replayed and was saved.'),
        'renamed': described({'type': 'object', 'additionalProperties': obj({'from': STRING, 'to': STRING},
                                                                           ['from', 'to'])},
                             'Queries adopted under a new name the route proved and a replay confirmed.'),
        'missing': described({'type': 'object', 'additionalProperties': STRING},
                             'Queries not updated, each with why; their previous entries are kept.'),
        'failed': described({'type': 'object', 'additionalProperties': STRING}, 'What failed, by query or route.'),
        'post_route': described({'enum': ['decoded', 'failed', 'not_checked']},
                                'Whether a post page still decodes; refresh cannot repair a post page.'),
        'capture': described(OBJECT, 'refresh --capture: what the app tab did, including cleanup_confirmed.'),
        'stop_reason': {'$ref': '#/$defs/StopReason'}, 'next': {'type': 'null'},
        'budget': {'$ref': '#/$defs/Budget'}, 'fetched_bytes': INTEGER, **FAILURE},
        ['ok', 'updated', 'renamed', 'missing', 'failed', 'stop_reason', 'budget', 'fetched_bytes'])
    definitions['OutHeader'] = obj({
        'kind': {'const': 'header'}, 'started_at': STRING, 'limit_unit': STRING, 'command': STRING,
        'account': STRING, **{key: {} for key in ('target', 'feed', 'tab', 'sort', 'query', 'type', 'tag',
                                                  'relation', 'collection', 'since', 'until')}},
        ['kind', 'started_at', 'command', 'account'],
        description='The first line of an --out file: the query it belongs to.')
    definitions['OutPage'] = obj({
        'kind': {'const': 'page'}, 'cursor': described(OBJECT, 'Where the next run resumes.'),
        'ids': {'type': 'array'}, 'n': INTEGER, 'stop_reason': STRING},
        ['kind', 'cursor', 'ids', 'n', 'stop_reason'],
        description='Commits the records written since the previous marker; lines after the last marker are '
                    'dropped and read again.')
    return {'ok': True, '$schema': 'https://json-schema.org/draft/2020-12/schema', '$defs': definitions,
            'commands': {'home user about post graph search me': '#/$defs/ReadResult',
                         'doctor': '#/$defs/Doctor', 'refresh': '#/$defs/Refresh',
                         'a failure before reading starts': '#/$defs/Error',
                         '--out file': 'OutHeader, then Post or User records, each page closed by OutPage'},
            'exit_codes': {str(code): meaning for code, meaning in (exit_codes or {}).items()}}
