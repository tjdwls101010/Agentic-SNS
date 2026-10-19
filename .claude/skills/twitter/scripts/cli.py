#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read X (Twitter) through the logged-in Aside browser, read-only."""
import argparse
import json
import os
import re
import shlex
import sys
from datetime import date, datetime, time, timedelta

from twitter import about, listing, maintenance, search, thread
from twitter.errors import TwitterError
from twitter.render import render_page, render_summary
from twitter.results import failure_envelope

EXIT_CODES = {
    0: 'success: records, a stop that more: (or the same --out command) resumes, an already complete --out file, or '
       'a doctor/schema result',
    2: 'invalid arguments, or a handle or --out file that belongs to another query, an earlier version or has expired',
    3: 'Aside or the browser tab is unavailable, timed out or answered invalidly',
    4: 'X login is required in the Aside browser (or it changed accounts mid-command)',
    5: 'requests are blocked until a person clears it (a lock or a challenge), or protection state is unreadable',
    6: 'a request failed before any record was read (a read X no longer accepts, or the time limit)',
    7: 'X explicitly returned nothing, or nothing fell inside the window',
    8: 'partial: records were read and then a request failed, or a stop could not save where to continue',
    9: 'the target cannot be read by this account: deleted, suspended, protected and not followed, or never existed',
    10: 'X\'s limit for this operation ran out before any record: not an account problem, other commands still work',
}
KIND_EXIT = {'records': 0, 'resumable': 0, 'complete': 0, 'maintenance': 0, 'argument': 2, 'aside': 3, 'login': 4,
             'blocked': 5, 'failed': 6, 'empty': 7, 'partial': 8, 'unavailable': 9, 'rate_limited': 10}


REQUESTS = ('how requests are counted: every read and retry this command sends counts exactly, and so does every '
            'x.com request the dedicated tab finishes while it runs (its own requests are told apart by a nonce in '
            'the URL fragment, never sent to X), so the total can end a little above --max-requests: no read is '
            'sent once the budget is spent. Opening the tab (or loading it again) is measured the same way until '
            'the load settles, about 15-25, and shown as "tab opened", outside --max-requests (20 plus what was seen '
            'when the start of the load could not be measured). Requests '
            'the open tab made between commands are shown as unwatched=, not charged, but a block seen there stops '
            'the command before it sends anything. Static files do not count. All invocations share one lock and '
            '1-2 s pacing for the account and slow down when X\'s limit for an operation is nearly used; a command '
            'ends within about two minutes. The tab is closed about 5 minutes after the last command.')
TEXT_OUTPUT = ('output: first line "<command> · … · N shown · stopped=<reason> · requests=<used>/<budget>" (plus '
               '"x-limit <operation> resets <time> · next <time>" when X\'s limit stopped it); dated reads add '
               '"window <since>..<until> · <coverage>"; then one record per [p1]/[r1]/[a1]/[t1] label, each ending '
               'with the arguments of the next command (url: post <url> opens that one post; author; replies '
               '<handle>); text is shown as text[N of M chars shown]; then coverage: lines; last, more: <command> when '
               'reading can continue.')
JSON_OUTPUT = ('--json: one JSON envelope instead (ok, command, stop_reason, request_count, max_requests, limit, '
               'coverage, next, error, message, fix, results, with full texts); schema result describes every field.')
OUT_OUTPUT = ('--out FILE: records go to an NDJSON file a whole page at a time and stdout gets one summary line (one '
              'JSON object with --json); rerun the same command with the same file to resume. --out cannot be '
              'combined with --after. The file holds other people\'s posts: keep it outside the repository.')
FAILURE = ('failure: one JSON envelope (ok false, error, message, fix) when nothing was read; records read before a '
           'failure print as usual, followed by a "coverage: incomplete — <message> fix: <fix>" line. Exit 10 (an '
           'operation\'s limit) and exit 5 (a block a person must clear) are different: the first passes by itself '
           'at the time shown and other commands still work.')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TwitterError(2, message, f'Run {self.prog} --help.')


def positive(value):
    if value.isascii() and value.isdigit() and int(value) > 0:
        return int(value)
    raise argparse.ArgumentTypeError('expected a positive integer')


def chars(value):
    if value.isascii() and value.isdigit():
        return int(value)
    raise argparse.ArgumentTypeError('expected 0 (full text) or a positive integer')


def budget(value):
    number = positive(value)
    # 성진: 호출당 400회 상한은 실계정 보호용(하루 누적 상한은 두지 않음, X4). 일회용 계정으로 바꾸면 올려도 됨
    if number > 400:
        raise argparse.ArgumentTypeError('at most 400 requests per invocation')
    return number


def day(value):
    try:
        found = date.fromisoformat(value)
        for edge in (found, found + timedelta(days=1)):  # a window's bounds are local midnights, the day after included
            datetime.combine(edge, time()).astimezone().timestamp()
        return found.isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError('expected a date as YYYY-MM-DD') from None
    except (OverflowError, OSError):
        raise argparse.ArgumentTypeError('expected a date this computer can turn into a local time') from None


OPTIONS = {
    'limit': (('--limit',), {'type': positive, 'help': 'Records to show; omitted: the default the description below gives (one page for most reads)'}),
    'since': (('--since',), {'type': day, 'metavar': 'DAY', 'help': 'First local day to include, YYYY-MM-DD'}),
    'until': (('--until',), {'type': day, 'metavar': 'DAY', 'help': 'Last local day to include, YYYY-MM-DD'}),
    'chars': (('--chars',), {'type': chars, 'help': 'Characters of each text to show (default 180; 0 = all received); --json and --out keep all'}),
    'after': (('--after',), {'type': positive, 'metavar': 'HANDLE', 'help': 'Continue from the numbered handle a more: line printed'}),
    'out': (('--out',), {'metavar': 'FILE', 'help': 'Collect into this NDJSON file, one committed page at a time; rerun the same command to resume. --limit then counts what is saved'}),
    'json': (('--json',), {'action': 'store_true', 'help': 'Print one JSON envelope instead of text'}),
    'max_requests': (('--max-requests',), {'type': budget, 'default': 25, 'metavar': 'N', 'help': 'Request budget (default 25, at most 400): no read is sent once it is spent; the page\'s own requests while the command runs count too'}),
}
LIST = ('limit', 'chars', 'after', 'out', 'json', 'max_requests')


COMMANDS = {
    'feed': {
        'help': 'Read your home feed, a page at a time.',
        'run': listing.feed,
        'arguments': [(('--feed',), {'choices': ['foryou', 'following'], 'default': 'foryou', 'help': 'foryou: the posts X ranks for this account; following: from the accounts it follows'}),
                      'since', 'until'] + list(LIST),
        'epilog': ['foryou is what X chose to show this account, not everything; following holds only the accounts it follows, and X does not serve it newest first either, so neither feed can close a --since window: a window keeps the posts dated inside it among those read (a sample, not the whole day).',
                   'A repost row is the reposter\'s act, dated when it was reposted; the words are the original\'s, shown under it with their own author. Promoted posts (ads) are left out and counted.',
                   'Without --limit, a window or --out it reads one page; more: continues.',
                   'requests: 1 per page of about 20 posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
    },
    'profile': {
        'help': 'Read a profile\'s tab: posts (with reposts), replies, media, highlights or articles.',
        'run': listing.profile,
        'arguments': [(('target',), {'help': 'X @handle or profile URL; a tab URL such as /<handle>/with_replies reads that tab'}),
                      (('--tab',), {'choices': ['posts', 'replies', 'media', 'highlights', 'articles'], 'help': 'The tab (default: the URL\'s tab, else posts)'}),
                      'since', 'until'] + list(LIST),
        'epilog': ['posts holds the account\'s posts and reposts, newest first (X\'s own Posts tab now hides reposts); a repost row is dated when it was reposted. posts and replies are newest first, so a --since window closes at the first page wholly older than it (a pinned post sits first whatever its date and does not close it). media (photos, videos and GIFs), highlights and articles are not served in date order: a window covers them only when read to the end.',
                   'A protected account this account does not follow is unavailable (exit 9), which is not the same as empty.',
                   'Without --limit, a window or --out it reads one page; more: continues.',
                   'requests: 1 to find the account, then 1 per page of about 20 posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    },
    'about': {
        'help': 'Read an account\'s card, or several accounts\' cards in one request.',
        'run': about.about,
        'arguments': [(('target',), {'nargs': '+', 'help': 'X @handle or profile URL; several are read together'}), 'json', 'max_requests'],
        'epilog': ['A card: name, bio, links, location, join date, counts (followers, following, posts), whether it is protected, its relation to you, and its marks: a paid check is an X subscription, not an identity check; a Business or Government badge is granted by X to an organisation; a declared Parody, Commentary or Fan label is the account\'s own. Several handles: those X did not return are named (unresolved).',
                   'requests: 1.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 9, 10),
    },
    'graph': {
        'help': 'Read the accounts a profile follows or that follow it, or the accounts X recommends as similar.',
        'run': listing.graph,
        'arguments': [(('target',), {'help': 'X @handle or profile URL'}),
                      (('relation',), {'choices': ['following', 'followers', 'verified', 'known', 'similar'], 'help': 'following, followers, verified (followers with a paid check), known (its followers you follow) or similar (X\'s recommendation)'})] + list(LIST),
        'epilog': ['A follow records what an account did, not friendship or agreement; similar is X\'s recommendation of accounts like this one, not a relationship of any kind. Counts on the card (about) are what X reports; the list is what X serves, page by page, and it can stop early: three pages in a row with no new account end the read (stopped=query_failure with that reason).',
                   'Without --limit or --out it reads one page; more: continues.',
                   'requests: 1 to find the account, then 1 per page of about 20 accounts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    },
    'me': {
        'help': 'Read your own bookmarks or likes.',
        'run': listing.me,
        'arguments': [(('collection',), {'choices': ['bookmarks', 'likes'], 'help': 'bookmarks or likes (nobody else\'s likes are public on X)'})] + list(LIST),
        'epilog': ['In X\'s order (most recently saved or liked first, as X serves it); each post keeps its own date, not when you saved or liked it.',
                   'Without --limit, a window or --out it reads one page; more: continues.',
                   'requests: 1 per page of about 20 posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
    },
    'reposts': {
        'help': 'Read the accounts that reposted one post.',
        'run': listing.reposts,
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'x.com post URL or numeric id'})] + list(LIST),
        'epilog': ['A repost is an account sharing the post as it is, which records the act, not agreement; quotes (the posts that add words) are read with quotes. The list is what X serves, page by page; three pages in a row with no new account end the read.',
                   'Without --limit or --out it reads one page; more: continues.',
                   'requests: 1 per page of about 20 accounts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    },
    'post': {
        'help': 'Read one post in full with its parent chain and first batch of replies, or several posts by id.',
        'run': thread.post,
        'arguments': [(('target',), {'nargs': '+', 'metavar': 'URL', 'help': 'x.com post URL or numeric id; several: those posts only, without replies'}),
                      (('--sort',), {'choices': ['top', 'recent'], 'default': 'top', 'help': 'Reply order: top (X\'s ranking) or recent (newest first)'}),
                      (('--limit',), {'type': positive, 'help': 'Reply threads to show from the first batch (each reply with what hangs under it)'}),
                      (('--chars',), {'type': chars, 'help': 'Characters of each parent and reply to show (default 180; 0 = all); the post itself is always shown in full'}),
                      'json', 'max_requests'],
        'epilog': ['The post is shown in full (a long post\'s whole text, an article\'s whole body), after the posts it answers (parent). Its first batch of replies follows, each conversation thread as X shows it: a reply\'s depth is its place in the thread, and "reply to a post not shown" marks where X skipped posts. A reply with more under it ends with replies <handle>, which reads that branch from the reply\'s own page; more: reads the next batch of direct replies; a coverage line names the handle for the replies X hid as probable spam or low quality.',
                   'top is X\'s ranking, which by X\'s own description puts paid subscribers\' replies higher; recent is newest first and does not include the replies X hid.',
                   'A community note under a post is context other users added and rated helpful, not the author\'s words. An edited post lists its versions; post <id> opens any of them.',
                   'Several ids: one request for those posts in full, without replies; ids X did not return are named (unresolved).',
                   'requests: 1 (the post, its parents and the first replies in one read).'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    },
    'replies': {
        'help': 'Read the next batch of a post\'s replies, the replies X hid, or the replies under one reply, by handle.',
        'run': thread.replies,
        'arguments': [(('target',), {'metavar': 'HANDLE', 'help': 'The number after "replies" or in a more: line'}),
                      (('--limit',), {'type': positive, 'help': 'Replies to show; omitted: one batch, or every batch with --out. With --out it counts replies saved'}),
                      'chars', 'out', 'json', 'max_requests'],
        'epilog': ['A handle names a batch: the next batch of a post\'s direct replies, the replies X hid, or every reply one reply\'s own page lists (batch by batch). Running it again reads the same batch again, live; it is not a replay. more: prints the handle of the batch after.',
                   'requests: 1 per batch of about 30-40 replies.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
    },
    'search': {
        'help': 'Search posts, accounts or media, with X\'s search operators.',
        'run': search.search,
        'arguments': [(('target',), {'metavar': 'QUERY', 'help': 'What to search for, as typed into X: words, "phrases", OR, -exclusions and operators (from: to: since:YYYY-MM-DD until:YYYY-MM-DD min_faves: filter:links lang: …)'}),
                      (('--type',), {'choices': ['posts', 'accounts', 'media'], 'default': 'posts', 'help': 'posts, accounts (people) or media'}),
                      (('--sort',), {'choices': ['top', 'latest'], 'default': 'top', 'help': 'Posts and media: top (X\'s ranking) or latest (newest first)'})] + list(LIST),
        'epilog': ['Results are in X\'s order for this account: top is a ranking, not a sample of opinion; latest is newest first. Accounts with the same or similar names are different results (compare url and their marks).',
                   'since: and until: in the query are filters X applies itself, so such a search read to the end (stopped=exhausted) covers its window: window ... closed (server-filtered); stopped by --limit, the budget or X\'s limit it is still open. X decides which day boundaries those operators use (measured once: until:D ran to the end of D in this account\'s time zone), so check created_at at the edges.',
                   'X allows about 50 searches per 15 minutes for this account (quotes count too): a wide search costs that limit, and when it runs out the command stops with exit 10 (before any result) or stopped=rate_limited (after some), naming when it resets.',
                   'Without --limit or --out it reads one page; more: continues.',
                   'requests: 1 per page of about 20.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
    },
    'quotes': {
        'help': 'Read the posts that quote one post.',
        'run': search.quotes,
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'x.com post URL or numeric id'}),
                      (('--sort',), {'choices': ['top', 'recent'], 'default': 'top', 'help': 'top (X\'s ranking) or recent'})] + list(LIST),
        'epilog': ['Each quote is its own post with two voices: the quoter\'s words, and the quoted post shown under it with its own author. Asked the way X\'s own quotes screen asks (a search for the post\'s id and its media links), so it shares search\'s limit (about 50 per 15 minutes).',
                   'Without --limit or --out it reads one page; more: continues.',
                   'requests: 1 per page of about 20.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
    },
    'doctor': {
        'help': 'Check Aside, the browser tab, login, account protection and X\'s limits; always JSON.',
        'run': maintenance.doctor,
        'arguments': [(('--unblock',), {'action': 'store_true', 'help': 'Only after a person has checked x.com in the '
                                        'Aside browser: make one check and lift a saved block if X answers normally'})],
        'epilog': ['It opens the dedicated x.com tab if none is open (about 15-25 requests the page makes itself while '
                   'it loads, measured; 20 plus what was seen when the start of the load could not be measured) and '
                   'otherwise makes no request.',
                   'output: one JSON envelope; results[0] holds aside, tab {target_id, opened_now, reopened, '
                   'opening_measured}, login, account_id (the X account in use), blocked and block_reason, limits (X\'s '
                   'per-operation limits seen and not yet reset: {limit, remaining, reset}), requests_last_hour and '
                   'requests_last_day (every command of this account, logged), operations (what the tab\'s app '
                   'defines), signature_generator, bearer, own_request_matching (whether the skill\'s own requests are '
                   'told apart in the tab\'s timing list), idle_close_seconds, data_dir, protection_state and '
                   'holds_personal_data. A saved block is reported as exit 5 without touching the browser.',
                   'The tab is closed about 5 minutes after the last command, which stops the app\'s own polling; set '
                   'TWITTER_IDLE_SECONDS to change the delay, or to off to leave it open. TWITTER_ASIDE_ACCOUNT picks '
                   'the Aside account (default: Aside\'s own).',
                   '--unblock keeps the block while it checks: the tab\'s login and one Viewer read (one request, '
                   'outside any budget, inside X\'s Viewer limit). Only an answer for the account the block was '
                   'recorded for lifts it; anything else leaves it and exits 5 with verification_reason '
                   '(rate_limited, logged_out, account_mismatch, moved, time_limit, aside). Per-operation limits are '
                   'never cleared by it. When protection state is unreadable, it first keeps those files for a person '
                   'as <name>.unreadable-<time> and stands a block for the account they name (or none), which the '
                   'check then lifts or keeps. It means nothing unless a person has looked at x.com in the Aside '
                   'browser first.'],
        'exits': (0, 2, 3, 4, 5, 6),
    },
    'schema': {
        'help': 'Describe results, files and record fields; always JSON, no request.',
        'run': maintenance.schema,
        'arguments': [(('object',), {'nargs': '?', 'choices': maintenance.SCHEMA_OBJECTS,
                                     'help': 'What to describe; omitted: the list of objects'})],
        'epilog': ['output: one JSON envelope; results holds the requested description (result: the envelope, stop '
                   'reasons, exit codes, window coverage, request counting and the text page; out: the --out file; '
                   'post, account, trend: record fields), or one line per object.'],
        'exits': (0, 2),
    },
}
HIDDEN = {'idle': {'run': maintenance.idle,
                   'arguments': [(('--token',), {'required': True}), (('--after',), {'type': int, 'default': 300})]}}


READS = ('feed', 'profile', 'about', 'graph', 'me', 'post', 'replies', 'reposts', 'search', 'quotes')


def epilog(name, spec):
    lines = list(spec['epilog'])
    if name in READS:
        lines += [REQUESTS, TEXT_OUTPUT, JSON_OUTPUT]
        if 'out' in [a for a in spec['arguments'] if isinstance(a, str)]:
            lines.append(OUT_OUTPUT)
        lines.append(FAILURE)
    lines.append('exit codes:\n' + '\n'.join(f'  {code}  {EXIT_CODES[code]}' for code in spec['exits']))
    return '\n\n'.join(lines)


def parser(hidden=False):
    root = Parser(prog='cli.py', description=__doc__, formatter_class=argparse.RawTextHelpFormatter,
                  epilog='Run <command> --help for its arguments, output, requests and exit codes; schema describes '
                         'every output field.\n\nexit codes:\n'
                         + '\n'.join(f'  {code}  {meaning}' for code, meaning in EXIT_CODES.items()))
    root.add_argument('--verbose', action='store_true', help='Write scrubbed request metadata to stderr')
    commands = root.add_subparsers(dest='command', required=True, metavar='<command>')
    for name, spec in COMMANDS.items():
        sub = commands.add_parser(name, help=spec['help'], description=spec['help'], epilog=epilog(name, spec),
                                  formatter_class=argparse.RawTextHelpFormatter, prog=f'cli.py {name}')
        for argument in spec['arguments']:
            flags, settings = OPTIONS[argument] if isinstance(argument, str) else argument
            sub.add_argument(*flags, **settings)
    if hidden:  # the idle cleanup the skill starts itself; not part of the help
        for name, spec in HIDDEN.items():
            sub = commands.add_parser(name, prog=f'cli.py {name}')
            for flags, settings in spec['arguments']:
                sub.add_argument(*flags, **settings)
    return root


def validate(options):
    for key in ('target', 'out'):
        values = options.get(key)
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise TwitterError(2, f'The {key} contains a line break or another control character.',
                                   'Pass it on one line.')
    if options.get('since') and options.get('until') and options['since'] > options['until']:
        raise TwitterError(2, '--since must not be later than --until.', 'Swap the two dates.')
    if options['command'] == 'replies' and not (options['target'].isascii() and options['target'].isdigit()):
        raise TwitterError(2, 'A replies handle is the number printed after "replies" or in a more: line.',
                           'Copy the whole replies or more: line.')
    if options['command'] == 'post' and len(options['target']) > 1 and (options.get('limit') or options['sort'] != 'top'):
        raise TwitterError(2, 'Several posts are read without replies, so --limit and --sort do not apply.',
                           'Drop them, or read one post.')
    if options['command'] == 'search' and not options['target'].strip():
        raise TwitterError(2, 'Search text must not be empty.', 'Pass the words to search for.')
    if options.get('after') and options.get('out'):
        raise TwitterError(2, '--after and --out cannot be combined; --out resumes its own file.',
                           'Rerun the same command with the same --out path.')


def invocation():
    """This file as it was invoked, double-quoted the way the skill's allowed-tools spells it."""
    return 'uv run "' + re.sub(r'([\\"$`])', r'\\\1', os.path.abspath(__file__)) + '"'


def command_line(words):
    return invocation() + ' ' + shlex.join(words)


def emit(kind, envelope, options):
    if isinstance(envelope.get('next'), list):
        envelope['next'] = command_line(envelope['next'])
    machine = options.get('json') or options['command'] in ('doctor', 'schema', 'idle')
    if options.get('out') and envelope.get('out') is not None and (envelope['ok'] or envelope.get('count')):
        print(json.dumps({k: v for k, v in envelope.items() if k != 'results'}, ensure_ascii=False) if machine
              else render_summary(envelope))
    elif machine or (not envelope['ok'] and not envelope.get('results')):
        print(json.dumps(envelope, ensure_ascii=False))
    else:
        print(render_page(envelope, chars=options.get('chars'), command=options['command']))
    return KIND_EXIT[kind]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    options = {'command': None}
    try:
        options = vars(parser(hidden=bool(argv) and argv[0] in HIDDEN).parse_args(argv))
        validate(options)
        if options['command'] == 'schema':
            options['exit_codes'] = [(code, meaning, [k for k, c in KIND_EXIT.items() if c == code])
                                     for code, meaning in EXIT_CODES.items()]
        spec = COMMANDS.get(options['command']) or HIDDEN[options['command']]
        kind, envelope = spec['run'](options)
    except TwitterError as error:
        kind, envelope = failure_envelope(error, options.get('command'))
    return emit(kind, envelope, options)


if __name__ == '__main__':
    sys.exit(main())
