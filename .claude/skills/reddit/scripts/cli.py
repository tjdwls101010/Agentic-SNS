#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read Reddit through the logged-in Aside browser: feeds, communities, posts and comment trees, people, search."""
import argparse
import json
import os
import re
import shlex
import sys
from datetime import date, datetime, time, timedelta

from reddit import about, listing, maintenance, thread
from reddit.errors import RedditError
from reddit.render import render_page, render_summary
from reddit.results import failure_envelope

EXIT_CODES = {
    0: 'success: records, a stop that more: or the same --out command resumes (budget, Reddit\'s window spent), an '
       'already complete --out file, or a doctor/schema result',
    2: 'invalid arguments, or a handle or --out file that belongs to another query, an earlier version or has expired',
    3: 'Aside is unavailable, timed out or answered invalidly, or which Aside account to use is unclear',
    4: 'Reddit login is required in the Aside browser, or it is logged in to another Reddit account than a '
       'continuation was read with',
    5: 'requests are blocked for this account (browser challenge, rate limit, or unreadable protection state)',
    6: 'a request failed before any record was read (including a response shape this skill does not know)',
    7: 'Reddit explicitly returned nothing, or nothing fell inside the window',
    8: 'partial: records were read and then a request failed, or the budget ran out with nothing to continue from',
    9: 'the target cannot be read by this account: missing, private, quarantined, banned, suspended, or a profile '
       'whose history is not visible — retrying does not change it',
}
KIND_EXIT = {'records': 0, 'resumable': 0, 'complete': 0, 'maintenance': 0, 'argument': 2, 'aside': 3, 'login': 4,
             'blocked': 5, 'failed': 6, 'empty': 7, 'partial': 8, 'unavailable': 9}

REQUESTS = ('how requests are counted and paced: every page, post read, comment expansion, redirect and share-link '
            'hop counts, and so does the account check (/api/me.json, 1 request) that a command reading something it '
            'can continue (more: or --out) makes first. Requests are spaced 1-2 s apart across every invocation of '
            'the account, longer when Reddit says its ten-minute window is running low, so N requests take at least '
            'N to 2N seconds. A command never waits out Reddit\'s window: when the bucket it needs is spent it stops '
            '(stopped=window_spent) and more: resumes after the reset the first line shows.')
TEXT_OUTPUT = ('output: first line "<command> · … · N shown · stopped=<reason> · requests=<used>/<budget> · reddit '
               'window <left>/<limit>, resets in <s>s"; dated reads add "window <since>..<until> <tz> · <coverage>"; '
               'then one record per [p1]/[c1]/[s1]/[u1] label, each ending with the URL that names it alone '
               '(post <url>, comments <url>, r/ and u/ names for about and profile); text is shown as '
               'text[N of M chars shown] with > quotes as ❝…❞; then coverage: lines; last, more: <command> when '
               'reading can continue.')
JSON_OUTPUT = ('--json: one JSON envelope instead (ok, command, stop_reason, request_count, max_requests, '
               'reddit_window, account, coverage, next, error, message, fix, results with full texts); schema result '
               'describes every field.')
OUT_OUTPUT = ('--out FILE: records go to an NDJSON file a whole page at a time and stdout gets one summary line (one '
              'JSON object with --json); rerun the same command with the same file to resume. --out cannot be '
              'combined with --after. The file holds other people\'s posts and comments: keep it outside the '
              'repository.')
FAILURE = ('failure: one JSON envelope (ok false, error, message, fix) when nothing was read; records read before a '
           'failure print as usual, followed by a "coverage: incomplete — <message> fix: <fix>" line (with --json, '
           'in the envelope).')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RedditError(2, message, f'Run {self.prog} --help.')


def positive(value):
    if value.isascii() and value.isdigit() and int(value) > 0:
        return int(value)
    raise argparse.ArgumentTypeError('expected a positive integer')


def count(value):
    if value.isascii() and value.isdigit():
        return int(value)
    raise argparse.ArgumentTypeError('expected 0 or a positive integer')


def budget(value):
    number = positive(value)
    # 성진: 호출당 100회 상한은 실계정 보호용(R7) — Reddit의 일반 버킷 하나(10분 100)를 넘지 않게. 일회용 계정이면 올려도 됨
    if number > 100:
        raise argparse.ArgumentTypeError('at most 100 requests per invocation')
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
    'limit': (('--limit',), {'type': positive, 'help': 'Records to show (default: one page of 25); with --out, records to save'}),
    'since': (('--since',), {'type': day, 'metavar': 'DAY', 'help': 'First local day to include, YYYY-MM-DD (only with --sort new)'}),
    'until': (('--until',), {'type': day, 'metavar': 'DAY', 'help': 'Last local day to include, YYYY-MM-DD (only with --sort new)'}),
    'chars': (('--chars',), {'type': count, 'help': 'Characters of each text to show (default 180; 0 = all received); --json and --out keep all'}),
    'after': (('--after',), {'type': positive, 'metavar': 'HANDLE', 'help': 'Continue from the numbered handle a more: line printed'}),
    'out': (('--out',), {'metavar': 'FILE', 'help': 'Collect into this NDJSON file, one committed page at a time; rerun the same command to resume'}),
    'json': (('--json',), {'action': 'store_true', 'help': 'Print one JSON envelope instead of text'}),
    'max_requests': (('--max-requests',), {'type': budget, 'default': 25, 'metavar': 'N', 'help': 'Requests this invocation may make (default 25, at most 100)'}),
}
LIST = ('limit', 'chars', 'after', 'out', 'json', 'max_requests')
WINDOW = ('since', 'until')

TIME = (('--time',), {'choices': listing.TIMES, 'help': 'Reddit\'s own period for a ranking (top, controversial): hour, day, week, month, year, all. Not a date window'})
COMMANDS = {
    'feed': {
        'help': 'Read your home feed, a page at a time.',
        'run': listing.feed,
        'arguments': [(('--sort',), {'choices': listing.FEED_SORTS, 'default': 'best', 'help': 'best (default) and hot are Reddit\'s ranking for this account; new is newest first; top with --time'}),
                      TIME, *WINDOW, *LIST],
        'epilog': ['The home feed is Reddit\'s choice for this account (its subscriptions and what it ranks), not Reddit as a whole.',
                   'A page asks Reddit for 100 posts and shows 25 (--limit); more: shows the rest of the page with no request, then reads the next page.',
                   '--since/--until (local days, --until included) work with --sort new only and keep the posts written on those days; --time is Reddit\'s period for top. The window line says whether the window was covered.',
                   'requests: 1 account check + 1 per page of 100; a more: that only shows what the last page already brought makes none.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'sub': {
        'help': 'Read a community\'s listing (r/name, r/a+b, r/popular, r/all).',
        'run': listing.sub,
        'arguments': [(('target',), {'help': 'r/<name>, a community URL, or r/<a+b> for several at once (r/popular and r/all are Reddit-wide)'}),
                      (('--sort',), {'choices': listing.SUB_SORTS, 'default': 'hot', 'help': 'hot (default), new (newest first), top or controversial (with --time), rising'}),
                      TIME, *WINDOW, *LIST],
        'epilog': ['A community\'s listing is that community\'s own; r/popular and r/all are Reddit-wide rankings. Pinned posts (moderators\' announcements, often old) sit at the top of hot; under new they sit at their own date.',
                   'A page asks Reddit for 100 posts and shows 25 (--limit); more: shows the rest of the page with no request, then reads the next page.',
                   '--since/--until (local days, --until included) work with --sort new only: the window closes at the first page wholly older than --since; if the listing ends first, the result is partial (8) because the window was not covered.',
                   'A private, quarantined or banned community is unavailable (exit 9), which is not the same as empty (7).',
                   'requests: 1 account check + 1 per page of 100; a more: that only shows what the last page already brought makes none.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
    'profile': {
        'help': 'Read a redditor\'s public activity: posts and comments, newest first by default.',
        'run': listing.profile,
        'arguments': [(('target',), {'help': 'u/<name> or a profile URL'}),
                      (('--type',), {'choices': listing.PROFILE_TYPES, 'default': 'overview', 'help': 'overview (posts and comments together, default), posts or comments'}),
                      (('--sort',), {'choices': listing.PROFILE_SORTS, 'default': 'new', 'help': 'new (default), hot, top or controversial (with --time)'}),
                      TIME, *WINDOW, *LIST],
        'epilog': ['A public history is that account\'s observed activity on Reddit. An account can hide its history from other accounts, or hide some communities from it: what is shown may leave things out.',
                   'An empty first page (no --after, --time, --since or --until) is checked against the account\'s karma for that kind (one more request): with karma it is a history that is not visible — hidden or deleted — (exit 9, reason history_not_visible), not an empty one; with no karma it is reported as observed (exit 7). A filtered empty result is just empty (7).',
                   'A page asks Reddit for 100 items and shows 25 (--limit); more: shows the rest of the page with no request. --since/--until need --sort new.',
                   'requests: 1 account check + 1 per page of 100, +1 when an empty first page is checked against karma.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
    'about': {
        'help': 'Read a community\'s card and rules, or a user\'s card.',
        'run': about.about,
        'arguments': [(('target',), {'help': 'r/<name> or u/<name> (or their URLs); a bare word is refused'}), 'chars', 'json', 'max_requests'],
        'epilog': ['A community: name, title, short description, sidebar, subscribers, active users, age, access type (public, restricted, private) and NSFW, then its rules. A user: karma by kind, account age, profile description, and the moderator, admin and verified markers. Karma, age and flair say what an account did on Reddit, not who the person is.',
                   'One live read tied to no handle or file, so the Reddit account is not checked first (the first line says account not checked).',
                   'requests: 2 for a community (card, rules), 1 for a user.'],
        'exits': (0, 2, 3, 4, 5, 6, 9),
    },
    'post': {
        'help': 'Read one post in full and the first batch of its comments.',
        'run': thread.post,
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'A post URL, id or redd.it link; a comment link opens the post at that comment; a share link (/r/<sub>/s/...) is resolved first'}),
                      (('--sort',), {'choices': thread.COMMENT_SORTS, 'default': 'best', 'help': 'Comment order: best (default), top, new, controversial, old, qa'}),
                      (('--limit',), {'type': positive, 'help': 'Comments to show (default 25)'}),
                      (('--depth',), {'type': count, 'help': 'Reply levels to show (default 2; 0 = top-level comments only)'}),
                      (('--context',), {'type': count, 'help': 'For a comment link: how many of its ancestors Reddit sends with it'}),
                      'chars', 'json', 'max_requests'],
        'epilog': ['The post is shown in full. Reddit sends up to 500 of its comments, 10 levels deep, in one answer; the rest are gaps. The comments shown are the first batch in depth-first order within --depth: each [c] line names the comment it answers (reply-to=), and the first line of the thread: line counts what Reddit reports (deleted and removed included), what arrived, what is shown, what is deeper than --depth and what is left to expand. more: continues the same reading (comments --after).',
                   'The sort is the order inside each batch, not across batches. A thread\'s suggested sort and contest mode (random order, hidden scores) are on the thread: line.',
                   'Every comment carries its permalink: comments <that url> opens it in full with what hangs under it.',
                   'requests: 1 account check + 1 (a share link adds 1 per redirect, at most 3).'],
        'exits': (0, 2, 3, 4, 5, 6, 8, 9),
    },
    'comments': {
        'help': 'Read the next batch of a thread, or one comment in full with what hangs under it.',
        'run': thread.comments,
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'A post URL (its next batch), or a comment\'s permalink (that comment, always, with its ancestors as context and what hangs under it)'}),
                      (('--sort',), {'choices': thread.COMMENT_SORTS, 'default': 'best', 'help': 'Comment order (default best); a reading keeps its order'}),
                      (('--limit',), {'type': positive, 'help': 'Comments to show (default 25); with --out, comments to save'}),
                      (('--depth',), {'type': count, 'help': 'Reply levels to show (default 2), counted from the linked comment for a comment link'}),
                      'chars', 'after', 'out', 'json', 'max_requests'],
        'epilog': ['A batch comes from the snapshot the last post or comments read left (for a day): no request while it holds comments not yet shown. When none is left within --depth, the next gaps are expanded: up to 100 comment ids across gaps in one request, and a "continue this thread" branch in one request each. A comment Reddit lists but does not send when asked is counted as asked for but never sent (deleted or removed).',
                   'A comment link is answered from the latest snapshot of its post when it holds that comment (no request); otherwise its subtree is read (1 request).',
                   'With --out the whole thread is written: the post once, then every comment flat (parent_id and depth), a page per expansion; rerun the same command to resume the same reading even after its snapshot expired.',
                   'requests: none from the snapshot; otherwise 1 account check + 1 per expansion (or 1 for a new read); --max-requests bounds a large thread, more: continues.'],
        'exits': (0, 2, 3, 4, 5, 6, 8, 9),
    },
    'doctor': {
        'help': 'Check Aside, the Reddit login and account protection; always JSON.',
        'run': maintenance.doctor,
        'arguments': [(('--unblock',), {'action': 'store_true', 'help': 'Only after a person has checked Reddit in the Aside browser (and solved any challenge there): make one check and lift a saved challenge if Reddit answers normally'})],
        'epilog': ['requests: 1 (/api/me.json, the login check). A saved block is reported as exit 5 without any request.',
                   'output: one JSON envelope; results[0] holds aside_account (the Aside account used: REDDIT_ASIDE_ACCOUNT, or the one `aside account status` marks active), reddit_account (who the browser is logged in to Reddit as), blocked and block_reason, buckets (each of Reddit\'s request buckets this account has used: remaining, limit, resets_in, rate_limited_for, wait_seconds), requests_last_hour and requests_last_day (every command of this Aside account, logged), data_dir, snapshot_bytes, protection_state and holds_personal_data.',
                   '--unblock keeps the block while it checks: one /api/me.json request. Only a clean answer lifts a challenge; a challenge again, a logged-out answer or an interrupted run leaves it. A bucket\'s rate limit or spent window is never lifted: it ends at Reddit\'s reset. It means nothing unless a person has looked at Reddit in the Aside browser first.'],
        'exits': (0, 2, 3, 4, 5, 6),
    },
    'schema': {
        'help': 'Describe results, files and record fields; always JSON, no request.',
        'run': maintenance.schema,
        'arguments': [(('object',), {'nargs': '?', 'choices': maintenance.SCHEMA_OBJECTS, 'help': 'What to describe; omitted: the list of objects'})],
        'epilog': ['output: one JSON envelope; results holds the requested description (result: the envelope, stop reasons, exit codes, window coverage, request counting and the text page; out: the --out file; post, comment, subreddit, user: record fields), or one line per object.'],
        'exits': (0, 2),
    },
}
READS = ('feed', 'sub', 'profile', 'about', 'post', 'comments')


def epilog(name, spec):
    lines = list(spec['epilog'])
    if name in READS:
        lines += [REQUESTS, TEXT_OUTPUT, JSON_OUTPUT]
        if 'out' in [a for a in spec['arguments'] if isinstance(a, str)]:
            lines.append(OUT_OUTPUT)
        lines.append(FAILURE)
    lines.append('exit codes:\n' + '\n'.join(f'  {code}  {EXIT_CODES[code]}' for code in spec['exits']))
    return '\n\n'.join(lines)


def parser():
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
    return root


def validate(options):
    for key in ('target', 'out', 'text', 'within'):
        value = options.get(key)
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise RedditError(2, f'The {key} contains a line break or another control character.', 'Pass it on one line.')
    if options.get('since') and options.get('until') and options['since'] > options['until']:
        raise RedditError(2, '--since must not be later than --until.', 'Swap the two dates.')
    if (options.get('since') or options.get('until')) and options.get('sort') not in (None, 'new'):
        raise RedditError(2, 'A date window needs --sort new: other orders are rankings, not a timeline.',
                          'Use --sort new with --since/--until, or --time for a ranking\'s server period.')
    if options.get('after') and options.get('out'):
        raise RedditError(2, '--after and --out cannot be combined; --out resumes its own file.',
                          'Rerun the same command with the same --out path.')


def invocation():
    """This file as it was invoked, double-quoted the way the skill's allowed-tools spells it."""
    return 'uv run "' + re.sub(r'([\\"$`])', r'\\\1', os.path.abspath(__file__)) + '"'


def command_line(words):
    return invocation() + ' ' + shlex.join(words)


def emit(kind, envelope, options):
    if isinstance(envelope.get('next'), list):
        envelope['next'] = command_line(envelope['next'])
    machine = options.get('json') or options['command'] in ('doctor', 'schema')
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
        options = vars(parser().parse_args(argv))
        validate(options)
        if options['command'] == 'schema':
            options['exit_codes'] = [(code, meaning, [k for k, c in KIND_EXIT.items() if c == code])
                                     for code, meaning in EXIT_CODES.items()]
        kind, envelope = COMMANDS[options['command']]['run'](options)
    except RedditError as error:
        kind, envelope = failure_envelope(error, options.get('command'))
    return emit(kind, envelope, options)


if __name__ == '__main__':
    sys.exit(main())
