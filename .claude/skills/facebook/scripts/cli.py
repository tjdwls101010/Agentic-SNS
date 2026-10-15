#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read Facebook through the logged-in Aside browser: feed, posts, comments, profiles, pages, groups, search."""
import argparse
import json
import os
import re
import shlex
import sys
from datetime import date

from facebook import about, listing, maintenance, search, thread
from facebook.errors import FacebookError
from facebook.render import render_page, render_summary
from facebook.results import failure_envelope

EXIT_CODES = {
    0: 'success: records, a budget stop that more: or the same --out command resumes, an already complete --out file, '
       'or a doctor/schema result',
    2: 'invalid arguments, or a handle or --out file that belongs to another query, an earlier version or has expired',
    3: 'Aside or the browser tab is unavailable, timed out or answered invalidly',
    4: 'Facebook login is required in the Aside browser',
    5: 'requests are blocked for this account (checkpoint, rate limit, or unreadable protection state)',
    6: 'a request failed before any record was read (including a query Facebook no longer accepts)',
    7: 'Facebook explicitly returned nothing, or nothing fell inside the window',
    8: 'partial: records were read and then a request failed, or the budget ran out with nothing to continue from',
}
KIND_EXIT = {'records': 0, 'resumable': 0, 'complete': 0, 'maintenance': 0, 'argument': 2, 'aside': 3, 'login': 4,
             'blocked': 5, 'failed': 6, 'empty': 7, 'partial': 8}

REQUESTS = ('how requests are counted: every GraphQL query, page fetch and retry counts, and so does every facebook.com request '
            'the dedicated tab finishes while the command runs. What the page itself loads is prepaid: opening the '
            'tab the first time is charged 30 (shown as "tab opened", not charged to --max-requests), and moving it '
            'to the screen that loads a current query id, when Facebook no longer accepts a stored one, is charged '
            '10; more is charged when the page loads more, and requests it finishes later use up those reservations '
            'first. So a reading can end above --max-requests by that excess; nothing more is sent after. fbcdn.net '
            'static files do not count. A rate limit on any of the tab\'s requests, even one that finished between '
            'commands or on a reload, blocks before the next request is sent. All invocations share one lock and '
            '1-2 s pacing for the account.')
TEXT_OUTPUT = ('output: first line "<command> · … · N shown · stopped=<reason> · requests=<used>/<budget>"; dated reads '
               'add "window <since>..<until> · <coverage>"; then one record per [p1]/[c1]/[e1] label, each ending with '
               'the arguments of the next command (url, author, replies <handle>); text is shown as text[N of M chars '
               'shown, complete|truncated]; then coverage: lines; detail: <command> when --chars cut a comment (it '
               're-reads the same page with --chars 0); last, more: <command> when reading can continue.')
JSON_OUTPUT = ('--json: one JSON envelope instead (ok, command, stop_reason, request_count, max_requests, coverage, '
               'next, error, message, fix, results, with full texts); schema result describes every field.')
OUT_OUTPUT = ('--out FILE: records go to an NDJSON file a whole page at a time and stdout gets one summary line (one '
              'JSON object with --json); rerun the same command with the same file to resume. --out cannot be '
              'combined with --after. The file holds other people\'s data: keep it outside the repository.')
FAILURE = ('failure: one JSON envelope (ok false, error, message, fix, and results read before the failure); text '
           'output instead marks a partial result with a coverage: incomplete line.')
DETAIL = 'Every detail path (post <url>, detail:, replies) is a new live request, not a replay of what was shown.'


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise FacebookError(2, message, f'Run {self.prog} --help.')


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
    if number > 400:
        raise argparse.ArgumentTypeError('at most 400 requests per invocation')
    return number


def day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError('expected a date as YYYY-MM-DD') from None


OPTIONS = {
    'limit': (('--limit',), {'type': positive, 'help': 'Records to show; omitted: until the source ends or the request budget is spent'}),
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
        'help': 'Read your home feed.',
        'run': listing.feed,
        'arguments': [(('--sort',), {'choices': ['top', 'recent'], 'default': 'top', 'help': 'top: the order Facebook ranks; recent: newest first'}),
                      'since', 'until',
                      (('--include-sponsored',), {'action': 'store_true', 'help': 'Keep advertisements; by default they are left out and counted'})] + list(LIST),
        'epilog': ['The feed is what Facebook chose to show this account, not everything its friends and pages posted.',
                   'With --since, only --sort recent can close the window (it stops at the first page older than --since); a ranked feed is a sample of the window.',
                   'requests: 1 per page of about 5-10 posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'profile': {
        'help': 'Read a profile\'s or page\'s timeline.',
        'run': listing.profile,
        'arguments': [(('target',), {'help': 'Profile or page URL, vanity name or numeric id'}), 'since', 'until'] + list(LIST),
        'epilog': ['--since/--until are applied by Facebook (server-filtered); reaching the end closes the window.',
                   'A timeline can hold posts by other people (posts on the timeline, shares); each record names its author.',
                   'requests: 1 to find the numeric id (none for a numeric id), then 1 per page of about 3-5 posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'group': {
        'help': 'Read a group\'s posts.',
        'run': listing.group,
        'arguments': [(('target',), {'help': 'Group URL, vanity name or numeric id'}),
                      (('--sort',), {'choices': ['top', 'recent', 'activity'], 'default': 'top', 'help': 'top and activity are ranked; recent: newest posts first'}),
                      'since', 'until'] + list(LIST),
        'epilog': ['With --since, only --sort recent can close the window; top and activity are samples of it.',
                   'requests: 1 to find the numeric id (none for a numeric id), then 1 per page of about 3-5 posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'post': {
        'help': 'Read one post in full with its first parent comments.',
        'run': thread.post,
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'Facebook post permalink (posts/, permalink.php, story.php, photo, videos/, groups/…/posts/)'}),
                      (('--sort',), {'choices': ['all', 'relevant', 'newest'], 'default': 'all', 'help': 'Comment order: all (ranked, nothing filtered out), relevant (Facebook\'s "most relevant", which can leave comments out), newest'}),
                      (('--limit',), {'type': positive, 'help': 'Parent comments to show from the first batch'}),
                      (('--chars',), {'type': chars, 'help': 'Characters of each comment to show (default 180; 0 = all); the post text is always shown in full'}),
                      'json', 'max_requests'],
        'epilog': ['The post text is shown in full. Each comment with replies ends with replies <handle>; more: continues the parent comments as a comments command.',
                   'requests: 3 (the page, to find the story; the post; the first comments).'],
        'exits': (0, 2, 3, 4, 5, 6, 8),
    },
    'comments': {
        'help': 'Read a post\'s parent comments, page by page.',
        'run': thread.comments,
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'Facebook post permalink'}),
                      (('--sort',), {'choices': ['all', 'relevant', 'newest'], 'default': 'all', 'help': 'all (ranked, nothing filtered out), relevant (can leave comments out), newest'}),
                      (('--limit',), {'type': positive, 'help': 'Parent comments to show; omitted: one page (about 10), or every page with --out. With --out it counts parents saved'})] + [o for o in LIST if o != 'limit'],
        'epilog': ['Replies are not expanded here: each comment with replies ends with replies <handle>, which reads that branch.',
                   'requests: 2 to find the post (none when continuing with --after), then 1 per page of about 10 comments.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'replies': {
        'help': 'Read one batch of replies under a comment, by the handle post or comments printed.',
        'run': thread.replies,
        'arguments': [(('target',), {'metavar': 'HANDLE', 'help': 'The number after "replies" on a comment or reply'}),
                      (('--limit',), {'type': positive, 'help': 'Replies to show; omitted: one batch (about 10), or every batch with --out. With --out it counts replies saved'}),
                      'chars', 'out', 'json', 'max_requests'],
        'epilog': ['A handle names a batch: the first batch of a comment\'s replies, or the batch after one already shown (more: prints that one). It is not used up: running it again reads the same batch again, live.',
                   'Each reply that has replies of its own ends with replies <handle>, which reads that deeper branch. Facebook\'s reply count includes those deeper replies.',
                   'requests: 1 per batch of about 10 replies.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'search': {
        'help': 'Search posts, people, pages or groups.',
        'run': search.search,
        'arguments': [(('target',), {'metavar': 'TEXT', 'help': 'What to search for'}),
                      (('--type',), {'choices': ['top', 'posts', 'people', 'pages', 'groups'], 'default': 'top', 'help': 'top mixes posts with people, pages and groups in Facebook\'s order'}),
                      (('--recent',), {'action': 'store_true', 'help': 'Posts only (top, posts): Facebook\'s "recent posts" filter'}),
                      'since', 'until',
                      (('--in-group',), {'metavar': 'GROUP', 'help': 'Search the posts of one group (its URL, vanity name or numeric id), as the group\'s own search box does'})] + list(LIST),
        'epilog': ['Results are in Facebook\'s order for this account; people and pages with the same name are different results (compare url and verified).',
                   '--recent, --since and --until are Facebook\'s post filters (top and posts only): Facebook applies the dates, so reaching the end closes the window as far as search returns posts; results stay in Facebook\'s order, not by date.',
                   '--in-group searches one group\'s posts (top or posts): requests: 1 to find the group id (none for a numeric id), then 1 per page.',
                   'requests: 1 per page of about 5 results.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'about': {
        'help': 'Read a profile\'s or page\'s visible About fields, or a group\'s card.',
        'run': about.about,
        'arguments': [(('target',), {'help': 'Profile or page URL, vanity name or numeric id; or a group by its /groups/ URL'}),
                      (('--section',), {'help': 'Only this locale-independent section, e.g. directory_work (schema about lists them as they appear)'}),
                      'json', 'max_requests'],
        'epilog': ['What About shows depends on the viewing account and the owner\'s privacy settings. Fields are never cut.',
                   'A group URL gives the group\'s card instead: name, privacy as Facebook labels and explains it, the member total as Facebook writes it, the viewing account\'s relation to the group, whether joining asks questions, the description, recent activity, creation date and the rules in order. requests: 1 to find the id (none for a numeric /groups/<id>/), then 2 (header and About).',
                   'requests: 1 to find the numeric id (none for a numeric id), 1 for the overview, then 1 per About tab; --section stops at the first tab that shows it.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'doctor': {
        'help': 'Check Aside, the browser tab, login and account protection; always JSON.',
        'run': maintenance.doctor,
        'arguments': [(('--unblock',), {'action': 'store_true', 'help': 'Clear a saved block, only after a person has checked Facebook in the Aside browser'})],
        'epilog': ['It opens the dedicated facebook.com tab if none is open (about 30 requests the page makes itself) and otherwise makes no request.',
                   'output: one JSON envelope; results[0] holds aside, tab {target_id, opened_now}, login, account_id (the Facebook account in use), blocked and block_reason, queries (which read queries are live in the tab), data_dir, protection_state and holds_personal_data. A saved block is reported as exit 5 without touching the browser.',
                   '--unblock clears a saved checkpoint or rate limit first; it means nothing unless a person has looked at Facebook in the Aside browser and confirmed the account is fine.'],
        'exits': (0, 2, 3, 4, 5),
    },
    'schema': {
        'help': 'Describe results, files and record fields; always JSON, no request.',
        'run': maintenance.schema,
        'arguments': [(('object',), {'nargs': '?', 'choices': maintenance.SCHEMA_OBJECTS, 'help': 'What to describe; omitted: the list of objects'})],
        'epilog': ['output: one JSON envelope; results holds the requested description (result: the envelope, stop reasons, exit codes, window coverage, request counting and the text page; out: the --out file; post, comment, entity, about: record fields), or one line per object.'],
        'exits': (0, 2),
    },
}
READS = ('feed', 'profile', 'group', 'post', 'comments', 'replies', 'search', 'about')


def epilog(name, spec):
    lines = list(spec['epilog'])
    if name in READS:
        lines += [REQUESTS, TEXT_OUTPUT if name != 'about' else TEXT_OUTPUT.replace('[p1]/[c1]/[e1] label', 'section'),
                  JSON_OUTPUT]
        if 'out' in [a for a in spec['arguments'] if isinstance(a, str)]:
            lines.append(OUT_OUTPUT)
        lines += [FAILURE, DETAIL]
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
    for key in ('target', 'section', 'out', 'in_group'):
        value = options.get(key)
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise FacebookError(2, f'The {key} contains a line break or another control character.', 'Pass it on one line.')
    if options.get('since') and options.get('until') and options['since'] > options['until']:
        raise FacebookError(2, '--since must not be later than --until.', 'Swap the two dates.')
    if options.get('after') and options.get('out'):
        raise FacebookError(2, '--after and --out cannot be combined; --out resumes its own file.',
                            'Rerun the same command with the same --out path.')
    if options['command'] == 'replies' and not (options['target'].isascii() and options['target'].isdigit()):
        raise FacebookError(2, 'A replies handle is the number printed after "replies".', 'Copy the whole replies line.')
    if options['command'] == 'search' and options['type'] not in ('top', 'posts') and (
            options.get('recent') or options.get('since') or options.get('until') or options.get('in_group')):
        raise FacebookError(2, '--recent, --since, --until and --in-group are for posts; use them with --type top or '
                               'posts.', 'Drop the option, or search --type posts.')
    if options['command'] == 'search' and not options['target'].strip():
        raise FacebookError(2, 'Search text must not be empty.', 'Pass the words to search for.')


def invocation():
    """This file as it was invoked, double-quoted the way the skill's allowed-tools spells it."""
    return 'uv run "' + re.sub(r'([\\"$`])', r'\\\1', os.path.abspath(__file__)) + '"'


def command_line(words):
    return invocation() + ' ' + shlex.join(words)


def emit(kind, envelope, options):
    for key in ('next', 'detail'):
        if isinstance(envelope.get(key), list):
            envelope[key] = command_line(envelope[key])
    machine = options.get('json') or options['command'] in ('doctor', 'schema')
    if machine:
        envelope.pop('detail', None)  # JSON carries full texts; detail: only re-reads a page text output cut
    if options.get('out') and envelope.get('out') is not None and (envelope['ok'] or envelope.get('count')):
        print(json.dumps({k: v for k, v in envelope.items() if k != 'results'}, ensure_ascii=False) if machine
              else render_summary(envelope))
    elif machine or (not envelope['ok'] and not envelope.get('results')):
        print(json.dumps(envelope, ensure_ascii=False))
    else:
        print(render_page(envelope, chars=options.get('chars'), command=options['command']))
    return KIND_EXIT[kind]


def main(argv=None):
    options = {'command': None}
    try:
        options = vars(parser().parse_args(argv))
        validate(options)
        if options['command'] == 'schema':
            options['exit_codes'] = [(code, meaning, [k for k, c in KIND_EXIT.items() if c == code])
                                     for code, meaning in EXIT_CODES.items()]
        kind, envelope = COMMANDS[options['command']]['run'](options)
    except FacebookError as error:
        kind, envelope = failure_envelope(error, options.get('command'))
    return emit(kind, envelope, options)


if __name__ == '__main__':
    sys.exit(main())
