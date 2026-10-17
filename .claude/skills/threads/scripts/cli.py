#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read Threads through the logged-in Aside browser: feeds, posts and replies, profiles, search."""
import argparse
import json
import os
import re
import shlex
import sys
from datetime import date, datetime, time, timedelta

from threads import about, listing, maintenance, search, thread
from threads.errors import ThreadsError
from threads.render import render_page, render_summary
from threads.results import failure_envelope

EXIT_CODES = {
    0: 'success: records, a budget stop that more: or the same --out command resumes, an already complete --out file, '
       'or a doctor/schema result',
    2: 'invalid arguments, or a handle or --out file that belongs to another query, an earlier version or has expired',
    3: 'Aside or the browser tab is unavailable, timed out or answered invalidly',
    4: 'Threads login is required in the Aside browser',
    5: 'requests are blocked for this account (checkpoint, rate limit, or unreadable protection state)',
    6: 'a request failed before any record was read (including a query Threads no longer accepts)',
    7: 'Threads explicitly returned nothing, or nothing fell inside the window',
    8: 'partial: records were read and then a request failed, or the budget ran out with nothing to continue from',
    9: 'the target cannot be read by this account: deleted, private and not followed, or a post that redirected away',
}
KIND_EXIT = {'records': 0, 'resumable': 0, 'complete': 0, 'maintenance': 0, 'argument': 2, 'aside': 3, 'login': 4,
             'blocked': 5, 'failed': 6, 'empty': 7, 'partial': 8, 'unavailable': 9}

REQUESTS = ('how requests are counted: every GraphQL query, document read and retry counts, and so does every Threads '
            'request the dedicated tab finishes while the command runs. Opening the tab (or loading it again after it '
            'was emptied) is prepaid at 40 and shown as "tab opened", outside --max-requests; learning a query '
            'Threads refused reads one document per try, also outside it (at most 3 tries and one reload a command). '
            'Requests the open tab made between commands are shown as unwatched=, not charged, but a block seen '
            'there stops the command before it sends anything. Static CDN files do not count. All invocations share '
            'one lock and 1-2 s pacing for the account. The tab is emptied about 5 minutes after the last command.')
TEXT_OUTPUT = ('output: first line "<command> · … · N shown · stopped=<reason> · requests=<used>/<budget>"; dated reads '
               'add "window <since>..<until> · <coverage>"; then one record per [p1]/[r1]/[a1] label, each ending with '
               'the arguments of the next command (url: post <url> opens that one post; author; replies <handle>); '
               'text is shown as text[N of M chars shown]; then coverage: lines; last, more: <command> when reading '
               'can continue.')
JSON_OUTPUT = ('--json: one JSON envelope instead (ok, command, stop_reason, request_count, max_requests, coverage, '
               'next, error, message, fix, results, with full texts); schema result describes every field.')
OUT_OUTPUT = ('--out FILE: records go to an NDJSON file a whole page at a time and stdout gets one summary line (one '
              'JSON object with --json); rerun the same command with the same file to resume. --out cannot be '
              'combined with --after. The file holds other people\'s posts: keep it outside the repository.')
FAILURE = ('failure: one JSON envelope (ok false, error, message, fix) when nothing was read; records read before a '
           'failure print as usual, followed by a "coverage: incomplete — <message> fix: <fix>" line (with --json, in '
           'the envelope\'s results).')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ThreadsError(2, message, f'Run {self.prog} --help.')


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
    # 성진: 호출당 400회 상한은 실계정 보호용(하루 누적 상한은 두지 않음, T8). 일회용 계정으로 바꾸면 올려도 됨
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
    'max_requests': (('--max-requests',), {'type': budget, 'default': 25, 'metavar': 'N', 'help': 'Requests this invocation may make (default 25, at most 400)'}),
}
LIST = ('limit', 'chars', 'after', 'out', 'json', 'max_requests')

COMMANDS = {
    'feed': {
        'help': 'Read your home feed, a page at a time.',
        'run': listing.feed,
        'arguments': [(('--feed',), {'choices': ['foryou', 'following'], 'default': 'foryou', 'help': 'foryou: the posts Threads ranks for this account; following: the accounts it follows, newest first'}),
                      'since', 'until'] + list(LIST),
        'epilog': ['foryou is what Threads chose to show this account, not everything; following holds only the accounts it follows.',
                   'A window keeps the dated posts written on its local days (posts without a date are left out and counted). Only --feed following can close a --since window (it stops at the first page wholly older than --since, while the feed stays newest first); foryou is a sample of the window.',
                   'A feed entry can carry several posts (a post and a reply to it, or an author continuing a post): they are shown together, and the later ones say reply-to= or continuation of.',
                   'Without --limit, a window or --out it reads one page; more: continues.',
                   'requests: 1 per page of about 5-10 posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'profile': {
        'help': 'Read a profile\'s tab: threads, replies, reposts or media.',
        'run': listing.profile,
        'arguments': [(('target',), {'help': 'Threads @handle or profile URL; a tab URL such as /@name/replies reads that tab'}),
                      (('--tab',), {'choices': ['threads', 'replies', 'reposts', 'media'], 'help': 'The tab (default: the URL\'s tab, else threads)'}),
                      'since', 'until'] + list(LIST),
        'epilog': ['threads and replies are newest first, so a --since window closes at the first page wholly older than it (a pinned post sits first whatever its date and does not close it). reposts and media are in no date order: a window covers them only when read to the end. A repost carries the original post\'s date, not when it was reposted.',
                   'A private profile this account does not follow is unavailable (exit 9), which is not the same as empty.',
                   'Without --limit, a window or --out it reads one page; more: continues.',
                   'requests: 1 to find the profile, then 1 per page (about 10 posts on threads). The first read of the replies, reposts or media tab in a while also reads that tab\'s screen once to learn its query (outside --max-requests).'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
    'about': {
        'help': 'Read a profile\'s card: name, bio, links, verification, privacy, follower count.',
        'run': about.about,
        'arguments': [(('target',), {'help': 'Threads @handle or profile URL'}), 'json', 'max_requests'],
        'epilog': ['Threads publishes a follower count but no following or mutual count: those are shown as ? (unknown); graph following lists the accounts.',
                   'A verified badge and a bio are what the account claims about itself.',
                   'requests: 2 (find the profile, read its card).'],
        'exits': (0, 2, 3, 4, 5, 6, 8, 9),
    },
    'graph': {
        'help': 'Read the accounts that follow a profile, or that it follows.',
        'run': listing.graph,
        'arguments': [(('target',), {'help': 'Threads @handle or profile URL'}),
                      (('relation',), {'choices': ['followers', 'following'], 'help': 'followers or following'})] + list(LIST),
        'epilog': ['followers: Threads may send its own sample rather than the whole list (stopped=server_capped); reported_total is the count the profile reports. following pages on.',
                   'Without --limit or --out it reads one page; more: continues.',
                   'requests: 1 to find the profile, then 1 per page of about 10-20 accounts. The first next page of following in a while may read the profile screen once to learn its query (outside --max-requests).'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
    'me': {
        'help': 'Read the posts you liked or saved (one batch).',
        'run': listing.me,
        'arguments': [(('collection',), {'choices': ['liked', 'saved'], 'help': 'liked or saved'})] + list(LIST),
        'epilog': ['One batch, as Threads sends it (stopped=not_paginable): not your whole history.',
                   'requests: 1.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'search': {
        'help': 'Search posts, tags or accounts.',
        'run': search.search,
        'arguments': [(('target',), {'metavar': 'TEXT', 'help': 'What to search for (a tag without #)'}),
                      (('--type',), {'choices': ['posts', 'tags', 'accounts'], 'default': 'posts', 'help': 'posts (by words), tags (posts under a tag) or accounts (one batch of profiles)'}),
                      (('--sort',), {'choices': ['top', 'recent'], 'default': 'top', 'help': 'Posts and tags: top (Threads ranks them) or recent (newest first)'}),
                      'since', 'until',
                      (('--from',), {'metavar': 'HANDLE', 'help': 'Posts and tags: only posts by this @handle'})] + list(LIST),
        'epilog': ['Results are in Threads\' order for this account: top is a ranking, not a sample of opinion; recent is newest first. Accounts with the same or similar names are different results (compare url and verified).',
                   '--since, --until and --from are filters Threads applies itself (posts and tags), so a filtered search read to the end (stopped=exhausted) covers its window in either order: window ... closed (server-filtered); stopped by --limit or the budget, it is still open.',
                   'Without --limit, a date or --out it reads one page; more: continues (accounts are one batch).',
                   'requests: 1 per page of about 10 posts; accounts 1.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'post': {
        'help': 'Read one post in full with its parent chain and first batch of replies.',
        'run': thread.post,
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'Threads post URL (/@name/post/<code> or /t/<code>) or its shortcode'}),
                      (('--sort',), {'choices': ['top', 'recent'], 'default': 'top', 'help': 'Reply order: top (Threads ranks them) or recent (newest first)'}),
                      (('--limit',), {'type': positive, 'help': 'Direct replies to show from the first batch (each with what hangs under it)'}),
                      (('--chars',), {'type': chars, 'help': 'Characters of each parent and reply to show (default 180; 0 = all); the post itself is always shown in full'}),
                      'json', 'max_requests'],
        'epilog': ['The post is shown in full, after the posts it answers (parent). Its first batch of direct replies follows, each with what hangs under it: replies to it (reply-to=) and the replier continuing (continuation of). A reply with more under it ends with replies <handle>, which opens that branch; more: reads the next batch of direct replies. A replies line says how many direct replies Threads reports, how many arrived and an estimate of those never received.',
                   'Every record\'s url opens that one post with post <url> (a reply is a post too).',
                   'requests: 3 (the post, its parents, its first replies); no screen is opened.'],
        'exits': (0, 2, 3, 4, 5, 6, 8, 9),
    },
    'replies': {
        'help': 'Read the next batch of a post\'s replies, or the replies under one reply, by the handle post printed.',
        'run': thread.replies,
        'arguments': [(('target',), {'metavar': 'HANDLE', 'help': 'The number after "replies" (a branch) or in a more: line (the next batch)'}),
                      (('--limit',), {'type': positive, 'help': 'Replies to show; omitted: one batch, or every batch with --out. With --out it counts replies saved'}),
                      'chars', 'out', 'json', 'max_requests'],
        'epilog': ['A handle names a batch: the next batch of a post\'s direct replies, or the replies under one reply (every reply that reply\'s own page lists, batch by batch, each with what hangs under it). Running it again reads the same batch again, live; it is not a replay. more: prints the handle of the batch after.',
                   'requests: 1 per batch of about 10 replies.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'quotes': {
        'help': 'Read the posts that quote one post (one batch).',
        'run': listing.activity,
        'arguments': [(('target',), {'help': 'Post URL or shortcode'})] + list(LIST),
        'epilog': ['Each quote is its own post ([p] label, role quote), shown with its author and full text; post <url> opens it with its media and replies. Threads sends one batch of up to about 100, in its own order: when it reports more (reported_total), the rest cannot be asked for (stopped=server_capped).',
                   'requests: 1.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'reposts': {
        'help': 'Read the accounts that reposted one post (one batch).',
        'run': listing.activity,
        'arguments': [(('target',), {'help': 'Post URL or shortcode'})] + list(LIST),
        'epilog': ['Each account ([a] label) with when it reposted. Threads sends one batch of up to about 100, in its own order: when it reports more (reported_total), the rest cannot be asked for (stopped=server_capped).',
                   'requests: 1.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'doctor': {
        'help': 'Check Aside, the browser tab, login and account protection; always JSON.',
        'run': maintenance.doctor,
        'arguments': [(('--unblock',), {'action': 'store_true', 'help': 'Only after a person has checked Threads in the Aside browser: make one check and lift a saved block if Threads answers normally'})],
        'epilog': ['It opens the dedicated www.threads.com tab if none is open (about 34 requests the page makes itself, prepaid at 40) and otherwise makes no request.',
                   'output: one JSON envelope; results[0] holds aside, tab {target_id, opened_now, reopened}, login, account_id (the Threads account in use), blocked and block_reason, requests_last_hour and requests_last_day (every command of this account, logged), queries (which read queries are live in the tab), idle_blank_seconds, data_dir, protection_state and holds_personal_data. A saved block is reported as exit 5 without touching the browser.',
                   'The tab is emptied (about:blank) about 5 minutes after the last command, which stops the app\'s own polling; set THREADS_IDLE_SECONDS to change the delay, or to off to leave the tab open. THREADS_ASIDE_ACCOUNT picks the Aside account (default: Aside\'s own).',
                   '--unblock keeps the block while it checks: the tab\'s state and one document read (one request, outside any budget). Only a clean answer lifts it; a checkpoint, a login page, a lost tab or an interrupted run leaves it. It means nothing unless a person has looked at Threads in the Aside browser first.'],
        'exits': (0, 2, 3, 4, 5, 6),
    },
    'schema': {
        'help': 'Describe results, files and record fields; always JSON, no request.',
        'run': maintenance.schema,
        'arguments': [(('object',), {'nargs': '?', 'choices': maintenance.SCHEMA_OBJECTS, 'help': 'What to describe; omitted: the list of objects'})],
        'epilog': ['output: one JSON envelope; results holds the requested description (result: the envelope, stop reasons, exit codes, window coverage, request counting and the text page; out: the --out file; post, account: record fields), or one line per object.'],
        'exits': (0, 2),
    },
}
READS = ('feed', 'profile', 'about', 'graph', 'me', 'search', 'post', 'replies', 'quotes', 'reposts')
HIDDEN = {'idle': {'run': maintenance.idle,
                   'arguments': [(('--token',), {'required': True}), (('--after',), {'type': int, 'default': 300})]}}


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
                  epilog='Read-only. Run <command> --help for its arguments, output, requests and exit codes; schema '
                         'describes every output field.\n\nexit codes:\n'
                         + '\n'.join(f'  {code}  {meaning}' for code, meaning in EXIT_CODES.items()))
    root.add_argument('--verbose', action='store_true', help='Write scrubbed request metadata to stderr')
    commands = root.add_subparsers(dest='command', required=True, metavar='<command>')
    for name, spec in COMMANDS.items():
        sub = commands.add_parser(name, help=spec['help'], description=spec['help'], epilog=epilog(name, spec),
                                  formatter_class=argparse.RawTextHelpFormatter, prog=f'cli.py {name}')
        for argument in spec['arguments']:
            flags, settings = OPTIONS[argument] if isinstance(argument, str) else argument
            sub.add_argument(*flags, **settings)
    if hidden:  # the idle blanker the skill starts itself; not part of the help
        for name, spec in HIDDEN.items():
            sub = commands.add_parser(name, prog=f'cli.py {name}')
            for flags, settings in spec['arguments']:
                sub.add_argument(*flags, **settings)
    return root


def validate(options):
    for key in ('target', 'out'):
        value = options.get(key)
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ThreadsError(2, f'The {key} contains a line break or another control character.', 'Pass it on one line.')
    if options.get('since') and options.get('until') and options['since'] > options['until']:
        raise ThreadsError(2, '--since must not be later than --until.', 'Swap the two dates.')
    if options['command'] == 'replies' and not (options['target'].isascii() and options['target'].isdigit()):
        raise ThreadsError(2, 'A replies handle is the number printed after "replies" or in a more: line.',
                           'Copy the whole replies or more: line.')
    if options['command'] == 'search':
        if not options['target'].strip():
            raise ThreadsError(2, 'Search text must not be empty.', 'Pass the words to search for.')
        if options['type'] == 'accounts' and any(options.get(k) for k in ('since', 'until', 'from')):
            raise ThreadsError(2, '--since, --until and --from filter posts and tags, not accounts.',
                               'Drop them, or search posts.')
        if options['type'] == 'accounts' and options.get('sort') == 'recent':
            raise ThreadsError(2, '--sort applies to posts and tags; account search is one batch in Threads\' order.',
                               'Drop --sort.')
    if options.get('after') and options.get('out'):
        raise ThreadsError(2, '--after and --out cannot be combined; --out resumes its own file.',
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
    except ThreadsError as error:
        kind, envelope = failure_envelope(error, options.get('command'))
    return emit(kind, envelope, options)


if __name__ == '__main__':
    sys.exit(main())
