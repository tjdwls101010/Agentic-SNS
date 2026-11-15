#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read social networks through the logged-in Aside browser: X, Threads, Reddit, Facebook, Naver Blog. Read-only."""
import argparse
import importlib
import importlib.util
import json
import sys
from datetime import date, datetime, time, timedelta

from sns.clock import Deadline
from sns.errors import SnsError
from sns.maintenance import objects, schema
from sns.reading import Invocation, adopt_all, doctor, foreign, idle
from sns.render import page, summary
from sns.results import failure_envelope

PLATFORM_PACKAGES = ('x', 'threads', 'reddit', 'facebook', 'naver_blog')

# The one table from a result's kind to its exit code (units raise kinds, never numbers).
EXIT_CODES = {
    0: 'success: records; a stop that more: (or the same --out command) resumes; an --out file already final; '
       'doctor or schema',
    2: 'invalid arguments, or a handle or --out file of another command, an earlier version or expired, or a URL of '
       'another platform (fix names the command that reads it)',
    3: 'Aside or the browser tab is unavailable, timed out or answered invalidly',
    4: 'login is required in the Aside browser, or the platform account changed',
    5: 'blocked: a checkpoint, challenge, lock or network block a person must clear, an account-wide rate limit before '
       'any record (it passes at the time given), or unreadable protection state',
    6: 'a request failed before any record was read (a changed answer, or the time limit)',
    7: 'the platform explicitly returned nothing, or nothing fell inside the window',
    8: 'partial: records were read and then a request failed, or a stop could not save where to continue',
    9: 'the target cannot be read by this account: deleted, private, suspended or never existed',
    10: 'a named limit (an X operation, a Reddit bucket) ran out before any record: not an account problem, other '
        'commands still work, the message gives the time',
}
# The same table in a word or two, for the top-level map; each command's --help gives the full meaning.
EXIT_SUMMARY = {0: 'success, or a stop more: resumes', 2: 'bad arguments, handle, --out file or platform',
                3: 'Aside or the browser tab failed', 4: 'login needed, or the account changed',
                5: 'blocked (a person must clear it), or rate-limited before any record',
                6: 'a request failed before any record', 7: 'explicitly nothing', 8: 'partial',
                9: 'not readable by this account', 10: 'a named limit ran out before any record'}
KIND_EXIT = {'records': 0, 'resumable': 0, 'complete': 0, 'maintenance': 0, 'argument': 2, 'aside': 3, 'login': 4,
             'blocked': 5, 'failed': 6, 'empty': 7, 'partial': 8, 'unavailable': 9, 'scope_limit': 10}

TEXT_OUTPUT = ('output: a first line "<platform> <command> · … · N shown · stopped=<reason> · requests=<n>" (plus the '
               'cost of opening a tab, and a limit that stopped it or runs low); dated reads add "window '
               '<since>..<until> <zone> · <coverage>"; then one block per record, each ending with the arguments of '
               'the next command; then coverage: lines; last, more: <command> when reading can continue. Text is '
               'shown as text[N of M chars shown].')
JSON_OUTPUT = '--json: one JSON envelope instead, with full texts; <platform> schema result describes every field.'
OUT_OUTPUT = ('--out FILE: records go to an NDJSON file a whole page at a time (so it can hold a little more than '
              '--limit) and stdout gets one summary line; rerun the same command with the same file to resume. Its '
              'directory must exist, and it cannot be inside the skill\'s state directory. The file holds other people\'s '
              'posts: keep it outside the repository.')
FAILURE = ('failure: one JSON envelope (ok false, error, message, fix) when nothing was read; records read before a '
           'failure print as usual, followed by "coverage: incomplete — <message> fix: <fix>".')
REQUESTS = ('requests: there is no request budget; a command ends at its natural end, at --limit, at a platform\'s '
            'limit or block, or at its time limit (about 100 seconds, so it finishes inside two minutes), and more: '
            'continues. Every invocation of an account shares one lock and the platform\'s pacing.')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SnsError('argument', message, f'Run {self.prog} --help.')


def positive(value):
    if value.isascii() and value.isdigit() and int(value) > 0:
        return int(value)
    raise argparse.ArgumentTypeError('expected a positive integer')


def chars(value):
    if value.isascii() and value.isdigit():
        return int(value)
    raise argparse.ArgumentTypeError('expected 0 (full text) or a positive integer')


def day(value):
    try:
        found = date.fromisoformat(value)
        for edge in (found, found + timedelta(days=1)):  # a window's bounds are midnights, the day after included
            datetime.combine(edge, time()).astimezone().timestamp()
        return found.isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError('expected a date as YYYY-MM-DD') from None
    except (OverflowError, OSError):
        raise argparse.ArgumentTypeError('expected a date this computer can turn into a time') from None


def _zone(platform):
    return 'Korea time (KST)' if getattr(platform.window, 'tz', None) is not None else 'this computer\'s time zone'


def option(name, platform):
    """A shared option: (flags, settings)."""
    return {
        'limit': (('--limit',), {'type': positive, 'help': 'How many to show (with --out: to save); what one counts '
                                                           'and the default are in the description below'}),
        'since': (('--since',), {'type': day, 'metavar': 'DAY', 'help': f'First day to include, YYYY-MM-DD, in '
                                                                        f'{_zone(platform)}'}),
        'until': (('--until',), {'type': day, 'metavar': 'DAY', 'help': f'Last day to include, YYYY-MM-DD, in '
                                                                        f'{_zone(platform)}'}),
        'chars': (('--chars',), {'type': chars, 'help': 'Characters of each text to show (default 180; 0 = all '
                                                         'received); --json and --out keep all'}),
        'after': (('--after',), {'type': positive, 'metavar': 'HANDLE', 'help': 'Continue from the numbered handle a '
                                                                                'more: or replies line printed'}),
        'out': (('--out',), {'metavar': 'FILE', 'help': 'Collect into this NDJSON file one committed page at a time; '
                                                        'rerun the same command to resume; cannot be combined with '
                                                        '--after'}),
        'json': (('--json',), {'action': 'store_true', 'help': 'Print one JSON envelope instead of text'}),
    }[name]


def shared_commands(platform):
    """doctor and schema, which every platform has."""
    return {
        'doctor': {
            'help': f'Check Aside, the browser, {platform.title} login and account protection; always JSON.',
            'run': lambda invocation: doctor(platform, invocation),
            'arguments': [(('--unblock',), {'action': 'store_true',
                                            'help': f'Only after a person has checked {platform.site} in the Aside '
                                                    'browser and cleared what it showed: make one check and lift a '
                                                    'saved block if the answer is normal'})],
            'epilog': [f'output: one JSON envelope; results[0] holds aside, aside_version, aside_account, login, '
                       f'viewer (the {platform.title} account in use), blocked, block_reason, hold_until, limits, '
                       'requests_last_hour and requests_last_day (every command of this account), idle_seconds, '
                       'data_dir (the state every install of the skill on this computer shares), imported_from (an old '
                       'install\'s data/ taken in), protection_state, holds_personal_data and the platform\'s own '
                       'checks. A saved block is reported as exit 5 without touching the browser.',
                       '--unblock keeps the block while it checks with one request; only an answer for the account '
                       'the block was recorded for lifts it, and anything else leaves it (exit 5 with '
                       'verification_reason). '
                       + ('When the dedicated tab is gone, opening it is the check (the site loads as when a person '
                          'opens it, and its first look is judged) and nothing more is sent. '
                          if platform.transport == 'tab' else '')
                       + 'A rate limit (a hold, or a limit on one operation or bucket) is never '
                       'lifted by it: it passes at its time. It means nothing unless a person has looked at the site '
                       'in the Aside browser first. SNS_ASIDE_ACCOUNT (or SNS_ASIDE_ACCOUNT_<PLATFORM>) picks the '
                       'Aside account; SNS_IDLE_SECONDS sets when an unused dedicated tab is emptied (default 300, '
                       'off to keep it).'],
            'exits': (0, 2, 3, 4, 5, 6, 10),
        },
        'schema': {
            'help': 'Describe results, --out files and record fields; always JSON, no request.',
            'run': lambda invocation: schema(platform, invocation),
            'arguments': [(('object',), {'nargs': '?', 'choices': objects(platform),
                                         'help': 'What to describe; omitted: the list of objects'})],
            'epilog': ['output: one JSON envelope; results holds the requested description (result: the envelope, '
                       'stop reasons, kinds, exit codes and window coverage; out: the --out file; the others: record '
                       'fields), or one line per object.'],
            'exits': (0, 2),
        },
    }


def epilog(spec):
    lines = list(spec.get('epilog') or [])
    names = [a for a in spec['arguments'] if isinstance(a, str)]
    if spec.get('reads', True) and 'json' in names:
        lines += [REQUESTS, TEXT_OUTPUT, JSON_OUTPUT]
        if 'out' in names:
            lines.append(OUT_OUTPUT)
        lines.append(FAILURE)
    lines.append('exit codes:\n' + '\n'.join(f'  {code}  {EXIT_CODES[code]}' for code in spec['exits']))
    return '\n\n'.join(lines)


def _x_surface(platform):
    PLATFORM = platform.PLATFORM
    FEED_CHOICES = ['foryou', 'following']
    PROFILE_TABS = ['posts', 'replies', 'media', 'highlights', 'articles', 'lists', 'memberships']
    GRAPH_RELATIONS = ['following', 'followers', 'verified', 'known', 'similar']
    ME_COLLECTIONS = ['bookmarks', 'likes', 'notifications', 'mentions']
    LIST_TABS = ['posts', 'members', 'about']
    COMMUNITY_TABS = ['posts', 'media', 'about']
    COMMUNITY_SORTS = ['top', 'recent']
    REPLY_SORTS = ['top', 'recent']
    SEARCH_TYPES = ['posts', 'accounts', 'media']
    SEARCH_SORTS = ['top', 'latest']
    TREND_TABS = list(platform.explore_TABS)

    CHOICES = {
        'feed.tab': FEED_CHOICES, 'profile.tab': PROFILE_TABS, 'graph.relation': GRAPH_RELATIONS,
        'me.collection': ME_COLLECTIONS, 'list.tab': LIST_TABS, 'community.tab': COMMUNITY_TABS,
        'community.sort': COMMUNITY_SORTS, 'post.sort': REPLY_SORTS, 'search.type': SEARCH_TYPES,
        'search.sort': SEARCH_SORTS, 'search.within': ['communities'], 'quotes.sort': REPLY_SORTS,
        'trends.tab': TREND_TABS,
    }


    LIST = ['limit', 'chars', 'after', 'out', 'json']
    TARGET_ACCOUNT = 'X @handle or profile URL'


    def check_replies(options):
        if not (options['target'].isascii() and options['target'].isdigit()):
            raise SnsError('argument', 'A replies handle is the number printed after "replies" or in a more: line.',
                           'Copy the whole replies or more: line.')


    def check_post(options):
        if len(options['target']) > 1 and (options.get('limit') or options['sort'] != 'top'):
            raise SnsError('argument', 'Several posts are read without replies, so --limit and --sort do not apply.',
                           'Drop them, or read one post.')


    def check_community(options):
        if not options.get('target') and (options.get('tab') or options.get('sort')):
            raise SnsError('argument', 'Without a community, community lists the ones X suggests: --tab and --sort need a '
                                       'target.', 'Pass a community URL or id, or drop --tab and --sort.')
        if options.get('target') and options.get('sort') and options.get('tab') in ('media', 'about'):
            raise SnsError('argument', '--sort orders a community\'s posts only.', 'Drop --sort, or use --tab posts.')
        if options.get('out') and options.get('tab') == 'about':
            raise SnsError('argument', 'about is one card, not a collection.', 'Drop --out.')


    def check_list(options):
        if options.get('out') and options.get('tab') == 'about':
            raise SnsError('argument', 'about is one card, not a collection.', 'Drop --out.')


    def check_search(options):
        if not options['target'].strip():
            raise SnsError('argument', 'Search text must not be empty.', 'Pass the words to search for.')
        if options.get('within') and (options['type'] != 'posts' or options['sort'] != 'top'):
            raise SnsError('argument', 'search --in communities reads posts only, in X\'s order.', 'Drop --type and --sort.')


    def _positive(value):
        """--limit of the commands whose help says what their limit counts (the shared help speaks of --out)."""
        if value.isascii() and value.isdigit() and int(value) > 0:
            return int(value)
        raise argparse.ArgumentTypeError('expected a positive integer')


    def _chars(value):
        """--chars of the commands without --out (the shared help names --out)."""
        if value.isascii() and value.isdigit():
            return int(value)
        raise argparse.ArgumentTypeError('expected 0 (full text) or a positive integer')


    def _run(function):
        return lambda invocation: function(PLATFORM, invocation)


    COMMANDS = {
        'feed': {
            'help': 'Read your home feed, a page at a time.',
            'run': _run(platform.listing_feed),
            'arguments': [(('--tab',), {'choices': FEED_CHOICES, 'default': 'foryou',
                                         'help': 'foryou: the posts X ranks for this account; following: from the accounts it follows'}),
                          'since', 'until', *LIST],
            'epilog': ['foryou is what X chose to show this account, not everything; following holds only the accounts it follows, and X does not serve it newest first either, so neither feed can close a --since window: a window keeps the posts dated inside it among those read (a sample, not the whole day). Neither feed ends by itself, so --out needs --limit.',
                       'A repost row is the reposter\'s act, dated when it was reposted; the words are the original\'s, shown under it with their own author. Promoted posts (ads) are left out and counted.',
                       'Without --limit or --out it reads one page, with a window too (the posts dated inside it among that page); more: continues.',
                       'requests: 1 per page of about 20 posts.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'profile': {
            'help': 'Read a profile\'s tab: posts (with reposts), replies, media, highlights, articles, lists or memberships.',
            'run': _run(platform.listing_profile),
            'arguments': [(('target',), {'help': f'{TARGET_ACCOUNT}; a tab URL such as /<handle>/with_replies reads that tab'}),
                          (('--tab',), {'choices': PROFILE_TABS, 'help': 'The tab (default: the URL\'s tab, else posts)'}),
                          'since', 'until', *LIST],
            'epilog': ['posts holds the account\'s posts and reposts, newest first (X\'s own Posts tab now hides reposts); a repost row is dated when it was reposted. posts and replies are newest first, so a --since window closes at the first page wholly older than it (a pinned post sits first whatever its date and does not close it). media (photos, videos and GIFs), highlights and articles are not served in date order: a window covers them only when read to the end.',
                       'lists are the lists the account made or follows, memberships the lists others put it in; both hold lists (list <url> reads one) and take no window.',
                       'A protected account this account does not follow is unavailable (exit 9), which is not the same as empty.',
                       'Without --limit or --out it reads one page; a --since/--until window on posts or replies reads on until it closes, on the other tabs it only filters the page read; more: continues.',
                       'requests: 1 to find the account, then 1 per page of about 20 posts (the lists tab: about 100 lists).'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'about': {
            'help': 'Read an account\'s card, several accounts\' cards in one request, or a space\'s card.',
            'run': _run(platform.about_about),
            'arguments': [(('target',), {'nargs': '+', 'help': 'X @handle or profile URL, several read together; or one x.com/i/spaces/<id> link'}),
                          'json'],
            'epilog': ['A card: name, bio, links, location, join date, counts (followers, following, posts), whether it is protected, its relation to you, and its marks: a paid check is an X subscription, not an identity check; a Business or Government badge is granted by X to an organisation; a declared Parody, Commentary or Fan label is the account\'s own. Several handles: those X did not return are named (unresolved).',
                       'A space link reads the space: title, live/scheduled/ended, host and speakers, listener counts and whether a replay is kept. A space X no longer keeps is unavailable (exit 9).',
                       'requests: 1.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 9, 10),
        },
        'graph': {
            'help': 'Read the accounts a profile follows or that follow it, or the accounts X recommends as similar.',
            'run': _run(platform.listing_graph),
            'arguments': [(('target',), {'help': TARGET_ACCOUNT}),
                          (('relation',), {'choices': GRAPH_RELATIONS, 'help': 'following, followers, verified (followers with a paid check), known (its followers you follow) or similar (X\'s recommendation)'}),
                          *LIST],
            'epilog': ['A follow records what an account did, not friendship or agreement; similar is X\'s recommendation of accounts like this one, not a relationship of any kind. Counts on the card (about) are what X reports; the list is what X serves, page by page, and it can stop early: three pages in a row with no new account end the read (stopped=query_failure with that reason).',
                       'Without --limit or --out it reads one page; more: continues.',
                       'requests: 1 to find the account, then 1 per page of about 20 accounts.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'me': {
            'help': 'Read your own bookmarks, likes, notifications or mentions.',
            'run': _run(platform.listing_me),
            'arguments': [(('collection',), {'choices': ME_COLLECTIONS, 'help': 'bookmarks, likes (nobody else\'s likes are public on X), notifications or mentions'}),
                          *LIST],
            'epilog': ['In X\'s order (most recently saved or liked first, as X serves it); each post keeps its own date, not when you saved or liked it. There is no date window: X does not serve these in date order.',
                       'notifications are X\'s notification tab as records (what happened, when, which accounts and posts); "suggested by X" marks X recommending something, which is not anyone\'s act. mentions are the posts that mention you. The skill only sends the read and never opens X\'s notifications screen, which marks them as read; the unread count X shows stayed the same for two minutes after a read when this was measured, though X\'s own refresh of that count was not observed. A notification\'s message names other people.',
                       'Without --limit or --out it reads one page; more: continues.',
                       'requests: 1 per page of about 20 posts.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'list': {
            'help': 'Read an X list: its posts, its members or its card.',
            'run': _run(platform.listing_lists),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'x.com/i/lists/<id> URL or the numeric list id'}),
                          (('--tab',), {'choices': LIST_TABS, 'default': 'posts', 'help': 'posts (from its members), members, or about (the card)'}),
                          *LIST],
            'epilog': ['A list is a set of accounts someone curated; its posts are its members\' posts in X\'s order, so they are not the members\' whole output and no window closes on them. about is one record: name, owner, members, followers, private or public.',
                       'about: a private list of someone else, or a deleted one, is unavailable (exit 9).',
                       'Without --limit or --out posts and members read one page; more: continues.',
                       'requests: 1 per page of about 20; about: 1.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            'check': check_list,
        },
        'community': {
            'help': 'Read a community\'s posts, media or card, or without a target the communities X suggests.',
            'run': _run(platform.listing_community),
            'arguments': [(('target',), {'nargs': '?', 'metavar': 'URL', 'help': 'x.com/i/communities/<id> URL or the numeric id; omitted: the communities X suggests to this account'}),
                          (('--tab',), {'choices': COMMUNITY_TABS, 'help': 'posts (default), media, or about (the card); with a target only'}),
                          (('--sort',), {'choices': COMMUNITY_SORTS, 'help': 'posts: top (default, X\'s ranking) or recent'}),
                          *LIST],
            'epilog': ['A community is a group with its own feed: its posts are what members posted there, in X\'s order (top is a ranking; recent was not verified as newest first), so no window closes on them. about is one record: size, moderators, how one joins, topic, rules, who made it and your role. search --in communities searches posts across communities.',
                       'A suggested community is X\'s recommendation for this account, not a ranking of all communities.',
                       'Without --limit or --out it reads one page; more: continues.',
                       'requests: 1 per page of about 20; about: 1.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            'check': check_community,
        },
        'post': {
            'help': 'Read one post in full with its parent chain and first batch of replies, or several posts by id.',
            'run': _run(platform.thread_post),
            'arguments': [(('target',), {'nargs': '+', 'metavar': 'URL', 'help': 'x.com post URL or numeric id; several: those posts only, without replies'}),
                          (('--sort',), {'choices': REPLY_SORTS, 'default': 'top', 'help': 'Reply order: top (X\'s ranking) or recent (newest first)'}),
                          (('--limit',), {'type': _positive, 'help': 'Reply threads to show from the first batch (each reply with what hangs under it)'}),
                          (('--chars',), {'type': _chars, 'help': 'Characters of each parent and reply to show (default 180; 0 = all); the post itself is always shown in full; --json keeps all'}),
                          'json'],
            'epilog': ['The post is shown in full (a long post\'s whole text, an article\'s whole body), after the posts it answers (parent). Its first batch of replies follows, each conversation thread as X shows it: a reply\'s depth is its place in the thread, and "reply to a post not shown" marks where X skipped posts. A reply with more under it ends with replies <handle>, which reads that branch from the reply\'s own page; more: reads the next batch of direct replies; a coverage line names the handle for the replies X hid as probable spam or low quality.',
                       'top is X\'s ranking, which by X\'s own description puts paid subscribers\' replies higher; recent is newest first and does not include the replies X hid.',
                       'A community note under a post is context other users added and rated helpful, not the author\'s words. An edited post lists its versions; post <id> opens any of them.',
                       'Several ids: one request for those posts in full, without replies; ids X did not return are named (unresolved).',
                       'requests: 1 (the post, its parents and the first replies in one read).'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            'check': check_post,
        },
        'replies': {
            'help': 'Read the next batch of a post\'s replies, the replies X hid, or the replies under one reply, by handle.',
            'run': _run(platform.thread_replies),
            'arguments': [(('target',), {'metavar': 'HANDLE', 'help': 'The number after "replies" or in a more: line'}),
                          (('--limit',), {'type': _positive, 'help': 'Replies to show; omitted: one batch, or every batch with --out. With --out it counts replies saved'}),
                          'chars', 'out', 'json'],
            'epilog': ['A handle names a batch: the next batch of a post\'s direct replies, the replies X hid, or every reply one reply\'s own page lists (batch by batch). Running it again reads the same batch again, live; it is not a replay. more: prints the handle of the batch after.',
                       'requests: 1 per batch of about 30-40 replies.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            'check': check_replies,
        },
        'reposts': {
            'help': 'Read the accounts that reposted one post.',
            'run': _run(platform.listing_reposts),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'x.com post URL or numeric id'}), *LIST],
            'epilog': ['A repost is an account sharing the post as it is, which records the act, not agreement; quotes (the posts that add words) are read with quotes. The list is what X serves, page by page; three pages in a row with no new account end the read.',
                       'Without --limit or --out it reads one page; more: continues.',
                       'requests: 1 per page of about 20 accounts.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'quotes': {
            'help': 'Read the posts that quote one post.',
            'run': _run(platform.search_quotes),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'x.com post URL or numeric id'}),
                          (('--sort',), {'choices': REPLY_SORTS, 'default': 'top', 'help': 'top (X\'s ranking) or recent'}),
                          *LIST],
            'epilog': ['Each quote is its own post with two voices: the quoter\'s words, and the quoted post shown under it with its own author. Asked the way X\'s own quotes screen asks (a search for the post\'s id and its media links), so it shares search\'s limit (about 50 per 15 minutes).',
                       'Without --limit or --out it reads one page; more: continues.',
                       'requests: 1 per page of about 20.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'search': {
            'help': 'Search posts, accounts or media, with X\'s search operators.',
            'run': _run(platform.search_search),
            'arguments': [(('target',), {'metavar': 'QUERY', 'help': 'What to search for, as typed into X: words, "phrases", OR, -exclusions and operators (from: to: since:YYYY-MM-DD until:YYYY-MM-DD min_faves: filter:links lang: …)'}),
                          (('--type',), {'choices': SEARCH_TYPES, 'default': 'posts', 'help': 'posts, accounts (people) or media'}),
                          (('--sort',), {'choices': SEARCH_SORTS, 'default': 'top', 'help': 'Posts and media: top (X\'s ranking) or latest (newest first)'}),
                          (('--in',), {'choices': ['communities'], 'dest': 'within', 'help': 'communities: search posts in communities only (X\'s community search; posts, in X\'s order)'}),
                          *LIST],
            'epilog': ['Results are in X\'s order for this account: top is a ranking, not a sample of opinion; latest is newest first. Accounts with the same or similar names are different results (compare url and their marks).',
                       'since: and until: in the query are filters X applies itself, so such a search read to the end (stopped=exhausted) covers its window: window ... closed (server-filtered); stopped by --limit, the time limit or X\'s limit it is still open. X decides which day boundaries those operators use (measured once: until:D ran to the end of D in this account\'s time zone), so check created_at at the edges.',
                       'X allows about 50 searches per 15 minutes for this account (quotes count too): a wide search costs that limit, and when it runs out the command stops with exit 10 (before any result) or stopped=rate_limited and a more: line (after some), naming when it resets.',
                       'Without --limit or --out it reads one page; more: continues.',
                       'requests: 1 per page of about 20.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
            'check': check_search,
        },
        'trends': {
            'help': 'Read the trends and events on one of X\'s Explore tabs.',
            'run': _run(platform.explore_trends),
            'arguments': [(('--tab',), {'choices': TREND_TABS, 'default': 'trending', 'help': 'trending (default), foryou, news, sports or entertainment'}),
                          (('--limit',), {'type': _positive, 'help': 'Trends and events to show; omitted: one page'}),
                          (('--chars',), {'type': _chars, 'help': 'Characters of each text to show (default 180; 0 = all received); --json keeps all'}),
                          'after', 'json'],
            'epilog': ['A trend is what X shows this account as popular now, in X\'s order and for X\'s region and language settings, not a measure of opinion or a full list; its count line is X\'s rounded figure. Each trend ends with search: <query>, the words search takes to read it; an event ends with its title as that query. Promoted trends (ads) and the posts or accounts X mixes into Explore are left out and counted.',
                       'requests: 1 for foryou (its first page comes with the Explore answer, and only that page is read); 2 for the other tabs (the Explore answer names their timeline), then 1 per further page.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'images': {
            'help': 'Save the pictures of one post (a video by its poster) so they can be looked at.',
            'run': _run(platform.images_images),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'x.com post URL or numeric id'}),
                          (('numbers',), {'nargs': '*', 'type': _positive, 'metavar': 'N',
                                          'help': 'The pictures to save, by the numbers the post shows ([image N])'}),
                          (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
            'epilog': ['The post is read again (its picture links do not last), so N is the Nth picture as X sends the post '
                       'now; each saved line names its kind, size, alt text and media_id to match what the post showed. A '
                       'video is saved as its poster image, not the video. Files go to images/ in the skill\'s state directory and are '
                       'removed a day later; they are other people\'s pictures. A picture that could not be saved is named '
                       'in coverage (exit 8); a number the post does not have is refused before any picture is fetched (exit 2). A stop between pictures (the time limit, a hold) keeps the saved ones and ends with more: naming the numbers left.',
                       'requests: 1 for the post, then 1 per picture.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
    }


    # What every reading command's output holds beyond the shared description (the core's text names no X record kinds and
    # knows nothing of the dedicated tab).
    RECORDS = ('records: one block per record, labelled [p1] post, [r1] reply, [a1] account, [t1] trend or event, [l1] '
               'list, [c1] community, [s1] space, [n1] notification, each ending with the arguments of the next command '
               '(url: post <url> opens that one post; author; replies <handle>; search: <query>).')
    TAB = ('the dedicated tab: the skill reads from its own x.com tab. Opening it (or loading it again) costs about 15-25 '
           'requests the page makes itself while it loads, shown as "tab opened" and counted apart from the reads; requests '
           'the open tab made between commands are shown as unwatched=, not charged, but a block seen there stops the '
           'command before it sends anything; static files do not count. The tab is closed about 5 minutes after the '
           'last command.')
    for _name in ('feed', 'profile', 'about', 'graph', 'me', 'list', 'community', 'post', 'replies', 'reposts', 'quotes',
                  'search', 'trends'):
        COMMANDS[_name]['epilog'] = [*COMMANDS[_name]['epilog'], RECORDS, TAB]
    COMMANDS['images']['epilog'] = [*COMMANDS['images']['epilog'], TAB]

    return COMMANDS, CHOICES


def _threads_surface(platform):
    PLATFORM = platform.PLATFORM
    FEED_CHOICES = ['foryou', 'following']
    PROFILE_TABS = ['threads', 'replies', 'reposts', 'media']
    GRAPH_RELATIONS = ['followers', 'following']
    ME_COLLECTIONS = ['liked', 'saved', 'activity']
    ACTIVITY_FILTERS = list(platform.web_ACTIVITY_FILTERS)
    REPLY_SORTS = ['top', 'recent']
    SEARCH_TYPES = ['posts', 'tags', 'accounts']
    SEARCH_SORTS = ['top', 'recent']

    CHOICES = {
        'feed.tab': FEED_CHOICES, 'profile.tab': PROFILE_TABS, 'graph.relation': GRAPH_RELATIONS,
        'me.collection': ME_COLLECTIONS, 'me.tab': ACTIVITY_FILTERS,
        'search.type': SEARCH_TYPES, 'search.sort': SEARCH_SORTS,
        'post.sort': REPLY_SORTS,
    }


    LIST = ['limit', 'chars', 'after', 'out', 'json']


    def check_replies(options):
        if not (options['target'].isascii() and options['target'].isdigit()):
            raise SnsError('argument', 'A replies handle is the number printed after "replies" or in a more: line.',
                           'Copy the whole replies or more: line.')


    def check_search(options):
        if not options['target'].strip():
            raise SnsError('argument', 'Search text must not be empty.', 'Pass the words to search for.')
        if options['type'] == 'accounts' and any(options.get(k) for k in ('since', 'until', 'from')):
            raise SnsError('argument', '--since, --until and --from filter posts and tags, not accounts.',
                           'Drop them, or search posts.')
        if options['type'] == 'accounts' and options.get('sort') == 'recent':
            raise SnsError('argument', '--sort applies to posts and tags; account search is one batch in Threads\' order.',
                           'Drop --sort.')


    def _positive(value):
        """--limit of the commands whose help says what their limit counts (the shared help speaks of --out)."""
        if value.isascii() and value.isdigit() and int(value) > 0:
            return int(value)
        raise argparse.ArgumentTypeError('expected a positive integer')


    def _chars(value):
        """--chars of the commands without --out (the shared help names --out)."""
        if value.isascii() and value.isdigit():
            return int(value)
        raise argparse.ArgumentTypeError('expected 0 (full text) or a positive integer')


    def check_me(options):
        if options['collection'] == 'activity':
            if options.get('after') or options.get('out'):
                raise SnsError('argument', 'Activity has no continuation or file.', 'Drop --after/--out.')
            if options.get('limit') is not None and not 1 <= options['limit'] <= 50:
                raise SnsError('argument', 'Activity limit is 1 to 50.', 'Choose a limit from 1 to 50.')
        elif options.get('limit') is not None and options['limit'] < 1:
            raise SnsError('argument', '--limit must be positive.', 'Choose a positive integer.')
        elif options.get('tab') is not None:
            raise SnsError('argument', '--tab selects an activity filter.', 'Use me activity or drop --tab.')


    def _activity_limit(value):
        try:
            return int(value)
        except ValueError:
            raise argparse.ArgumentTypeError('expected an integer') from None


    def _run(function):
        return lambda invocation: function(PLATFORM, invocation)


    COMMANDS = {
        'feed': {
            'help': 'Read your home feed, a page at a time.',
            'run': _run(platform.listing_feed),
            'arguments': [(('--tab',), {'choices': FEED_CHOICES, 'default': 'foryou',
                                         'help': 'foryou: the posts Threads ranks for this account; following: the accounts it follows, newest first'}),
                          'since', 'until', *LIST],
            'epilog': ['foryou is what Threads chose to show this account, not everything; following holds only the accounts it follows. Neither feed ends by itself, so --out needs --limit.',
                       'A window keeps the dated posts written on its days (posts without a date are left out and counted). Only --tab following can close a --since window (it stops at the first page wholly older than --since, while the feed stays newest first); foryou is a sample of the window: it keeps the posts dated inside it among the page read.',
                       'A feed entry can carry several posts (a post and a reply to it, or an author continuing a post): they are shown together, and the later ones say reply-to= or continuation of.',
                       'Without --limit or --out it reads one page (following with a window reads on until it closes); more: continues.',
                       'requests: 1 per page of about 5-10 posts.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'profile': {
            'help': 'Read a profile\'s tab: threads, replies, reposts or media.',
            'run': _run(platform.listing_profile),
            'arguments': [(('target',), {'help': 'Threads @handle or profile URL; a tab URL such as /@name/replies reads that tab'}),
                          (('--tab',), {'choices': PROFILE_TABS, 'help': 'The tab (default: the URL\'s tab, else threads)'}),
                          'since', 'until', *LIST],
            'epilog': ['threads and replies are newest first, so a --since window closes at the first page wholly older than it (a pinned post sits first whatever its date and does not close it). reposts and media are in no date order: a window covers them only when read to the end (--limit or --out, or more:). A repost carries the original post\'s date, not when it was reposted.',
                       'A private profile this account does not follow is unavailable (exit 9), which is not the same as empty.',
                       'Without --limit or --out it reads one page (a window on threads or replies reads on until it closes); more: continues.',
                       'requests: 1 to find the profile, then 1 per page (about 10 posts on threads). The first read of the replies, reposts or media tab in a while also reads that tab\'s screen once to learn its query.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'about': {
            'help': 'Read a profile\'s card: name, bio, links, verification, privacy, follower count.',
            'run': _run(platform.about_about),
            'arguments': [(('target',), {'help': 'Threads @handle or profile URL'}), 'json'],
            'epilog': ['Threads publishes a follower count but no following or mutual count: those are shown as ? (unknown); graph following lists the accounts.',
                       'A verified badge and a bio are what the account claims about itself.',
                       'requests: 2 (find the profile, read its card).'],
            'exits': (0, 2, 3, 4, 5, 6, 8, 9),
        },
        'graph': {
            'help': 'Read the accounts that follow a profile, or that it follows.',
            'run': _run(platform.listing_graph),
            'arguments': [(('target',), {'help': 'Threads @handle or profile URL'}),
                          (('relation',), {'choices': GRAPH_RELATIONS, 'help': 'followers or following'}),
                          *LIST],
            'epilog': ['followers: Threads may send its own sample rather than the whole list (stopped=server_capped); the coverage line gives the count the profile reports. following pages on.',
                       'Without --limit or --out it reads one page; more: continues.',
                       'requests: 1 to find the profile, then 1 per page of about 20 accounts.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'me': {
            'help': 'Read the posts you liked or saved (one batch).',
            'run': lambda invocation: (platform.listing_notifications if invocation.options['collection'] == 'activity' else platform.listing_me)(PLATFORM, invocation),
            'check': check_me,
            'arguments': [(('collection',), {'choices': ME_COLLECTIONS, 'metavar': 'KIND', 'help': 'liked, saved or activity'}), (('--tab',), {'choices': ACTIVITY_FILTERS, 'help': 'App activity filter (default: all); requests means follow requests'}), (('--limit',), {'type': _activity_limit, 'help': 'Rows to show (activity: default 20, 1 to 50)'}), 'chars', 'after', 'out', 'json'],
            'epilog': ['One batch, as Threads sends it (stopped=not_paginable): not your whole history.',
                       'requests: 1.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'activity': {
            'help': 'Read your activity (notifications) list without marking it seen.',
            'run': _run(platform.listing_notifications),
            'arguments': [(('--tab',), {'choices': ACTIVITY_FILTERS, 'default': 'all',
                                           'help': 'App activity filter (default: all); requests means follow requests'}),
                          (('--limit',), {'type': _activity_limit, 'default': 20, 'metavar': 'N',
                                         'help': 'Rows to request in this page (default 20; 1 to 50)'}),
                          'json', (('--chars',), {'type': _chars, 'metavar': 'N',
                                                'help': 'Characters of each notification to show (default 180; 0 = all)'})],
            'epilog': ['Reads one page in Threads\' order. If Threads says older activity exists, stopped=server_capped '
                       'and the coverage line say only this page was read; no next page is requested.',
                       'Reading the list sends no seen change (the app marks notifications seen only when its activity '
                       'screen opens, which this skill never does); seen state as observed on 2026-10-22.',
                       'requests: 1.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'search': {
            'help': 'Search posts, tags or accounts.',
            'run': _run(platform.search_search),
            'arguments': [(('target',), {'metavar': 'TEXT', 'help': 'What to search for (a tag without #)'}),
                          (('--type',), {'choices': SEARCH_TYPES, 'default': 'posts',
                                         'help': 'posts (by words), tags (posts under a tag) or accounts (one batch of profiles)'}),
                          (('--sort',), {'choices': SEARCH_SORTS, 'default': 'top',
                                         'help': 'Posts and tags: top (Threads ranks them) or recent (newest first)'}),
                          'since', 'until',
                          (('--from',), {'metavar': 'ACCOUNT', 'help': 'Posts and tags: only posts by this @handle'}),
                          *LIST],
            'epilog': ['Results are in Threads\' order for this account: top is a ranking, not a sample of opinion; recent is newest first. Accounts with the same or similar names are different results (compare url and verified).',
                       '--since, --until and --from are filters Threads applies itself (posts and tags), so a filtered search read to the end (stopped=exhausted) covers its window in either order: window ... closed (server-filtered); stopped by --limit or the time limit, it is still open. The days are judged in the zone the window was made in and keep that span across more:.',
                       'Without --limit or --out it reads one page (a dated search reads on until Threads has no more; accounts are one batch); more: continues.',
                       'requests: 1 per page of about 10 posts; accounts 1.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
            'check': check_search,
        },
        'post': {
            'help': 'Read one post in full with its parent chain and first batch of replies.',
            'run': _run(platform.thread_post),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'Threads post URL (/@name/post/<code> or /t/<code>) or its shortcode'}),
                          (('--sort',), {'choices': REPLY_SORTS, 'default': 'top', 'help': 'Reply order: top (Threads ranks them) or recent (newest first)'}),
                          (('--limit',), {'type': _positive, 'help': 'Direct replies to show from the first batch (each with what hangs under it)'}),
                          (('--chars',), {'type': _chars, 'help': 'Characters of each parent and reply to show (default 180; 0 = all); the post itself is always shown in full'}),
                          'json'],
            'epilog': ['The post is shown in full, after the posts it answers (parent). Its first batch of direct replies follows, each with what hangs under it: replies to it (reply-to=) and the replier continuing (continuation of). A reply with more under it ends with replies <handle>, which opens that branch; more: reads the next batch of direct replies. A replies line says how many direct replies Threads reports, how many arrived and an estimate of those never received.',
                       'Every record\'s url opens that one post with post <url> (a reply is a post too).',
                       'requests: 3 (the post, its parents, its first replies); no screen is opened.'],
            'exits': (0, 2, 3, 4, 5, 6, 8, 9),
        },
        'replies': {
            'help': 'Read the next batch of a post\'s replies, or the replies under one reply, by the handle post printed.',
            'run': _run(platform.thread_replies),
            'arguments': [(('target',), {'metavar': 'HANDLE', 'help': 'The number after "replies" (a branch) or in a more: line (the next batch)'}),
                          (('--limit',), {'type': _positive, 'help': 'Replies to show; omitted: one batch, or every batch with --out. With --out it counts replies saved'}),
                          'chars', 'out', 'json'],
            'epilog': ['A handle names a batch: the next batch of a post\'s direct replies, or the replies under one reply (every reply that reply\'s own page lists, batch by batch, each with what hangs under it). Running it again reads the same batch again, live; it is not a replay. more: prints the handle of the batch after.',
                       'requests: 1 per batch of about 10 replies.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
            'check': check_replies,
        },
        'quotes': {
            'help': 'Read the posts that quote one post (one batch).',
            'run': _run(platform.listing_activity),
            'arguments': [(('target',), {'help': 'Post URL or shortcode'}), *LIST],
            'epilog': ['Each quote is its own post ([p] label, role quote), shown with its author and its text as the activity list gives it (--chars sets how much is shown); post <url> opens it with its media and replies. Threads sends one batch of up to about 100, in its own order: when it reports more (reported_total), the rest cannot be asked for (stopped=server_capped).',
                       'requests: 1.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'reposts': {
            'help': 'Read the accounts that reposted one post (one batch).',
            'run': _run(platform.listing_activity),
            'arguments': [(('target',), {'help': 'Post URL or shortcode'}), *LIST],
            'epilog': ['Each account ([a] label) with when it reposted. Threads sends one batch of up to about 100, in its own order: when it reports more (reported_total), the rest cannot be asked for (stopped=server_capped).',
                       'requests: 1.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'images': {
            'help': 'Save the pictures of one post (a video by its poster) so they can be looked at.',
            'run': _run(platform.images_images),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'threads.com (or threads.net) post URL'}),
                          (('numbers',), {'nargs': '*', 'type': _positive, 'metavar': 'N',
                                          'help': 'The pictures to save, by the numbers the post shows ([image N])'}),
                          (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
            'epilog': ['The post is read again (its picture links are signed and do not last), so N is the Nth picture as '
                       'Threads sends the post now; each saved line names its kind, size and media_id to match what the '
                       'post showed. A video is saved as its poster image. Files go to images/ in the skill\'s state directory and are '
                       'removed a day later; they are other people\'s pictures. A picture that could not be saved is named '
                       'in coverage (exit 8); a number the post does not have is refused before any picture is fetched (exit 2). A stop between pictures (the time limit, a hold) keeps the saved ones and ends with more: naming the numbers left.',
                       'requests: 3 for the post (as post reads it), then 1 per picture.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
    }


    # What every reading command's output holds beyond the shared description (the core's text names no Threads record
    # kinds and knows nothing of the dedicated tab).
    RECORDS = ('records: one block per record, labelled [p1] post, [r1] reply, [a1] account, [n1] notification, '
               'each ending with the arguments '
               'of the next command (url: post <url> opens that one post; author; replies <handle>).')
    TAB = ('the dedicated tab: the skill reads from its own threads.com tab. Opening it (or loading it again after it was '
           'emptied) costs about 34-40 requests the page makes itself, shown as "tab opened" and counted apart from the '
           'reads; learning a query Threads refused reads one document per try (at most 3 tries and one reload a command); '
           'requests the page itself sends while a read runs are counted with that read, so requests= can be a few more than the requests: line of a command says; requests the open tab made between commands are shown as unwatched=, not charged, but a block seen there stops '
           'the command before it sends anything; static files do not count. The tab is emptied (about:blank) about 5 '
           'minutes after the last command.')
    for _name in ('feed', 'profile', 'about', 'graph', 'me', 'activity', 'search', 'post', 'replies', 'quotes', 'reposts'):
        COMMANDS[_name]['epilog'] = [*COMMANDS[_name]['epilog'], RECORDS, TAB]
    COMMANDS['images']['epilog'] = [*COMMANDS['images']['epilog'], TAB]

    COMMANDS['me']['epilog'] = COMMANDS['activity']['epilog'] + COMMANDS['me']['epilog']
    del COMMANDS['activity']
    return COMMANDS, CHOICES


def _reddit_surface(platform):
    PLATFORM = platform.PLATFORM
    # --- the commands --------------------------------------------------------------------------------------------------

    LIST = ['limit', 'chars', 'after', 'out', 'json']
    WINDOW = ['since', 'until']
    TIME = (('--time',), {'choices': platform.web_TIMES, 'help': 'Reddit\'s own period for a ranking (top, controversial): hour, day, '
                                                        'week, month, year, all. Not a date window'})
    ACCOUNT = ('The account check (/api/me.json, 1 request) is made once by a command that can be continued (a more: or '
               '--out) before it reads; a more: that only shows what the last page already brought makes just that check.')
    WINDOWS = ('--since/--until (days on this computer, --until included) read a timeline, so they need sort new: without '
               '--sort the read is sort new and its first line says sort=new (window); another explicit --sort is refused '
               '(exit 2). The window closes at the first post more than ten minutes older than --since (Reddit\'s new '
               'order can be a minute off); if the listing ends first the result is partial (8) because the window was not '
               'covered, and a listing that returns nothing is empty (7).')
    PAGE = ('A page asks Reddit for 100 and shows 25 (--limit counts them; with --out, what is saved); more: shows the rest '
            'of the page, then reads the next.')


    def positive(value):
        if value.isascii() and value.isdigit() and int(value) > 0:
            return int(value)
        raise argparse.ArgumentTypeError('expected a positive integer')


    def count(value):
        if value.isascii() and value.isdigit():
            return int(value)
        raise argparse.ArgumentTypeError('expected 0 or a positive integer')


    def _command(function):
        return lambda invocation: function(PLATFORM, invocation)


    COMMANDS = {
        'feed': {
            'help': 'Read your home feed, a page at a time.',
            'run': _command(platform.listing_feed), 'check': platform.listing_window_check,
            'arguments': [(('--sort',), {'choices': platform.web_FEED_SORTS, 'help': 'best (default) and hot are Reddit\'s ranking '
                                                                            'for this account; new is newest first; top '
                                                                            'with --time'}), TIME, *WINDOW, *LIST],
            'epilog': ['The home feed is Reddit\'s choice for this account (its subscriptions and what it ranks), not Reddit '
                       'as a whole. best and hot never end by themselves: --out needs --limit there.', PAGE, WINDOWS,
                       ACCOUNT],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'sub': {
            'help': 'Read a community\'s listing (r/name, r/a+b, r/popular, r/all).',
            'run': _command(platform.listing_sub), 'check': platform.listing_window_check,
            'arguments': [(('target',), {'help': 'r/<name>, a community URL, or r/<a+b> for several at once (r/popular and '
                                                 'r/all are Reddit-wide)'}),
                          (('--sort',), {'choices': platform.web_SUB_SORTS, 'help': 'hot (default), new (newest first), top or '
                                                                           'controversial (with --time), rising'}),
                          TIME, *WINDOW, *LIST],
            'epilog': ['A community\'s listing is that community\'s own; r/popular and r/all are Reddit-wide rankings. '
                       'Pinned posts (moderators\' announcements, often old) sit at the top of hot; under new they sit at '
                       'their own date.', PAGE, WINDOWS,
                       'A private, quarantined or banned community is unavailable (exit 9), which is not the same as '
                       'empty (7).', ACCOUNT],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'profile': {
            'help': 'Read a redditor\'s public activity: posts and comments, newest first by default.',
            'run': _command(platform.listing_profile), 'check': platform.listing_window_check,
            'arguments': [(('target',), {'help': 'u/<name> or a profile URL'}),
                          (('--tab',), {'choices': platform.web_PROFILE_TYPES, 'help': 'overview (posts and comments together, '
                                                                               'default), posts or comments'}),
                          (('--sort',), {'choices': platform.web_PROFILE_SORTS, 'help': 'new (default), hot, top or controversial '
                                                                               '(with --time)'}),
                          TIME, *WINDOW, *LIST],
            'epilog': ['A public history is that account\'s observed activity on Reddit. An account can hide its history '
                       'from other accounts, or hide some communities from it: what is shown may leave things out.',
                       'An empty first page (no --after, --time, --since or --until) is checked against the account\'s '
                       'karma for that kind (one more request): with karma it is a history that is not visible — hidden '
                       'or deleted — (exit 9, reason history_not_visible), not an empty one; with no karma it is reported '
                       'as observed (exit 7). A filtered empty result is just empty (7).', PAGE, WINDOWS, ACCOUNT],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'about': {
            'help': 'Read a community\'s card and rules, or a user\'s card.',
            'run': _command(platform.about_about),
            'arguments': [(('target',), {'help': 'r/<name> or u/<name> (or their URLs); a bare word is refused'}),
                          'chars', 'json'],
            'epilog': ['A community: name, title, short description, sidebar, subscribers, active users, age, access type '
                       '(public, restricted, private) and NSFW, then its rules, its moderators and its pinned posts '
                       '(moderators\' announcements and megathreads, which can gather a topic the listing then shows '
                       'less of). A user: karma by kind, account age, profile description, and the moderator, admin and '
                       'verified markers. Karma, age and flair say what an account did on Reddit, not who the person is.',
                       'One live read tied to no handle or file, so the Reddit account is not checked first.',
                       'requests: 4 requests for a community (card, rules, moderators, the first page of hot for its pinned posts), '
                       '1 for a user.'],
            'exits': (0, 2, 3, 4, 5, 6, 9, 10),
        },
        'wiki': {
            'help': 'Read a community\'s wiki: one page in full, or its page list.',
            'run': _command(platform.wiki_wiki),
            'arguments': [(('target',), {'help': 'r/<name>, or a wiki URL (https://www.reddit.com/r/<name>/wiki/<page>)'}),
                          (('page',), {'nargs': '?', 'help': 'The page (default index; names such as faq or faq/start)'}),
                          (('--pages',), {'action': 'store_true', 'help': 'List the wiki\'s pages instead of reading one'}),
                          (('--chars',), {'type': count, 'help': 'Characters of the page to show (default: all)'}), 'json'],
            'epilog': ['A wiki page is what its community\'s moderators wrote and revised (when, by whom and why are on the '
                       'first record line): often a FAQ, rules in detail, or recommended resources. The page list keeps '
                       'settings pages (config/..., the sidebar and rules text) apart.',
                       'Wiki pages count in Reddit\'s own wiki bucket, not the one listings and threads use; the first '
                       'line shows its window as wiki. One live read tied to no handle or file, so the Reddit account is '
                       'not checked first.',
                       'A page that does not exist, or a wiki that is off or private, is unavailable (exit 9).',
                       'requests: 1 request.'],
            'exits': (0, 2, 3, 4, 5, 6, 9, 10),
        },
        'search': {
            'help': 'Search posts, communities or users, across Reddit or inside one community.',
            'run': _command(platform.search_search), 'check': platform.listing_window_check,
            'arguments': [(('text',), {'metavar': 'TEXT', 'help': 'What to search for, as one argument; sent to Reddit as '
                                                                  'it is'}),
                          (('--type',), {'choices': platform.web_SEARCH_TYPES, 'help': 'posts (default), subs (communities) or '
                                                                              'users'}),
                          (('--in',), {'dest': 'within', 'metavar': 'r/NAME', 'help': 'Search posts inside this one '
                                                                                       'community'}),
                          (('--sort',), {'choices': platform.web_SEARCH_SORTS, 'help': 'relevance (default), hot, top, new (newest '
                                                                              'first) or comments (most commented)'}),
                          TIME,
                          (('--nsfw',), {'action': 'store_true', 'help': 'Include posts marked over 18 (otherwise Reddit '
                                                                         'leaves most out)'}),
                          *WINDOW, *LIST],
            'epilog': ['Reddit matches words loosely: several words find posts with any of them, so results can be '
                       'off-topic. These operators work inside TEXT: "exact phrase", subreddit:NAME, author:NAME, '
                       'title:WORD, self:yes (text posts), site:DOMAIN, flair:NAME; url:TEXT matches loosely. Comments '
                       'cannot be searched here.',
                       'Results are Reddit\'s ranking for this query, not a sample of what Reddit holds; an empty search '
                       'shows nothing matched these words in Reddit\'s index, not that nobody discussed it.',
                       PAGE, '--time is Reddit\'s period (hour ... all). ' + WINDOWS, ACCOUNT],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'related': {
            'help': 'Read the other discussions of the same link (crossposts and duplicates).',
            'run': _command(platform.listing_related),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'A post URL or id (a comment link reads its post)'}),
                          *LIST],
            'epilog': ['Each other post of the same link, in other communities or the same one: one link\'s discussion is '
                       'often split across communities that react differently. Exit 7 when there is none.', PAGE, ACCOUNT],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'me': {
            'help': 'Read your own subscriptions, saved or upvoted items, or the replies and mentions others sent you.',
            'run': _command(platform.listing_me),
            'arguments': [(('collection',), {'choices': platform.web_ME_COLLECTIONS, 'help': 'subs (subscribed communities), saved, '
                                                                                    'upvoted, comment-replies (replies to '
                                                                                    'your comments), post-replies (replies '
                                                                                    'to your posts) or mentions (of your '
                                                                                    'name)'}), *LIST],
            'epilog': ['Lists of the Reddit account the Aside browser is logged in to (the account check names it). saved '
                       'and upvoted hold posts and comments, newest saved or upvoted first. comment-replies, post-replies and '
                       'mentions are what other accounts sent you, newest first; reading them never marks them read '
                       '(unread says which are still new). Private messages are not read.', PAGE, ACCOUNT],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'post': {
            'help': 'Read one post in full and the first batch of its comments.',
            'run': _command(platform.thread_post),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'A post URL, id or redd.it link; a comment link opens the '
                                                                   'post at that comment; a share link (/r/<sub>/s/...) '
                                                                   'is resolved first'}),
                          (('--sort',), {'choices': platform.web_COMMENT_SORTS, 'help': 'Comment order: best (default), top, new, '
                                                                               'controversial, old, qa'}),
                          (('--limit',), {'type': positive, 'help': 'Comments to show (default 25)'}),
                          (('--depth',), {'type': count, 'help': 'Reply levels to show (default 2; 0 = top-level comments '
                                                               'only)'}),
                          (('--context',), {'type': count, 'help': 'For a comment link: how many of its ancestors Reddit '
                                                                 'sends with it'}),
                          'chars', 'json'],
            'epilog': ['The post is shown in full. Reddit sends up to 500 of its comments, 10 levels deep, in one answer; '
                       'the rest are gaps. The comments shown are the first batch in depth-first order within --depth: '
                       'each [c] line names the comment it answers (reply-to=), and the thread: line counts what Reddit '
                       'reports (deleted and removed included), what arrived, what is shown, what is deeper than --depth '
                       'and what is left to expand. more: continues the same reading (comments --after); it is offered '
                       'only while a continuation can still show or fetch comments within --depth. The first line counts '
                       'the post and the context rows with the comments.',
                       'The sort is the order inside each batch, not across batches. A thread\'s suggested sort and '
                       'contest mode (random order, hidden scores) are on the thread: line.',
                       'Every comment carries its permalink: comments <that url> opens it in full with what hangs under '
                       'it.',
                       'requests: the account check (/api/me.json) + 1 request (a share link adds 1 per redirect, at most 3).'],
            'exits': (0, 2, 3, 4, 5, 6, 8, 9, 10),
        },
        'comments': {
            'help': 'Read the next batch of a thread, or one comment in full with what hangs under it.',
            'run': _command(platform.thread_comments),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'A post URL (its next batch), or a comment\'s permalink '
                                                                   '(that comment, always, with its ancestors as context '
                                                                   'and what hangs under it)'}),
                          (('--sort',), {'choices': platform.web_COMMENT_SORTS, 'help': 'Comment order (default best); a reading '
                                                                               'keeps its order'}),
                          (('--limit',), {'type': positive, 'help': 'Comments to show (default 25); with --out, comments to '
                                                               'save'}),
                          (('--depth',), {'type': count, 'help': 'Reply levels to show (default 2), counted from the linked '
                                                               'comment for a comment link'}),
                          'chars', 'after', 'out', 'json'],
            'epilog': ['A batch comes from the snapshot the last post or comments read left (for a day): no listing '
                       'request while it holds comments not yet shown. When none is left within --depth, the next gaps are '
                       'expanded: up to 100 comment ids across gaps in one request, and a "continue this thread" branch in '
                       'one request each. A comment Reddit lists but does not send when asked is counted as asked for but '
                       'never sent (deleted or removed). more: is offered only while a continuation can still show or '
                       'fetch comments within --depth; comments only deeper than --depth, and branches Reddit sent '
                       'nothing for, are left as coverage notes (a larger --depth shows the first kind).',
                       'A comment link is answered from the latest snapshot of its post when it holds that comment; '
                       'otherwise its subtree is read (1 request).',
                       'With --out the whole thread is written: the post once, then every comment flat (parent_id and '
                       'depth), a page per expansion; rerun the same command to resume the same reading even after its '
                       'snapshot expired. A tree whose last branches Reddit will not expand ends partial (8).',
                       'requests: the account check (/api/me.json) + 1 request per expansion (or 1 for a new read); the time limit '
                       'stops a large thread and more: continues.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'images': {
            'help': 'Save the pictures of one post (a gallery, an image post, a video\'s preview) so they can be looked at.',
            'run': _command(platform.images_images),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'A post URL, id or redd.it link (a comment link or a '
                                                                   'share link opens its post)'}),
                          (('numbers',), {'nargs': '*', 'type': positive, 'metavar': 'N',
                                          'help': 'The pictures to save, by the numbers the post shows (media N:)'}),
                          (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
            'epilog': ['The post is read again (preview links are signed and do not last), so N is the Nth picture as Reddit '
                       'sends the post now; each saved line names its kind, size and media_id to match what the post '
                       'showed. Only Reddit\'s own image hosts (i.redd.it, preview.redd.it) are fetched; a picture hosted '
                       'elsewhere is named and skipped. Files go to images/ in the skill\'s state directory and are removed a day later; '
                       'they are other people\'s pictures. A picture that could not be saved is named in coverage (exit 8); a number the post does not have is refused before any picture is fetched (exit 2). A stop between pictures (the time limit, a hold) keeps the saved ones and ends with more: naming the numbers left.',
                       'requests: 1 for the post (plus a share link\'s hops), then 1 per picture.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
    }

    # The closed sets the commands offer (cli.py checks its parser's choices against this).
    CHOICES = {
        'feed.sort': list(platform.web_FEED_SORTS), 'feed.time': list(platform.web_TIMES),
        'sub.sort': list(platform.web_SUB_SORTS), 'sub.time': list(platform.web_TIMES),
        'profile.tab': list(platform.web_PROFILE_TYPES), 'profile.sort': list(platform.web_PROFILE_SORTS), 'profile.time': list(platform.web_TIMES),
        'search.type': list(platform.web_SEARCH_TYPES), 'search.sort': list(platform.web_SEARCH_SORTS), 'search.time': list(platform.web_TIMES),
        'me.collection': list(platform.web_ME_COLLECTIONS),
        'post.sort': list(platform.web_COMMENT_SORTS), 'comments.sort': list(platform.web_COMMENT_SORTS),
    }

    return COMMANDS, CHOICES


def _facebook_surface(platform):
    PLATFORM = platform.PLATFORM
    FEED_SORTS = ['top', 'recent']
    GROUP_SORTS = ['top', 'recent', 'activity']
    COMMENT_SORTS = ['all', 'relevant', 'newest']
    SEARCH_TYPES = ['top', 'posts', 'people', 'pages', 'groups']

    CHOICES = {'feed.sort': FEED_SORTS, 'group.sort': GROUP_SORTS, 'post.sort': COMMENT_SORTS,
               'comments.sort': COMMENT_SORTS, 'search.type': SEARCH_TYPES}


    LIST = ['limit', 'chars', 'after', 'out', 'json']


    def check_replies(options):
        if not (options['target'].isascii() and options['target'].isdigit()):
            raise SnsError('argument', 'A replies handle is the number printed after "replies".',
                           'Copy the whole replies line.')


    def check_search(options):
        if not options['target'].strip():
            raise SnsError('argument', 'Search text must not be empty.', 'Pass the words to search for.')
        if options['type'] not in ('top', 'posts') and (options.get('recent') or options.get('since')
                                                        or options.get('until') or options.get('within')):
            raise SnsError('argument', '--recent, --since, --until and --in are for posts; use them with --type top '
                                       'or posts.', 'Drop the option, or search --type posts.')


    def _positive(value):
        """--limit of the commands whose help says what their limit counts (the shared help speaks of --out)."""
        if value.isascii() and value.isdigit() and int(value) > 0:
            return int(value)
        raise argparse.ArgumentTypeError('expected a positive integer')


    def _chars(value):
        """--chars of the commands without --out (the shared help names --out)."""
        if value.isascii() and value.isdigit():
            return int(value)
        raise argparse.ArgumentTypeError('expected 0 (full text) or a positive integer')


    def _run(function):
        return lambda invocation: function(PLATFORM, invocation)


    COMMANDS = {
        'feed': {
            'help': 'Read your home feed, a page at a time.',
            'run': _run(platform.listing_feed),
            'arguments': [(('--sort',), {'choices': FEED_SORTS, 'default': 'top', 'help': 'top: the order Facebook ranks; recent: newest first'}),
                          'since', 'until',
                          (('--include-sponsored',), {'action': 'store_true', 'help': 'Keep advertisements; by default they are left out and counted'}),
                          *LIST],
            'epilog': ['The feed is what Facebook chose to show this account, not everything its friends and pages posted.',
                       'top is Facebook\'s ranking, which cannot close a --since window: a window keeps the posts dated inside it among those read (a sample, not the whole span). recent is newest first, so a --since window closes at the first page with a dated, unpinned post older than --since; a feed that ends before --since is partial, because Facebook shows no older posts here. A post with no date cannot be placed in a window and is left out and counted. The top feed never ends by itself, so --out needs --limit.',
                       'Without --limit or --out it reads one page (about 5-10 posts), with a window too; more: continues.',
                       'requests: 1 per page of about 5-10 posts.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'profile': {
            'help': 'Read a profile\'s or page\'s timeline.',
            'run': _run(platform.listing_profile),
            'arguments': [(('target',), {'help': 'Profile or page URL, vanity name or numeric id'}), 'since', 'until', *LIST],
            'epilog': ['--since/--until are applied by Facebook (server-filtered) and checked against each post\'s date again; reading to the end closes the window. A post with no date cannot be placed in a window and is left out and counted; a pinned post is judged by its date like the others.',
                       'A timeline can hold posts by other people (posts on the timeline, shares); each record names its author.',
                       'Without --limit or --out it reads one page (about 3-5 posts); a --since/--until window reads on until it ends; more: continues.',
                       'requests: 1 to find the numeric id (none for a numeric id), then 1 per page of about 3-5 posts.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'group': {
            'help': 'Read a group\'s posts.',
            'run': _run(platform.listing_group),
            'arguments': [(('target',), {'help': 'Group URL, vanity name or numeric id'}),
                          (('--sort',), {'choices': GROUP_SORTS, 'default': 'top', 'help': 'top and activity are ranked; recent: newest posts first'}),
                          'since', 'until', *LIST],
            'epilog': ['With --since, only --sort recent can close the window (a group\'s oldest post ends it); top and activity are samples of it. A post with no date cannot be placed in a window and is left out and counted.',
                       'Without --limit or --out it reads one page (about 3-5 posts); a window on recent reads on until it closes; more: continues.',
                       'requests: 1 to find the numeric id (none for a numeric id), then 1 per page of about 3-5 posts.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'post': {
            'help': 'Read one post in full with its first parent comments.',
            'run': _run(platform.thread_post),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'Facebook post permalink (posts/, permalink.php, story.php, photo, videos/, groups/…/posts/)'}),
                          (('--sort',), {'choices': COMMENT_SORTS, 'default': 'all', 'help': 'Comment order: all (ranked, nothing filtered out), relevant (Facebook\'s "most relevant", which can leave comments out), newest'}),
                          (('--limit',), {'type': _positive, 'help': 'Parent comments to show from the first batch'}),
                          (('--chars',), {'type': _chars, 'help': 'Characters of each comment to show (default 180; 0 = all); the post text is always shown in full; --json keeps all'}),
                          'json'],
            'epilog': ['The post text is shown in full. Each comment with replies ends with replies <handle>; more: continues the parent comments as a comments command. Share links (/share/, /reel/, /watch/, fb.watch) are not read: open the post in the browser and copy its own permalink.',
                       'requests: 3 (the page, to find the story; the post; the first comments).'],
            'exits': (0, 2, 3, 4, 5, 6, 8, 9),
        },
        'comments': {
            'help': 'Read a post\'s parent comments, page by page.',
            'run': _run(platform.thread_comments),
            'arguments': [(('target',), {'metavar': 'URL', 'help': 'Facebook post permalink'}),
                          (('--sort',), {'choices': COMMENT_SORTS, 'default': 'all', 'help': 'all (ranked, nothing filtered out), relevant (can leave comments out), newest'}),
                          (('--limit',), {'type': _positive, 'help': 'Parent comments to show; omitted: one page (about 10), or every page with --out. With --out it counts parents saved'}),
                          *[option for option in LIST if option != 'limit']],
            'epilog': ['Replies are not expanded here: each comment with replies ends with replies <handle>, which reads that branch.',
                       'Without --limit or --out it reads one page (about 10 comments); more: continues.',
                       'requests: 2 to find the post (none when continuing with --after), then 1 per page of about 10 comments.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'replies': {
            'help': 'Read one batch of replies under a comment, by the handle post or comments printed.',
            'run': _run(platform.thread_replies),
            'arguments': [(('target',), {'metavar': 'HANDLE', 'help': 'The number after "replies" on a comment or reply'}),
                          (('--limit',), {'type': _positive, 'help': 'Replies to show; omitted: one batch (about 10), or every batch with --out. With --out it counts replies saved'}),
                          'chars', 'out', 'json'],
            'epilog': ['A handle names a batch: the first batch of a comment\'s replies, or the batch after one already shown (more: prints that one). It is not used up: running it again reads the same batch again, live.',
                       'Each reply that has replies of its own ends with replies <handle>, which reads that deeper branch. Facebook\'s reply count includes those deeper replies.',
                       'A deeper branch (the replies under a reply, Facebook\'s last level) is one batch: asked for more, Facebook sends the same replies again, so it ends with stopped=server_capped and a coverage line counting what was not sent. Each of its replies names the comment it answers as its parent, which can be the top comment or another reply in the branch.',
                       'requests: 1 per batch of about 10 replies.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
            'check': check_replies,
        },
        'search': {
            'help': 'Search posts, people, pages or groups.',
            'run': _run(platform.search_search),
            'arguments': [(('target',), {'metavar': 'TEXT', 'help': 'What to search for'}),
                          (('--type',), {'choices': SEARCH_TYPES, 'default': 'top', 'help': 'top mixes posts with people, pages and groups in Facebook\'s order'}),
                          (('--recent',), {'action': 'store_true', 'help': 'Posts only (top, posts): Facebook\'s "recent posts" filter'}),
                          'since', 'until',
                          (('--in',), {'dest': 'within', 'metavar': 'GROUP', 'help': 'Search the posts of one group (its URL, vanity name or numeric id), as the group\'s own search box does'}),
                          *LIST],
            'epilog': ['Results are in Facebook\'s order for this account; people and pages with the same name are different results (compare url and verified).',
                       '--recent, --since and --until are Facebook\'s post filters (top and posts only): Facebook applies the dates, so reaching the end closes the window as far as search returns posts; results stay in Facebook\'s order, not by date. A result with no date cannot be placed in a window and is left out and counted.',
                       '--in searches one group\'s posts (top or posts): requests: 1 to find the group id (none for a numeric id), then 1 per page.',
                       'Without --limit or --out it reads one page (about 5 results); more: continues.',
                       'requests: 1 per page of about 5 results.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
            'check': check_search,
        },
        'about': {
            'help': 'Read a profile\'s or page\'s visible About fields, or a group\'s card.',
            'run': _run(platform.about_about),
            'arguments': [(('target',), {'help': 'Profile or page URL, vanity name or numeric id; or a group by its /groups/ URL'}),
                          (('--section',), {'help': 'Only this locale-independent section, e.g. directory_work (schema about lists them as they appear)'}),
                          'json'],
            'epilog': ['What About shows depends on the viewing account and the owner\'s privacy settings. Fields are never cut.',
                       'A group URL gives the group\'s card instead: name, privacy as Facebook labels and explains it, the member total as Facebook writes it, the viewing account\'s relation to the group, whether joining asks questions, the description, recent activity, creation date and the rules in order. requests: 1 to find the id (none for a numeric /groups/<id>/), then 2 (header and About).',
                       'requests: 1 to find the numeric id (none for a numeric id), 1 for the overview, then 1 per About tab; --section stops at the first tab that shows it.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'images': {
            'help': 'Save the pictures of one post (a video by its poster) so they can be looked at.',
            'run': _run(platform.images_images),
            'arguments': [(('target',), {'help': 'Post permalink URL'}),
                          (('numbers',), {'nargs': '*', 'type': _positive, 'metavar': 'N',
                                          'help': 'The pictures to save, by the numbers the post shows ([image N])'}),
                          (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
            'epilog': ['The post is read again (its picture links are signed and do not last), so N is the Nth picture as '
                       'Facebook sends the post now; each saved line names its kind, size and media_id to match what the '
                       'post showed. A video is saved as its poster image. Files go to images/ in the skill\'s state directory and are '
                       'removed a day later; they are other people\'s pictures. A picture that could not be saved is named '
                       'in coverage (exit 8); a number the post does not have is refused before any picture is fetched (exit 2). A stop between pictures (the time limit, a hold) keeps the saved ones and ends with more: naming the numbers left.',
                       'requests: 2 for the post (its page, then the post), then 1 per picture.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'notifications': {
            'help': 'Read your notification list (its first page) without marking anything seen.',
            'run': _run(platform.notifications_notifications),
            'arguments': [*LIST],
            'epilog': ['Reads the notifications of the account the tab is logged in to, in Facebook\'s order. Each record is [n1] time · type word · unseen, seen or read, then the text Facebook wrote, then url: what it points at (a post permalink opens with post <url>). Bucket headers and the see-previous button are layout and are left out.',
                       'Reading the list sends no seen or read change (those are separate requests this skill never sends); whether Facebook counts a read as seen by itself was not observable when this was measured (no unseen notification at the time). If Facebook stops accepting the stored notifications query the command ends with exit 6 and does not open the notifications screen to relearn it, because opening that screen is what makes the app mark notifications seen.',
                       'It reads the first page (about 15 notifications), which is all it can: asked for the page after, '
                       'Facebook answered nothing when this was measured, so when Facebook says older ones follow it ends '
                       'with stopped=server_capped and a coverage line instead of more:.',
                       'requests: 1.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
    }

    # What every reading command's output holds beyond the shared description (the core's text names no Facebook record
    # kinds and knows nothing of the dedicated tab).
    RECORDS = ('records: one block per record, labelled [p1] post, [c1] comment or reply, [e1] person, page or group, '
               '[n1] notification, each '
               'ending with the arguments of the next command (url: post <url> opens that one post; author: profile <url>; '
               'replies <handle>); about prints one line per field as section: text.')
    TAB = ('the dedicated tab: the skill reads from its own www.facebook.com tab. Opening it costs about 30 requests the '
           'page makes itself while it loads, and moving it to the screen that loads a current query id (when Facebook no '
           'longer accepts a stored one; notifications never does, since that screen marks them seen) about 10 more; '
           'both are shown as "tab opened" and counted apart from the reads, '
           'and requests the page finishes later use up those reservations first. Requests the open tab made between '
           'commands are shown as unwatched=, not charged, but a rate limit or a checkpoint seen there stops the command '
           'before it sends anything. The tab is emptied (about:blank) about 5 minutes after the last command.')
    for _name in ('feed', 'profile', 'group', 'post', 'comments', 'replies', 'search', 'about', 'notifications'):
        COMMANDS[_name]['epilog'] = [*COMMANDS[_name]['epilog'], RECORDS, TAB]
    COMMANDS['images']['epilog'] = [*COMMANDS['images']['epilog'], TAB]

    CHOICES['me.collection'] = ['notifications']
    COMMANDS['me'] = COMMANDS.pop('notifications')
    COMMANDS['me']['arguments'].insert(0, (('collection',), {'choices': ['notifications'], 'metavar': 'KIND', 'help': 'notifications'}))
    return COMMANDS, CHOICES


def _naver_blog_surface(platform):
    PLATFORM = platform.PLATFORM
    # --- the commands --------------------------------------------------------------------------------------------------

    ACCOUNT = ('The account check (current-user, 1 request) comes first for a read that goes on past one screen (a --limit '
               'above the default, a window), for --out and for a continuation (--after). A one-screen read that must '
               'leave a more: line stamps it with the account seen in the last 12 hours instead — a hint, never proof: '
               'continuing it checks the account for real, and a login that changed meanwhile ends as exit 4.')
    PAGE = 'More: shows what a page already brought (no request) before it reads the next page.'


    def positive(value):
        if value.isascii() and value.isdigit() and int(value) > 0:
            return int(value)
        raise argparse.ArgumentTypeError('expected a positive integer')


    def _command(function):
        return lambda invocation: function(PLATFORM, invocation)


    COMMANDS = {
        'search': {
            'help': 'Search Naver Blog for posts, blogs or tags, or one blog\'s own posts and tags.',
            'run': _command(platform.search_search), 'check': platform.search_check,
            'arguments': [(('text',), {'nargs': '+', 'metavar': 'TEXT', 'help': 'What to search for; several words are one '
                                                                                'query (no quotes needed)'}),
                          (('--type',), {'choices': ['posts', 'blogs', 'tags', 'clips'], 'default': None,
                                         'help': 'posts (default), blogs (bloggers), tags (posts under an exact tag), or '
                                                 'clips (short videos)'}),
                          (('--in',), {'dest': 'within', 'metavar': 'BLOG', 'help': 'Search inside one blog (id, URL or naver.me link): '
                                                                    '--type posts or tags'}),
                          (('--sort',), {'choices': ['relevance', 'date'], 'help': 'relevance (Naver\'s relevance, default) or date '
                                                                             '(newest first); posts, blogs and clips'}),
                          'since', 'until',
                          (('--own-money',), {'action': 'store_true', 'help': 'Naver-wide post search: only posts carrying '
                                                                              'Naver\'s 내돈내산 인증 card, a purchase or visit '
                                                                              'Naver recorded (a title or tag saying 내돈내산 '
                                                                              'is not it)'}),
                          'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ['What each search honours (refused otherwise, before any request): posts — --sort, --since/--until '
                       '(Naver filters by KST day) and --own-money; blogs — --sort only; tags — no order (newest first), '
                       'so --since/--until is applied here and closes the window; --in posts — --sort and dates; --in '
                       'tags — neither, and it matches whole tags only. Relevance is Naver\'s ranking for this '
                       'account, not a sample of opinion.',
                       'Naver serves at most 1,000 results of any search: the read ends there as a natural end '
                       '(stopped=server_capped, exit 0, a coverage line says so); narrow the words or the dates to reach '
                       'further. A tag result carries no blog name.',
                       'limit: --limit counts records. Without it one page is read (30 posts or tags, 20 blogs, clips or '
                       'in-blog posts) and 10 are shown. ' + PAGE + ' With --out whole pages are saved, so a little over '
                       '--limit.',
                       'requests: 1 request per page; a --in domain address costs one lookup. ' + ACCOUNT],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'keywords': {
            'help': 'Naver Blog\'s popular searches of the day, or the searches related to one keyword.',
            'run': _command(platform.search_keywords),
            'arguments': [(('text',), {'nargs': '*', 'metavar': 'TEXT', 'help': 'A keyword for its related searches; '
                                                                                'omitted: the popular ones'}), 'json'],
            'epilog': ['Popular: about 12 keywords and the day Naver computed them; related: about 15 keywords. Both are '
                       'Naver\'s own order — a ranking, not a share of searches or of opinion. search <keyword> reads '
                       'one.',
                       'requests: 1 request.'],
            'exits': (0, 2, 3, 4, 5, 6, 7),
        },
        'post': {
            'help': 'Read one post in full: body, pictures, links, tags, reactions, same-category posts.',
            'run': _command(platform.post_post),
            'arguments': [(('target',), {'metavar': 'POST', 'help': 'Post URL (blog.naver.com or m.blog.naver.com), '
                                                                    'blogId/logNo, or a naver.me link to a post'}),
                          (('--comments',), {'action': 'store_true', 'help': 'Also read the first page of comments (10 '
                                                                             'comments with their replies; one request)'}),
                          'chars', (('--out',), {'metavar': 'FILE', 'help': 'Save the post, its sections and its comments '
                                                                           'as NDJSON (written only when every section was read)'}),
                          'json'],
            'epilog': ['The body is never clipped. Its label says how much was read: text[full], text[partial: k of n '
                       'components reduced] (those blocks gave up only their text and pictures) or text[legacy]. Pictures '
                       'are numbered in place ([image N: caption], [sticker: image N]); images <post> N saves one. links: '
                       'lists every outbound link with its host and, for commission or marketing hosts, its id.',
                       'Naver 내돈내산 인증 card: a purchase or visit Naver recorded (shopping order, reservation, receipt, '
                       'payment) that the writer attached — it proves a recorded purchase, not who paid; words in a title '
                       'or tag are not it. likes is the live count of the post\'s reactions; list surfaces can lag it.',
                       'A deleted, private or neighbors-only post answers the same way (exit 9). A failed section (same '
                       'category, comments) is shown beside the others and makes the exit 8.',
                       'The post page names the logged-in account for free (kept as a hint); if it is not the account this '
                       'command started with (--out checks it first), the command ends as a changed login (exit 4).',
                       'requests: 3 requests (the page, its reactions, the same-category posts), +1 with --comments (+1 when '
                       'the blog number is unknown), +1 for a naver.me link, +1 with --out for the account check.',
                       'output: the post section ([p1]: head, tags and flags, the label, the body lines, links:, url), '
                       'then same category ([p<n>] posts) and comments ([c<n>]). --json: one envelope whose sections hold '
                       'the records (schema post_read).'],
            'exits': (0, 2, 3, 4, 5, 6, 8, 9),
        },
        'comments': {
            'help': 'Read a post\'s comments and replies, newest first, replies under their parent.',
            'run': _command(platform.post_comments),
            'arguments': [(('target',), {'metavar': 'POST', 'help': 'Post URL, blogId/logNo, or a naver.me link'}),
                          'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ['Comments come newest first; each comment\'s replies follow it, oldest first, indented '
                       '(reply-to=#n). A reply whose parent is on another page says (parent not shown). blog: <id> on a '
                       'comment is the commenter\'s blog. A coverage line gives Naver\'s own count of comments, replies, '
                       'deleted and blinded ones.',
                       'limit: --limit counts rows (comments and replies together). Without it one page of up to 100 rows '
                       'is read and 20 are shown. ' + PAGE,
                       'requests: 1 request to find the blog number (a continuation carries it), then 1 per 100 rows. '
                       + ACCOUNT],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'images': {
            'help': 'Save a post\'s pictures by their numbers so they can be looked at (Read the printed path).',
            'run': _command(platform.images_images),
            'arguments': [(('target',), {'metavar': 'POST', 'help': 'Post URL, blogId/logNo, or a naver.me link'}),
                          (('numbers',), {'nargs': '*', 'type': positive, 'metavar': 'N', 'help': 'Picture numbers as '
                                                                                              'post shows them ([image N])'}),
                          (('--all',), {'action': 'store_true', 'help': 'Every picture of the post (stickers, cards and '
                                                                        'maps included)'}), 'json'],
            'epilog': ['Reads the post again (1 request) and saves each picture (1 request each) under images/ in the skill\'s state directory, '
                       'printing one line per picture with its path. A picture can say what the text does not: prices on '
                       'a menu, a disclosure drawn into a photo or a sticker. The files are other people\'s photos; the '
                       'skill removes each once it is 24 hours old (the next time it runs), so nothing needs deleting by '
                       'hand.',
                       'A picture that cannot be saved (gone, over 10 MB, hosted outside Naver, not a picture) is named '
                       'and skipped, the rest are saved (exit 8). A stop (the time limit, a hold) ends with more: naming '
                       'the numbers left.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'resolve': {
            'help': 'Show where naver.me short links lead, without following them.',
            'run': _command(platform.post_resolve),
            'arguments': [(('target',), {'nargs': '+', 'metavar': 'LINK', 'help': 'naver.me/<code> links (as post\'s '
                                                                                   'links: block prints them)'}),
                          'json'],
            'epilog': ['Each link is read once and its redirect reported, never followed: the destination with its host '
                       'and, for commission or marketing hosts (brandconnect.naver.com is a creator\'s shopping-connect '
                       'link), its id; a Naver Blog post destination is named as post takes it.',
                       'Any number of links is read. When the time limit or a hold interrupts, the links not yet read go '
                       'on in the more: command, which names them.',
                       'requests: 1 request per link.'],
            'exits': (0, 2, 3, 4, 5, 6, 8),
        },
        'about': {
            'help': 'Read a blog\'s card, post and clip counts, category tree, notices and popular posts.',
            'run': _command(platform.blog_blog),
            'arguments': [(('target',), {'metavar': 'BLOG', 'help': 'Blog id, blog URL (a post URL names its blog), or a '
                                                                    'naver.me link'}),
                          (('--brief',), {'action': 'store_true', 'help': 'Card, counts and categories only (3 requests)'}),
                          'chars', 'json'],
            'epilog': ['The card: name, nickname, description, neighbor count, visitors today and in total, posts and '
                       'clips, the viewer\'s relation (neighbor or mutual-neighbor), official/market/power-blog marks. '
                       'Categories are the tree ([n] name · posts; closed ones are counted, not listed). Popular posts are '
                       'the only surface with view counts. A domain address is resolved once to the blog\'s own id.',
                       'requests: 5 requests (card, counts, categories, notices, popular); --brief 3; +1 for a domain address '
                       'or a naver.me link.',
                       'output: sections blog ([b1]), categories, notices and popular ([p<n>]); a failed section is shown '
                       'and makes the exit 8.'],
            'exits': (0, 2, 3, 4, 5, 6, 8, 9),
        },
        'profile': {
            'help': 'List one blog\'s posts newest first: all, one category, its notices or its popular posts.',
            'run': _command(platform.blog_posts), 'check': platform.blog_check,
            'arguments': [(('target',), {'metavar': 'BLOG', 'help': 'Blog id, blog URL (a PostList URL\'s categoryNo counts '
                                                                    'as --category), or a naver.me link'}),
                          (('--category',), {'metavar': 'N|NAME', 'help': 'A category number (free) or name (one request: '
                                                                          'exact match first, then part of a name)'}),
                          (('--tab',), {'choices': ['posts', 'popular', 'notices'], 'default': 'posts', 'help': 'The posts, popular posts (one page, with view counts), or notice posts (one page)'}),
                          'since', 'until', 'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ['The list is newest first, so --since closes it at the first post older than that day. Naver '
                       'reports no total here. Popular and notices are one page each: no window, file or more:.',
                       'limit: --limit counts posts. Without it one page of 30 is read and 10 are shown. ' + PAGE,
                       'requests: 1 request per page of 30 (+1 for a category name, a domain address or a naver.me link). '
                       + ACCOUNT],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'feed': {
            'help': 'Read the logged-in account\'s neighbor feed (이웃새글), newest first, a page at a time.',
            'run': _command(platform.neighbors_feed),
            'arguments': [(('--group',), {'type': positive, 'metavar': 'N', 'help': 'Only one neighbor group (me '
                                                                                   'groups lists them)'}),
                          'since', 'until', 'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ['Only the blogs this account follows, newest first, so --since closes at the first post older than '
                       'that day. A coverage line gives Naver\'s count of feed posts.',
                       'limit: --limit counts posts. Without it one page of 20 is read and 10 are shown. ' + PAGE,
                       'requests: 1 request per page of 20, after the account check (current-user, 1 request: the feed is '
                       'addressed by the logged-in account\'s blog id, so it is always asked, and a continuation asks '
                       'again).'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'graph': {
            'help': 'Read the logged-in account\'s neighbor list, or a blog\'s public one.',
            'run': _command(platform.neighbors_buddies), 'check': platform.neighbors_check,
            'arguments': [(('target',), {'nargs': '?', 'metavar': 'BLOG', 'help': 'A blog id or URL for its public neighbor '
                                                                                  'list; omitted: your own neighbors'}),
                          (('relation',), {'choices': ['buddies', 'followers'], 'metavar': 'RELATION', 'help': 'buddies or followers'}),
                          (('--group',), {'type': positive, 'metavar': 'N', 'help': 'Only your neighbors in one group'}),
                          'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ['followers and --group read your own account and take no blog. Your own list (20 a '
                       'page) carries mutual (서로이웃) and your groups; a blog\'s public list (50 a page) is private by '
                       'default, so an empty one (exit 7) does not mean no neighbors — about <id> shows the card\'s count.',
                       'limit: --limit counts neighbors. Without it one page is read and 20 are shown. ' + PAGE,
                       'requests: 1 request per page; your own lists ask the account first (current-user, 1 request), a '
                       'blog\'s public list does not.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'topic': {
            'help': 'Browse the topic directory, or one topic\'s newest or featured posts.',
            'run': _command(platform.directory_topic), 'check': platform.directory_check,
            'arguments': [(('target',), {'nargs': '?', 'metavar': 'TOPIC', 'help': 'Topic number (free) or name (one '
                                                                                   'request); omitted: the directory'}),
                          (('--tab',), {'choices': ['newest', 'featured'], 'default': 'newest', 'help': 'The topic\'s newest or featured posts (one page)'}),
                          'since', 'until', 'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ['A topic\'s posts are the ones Naver files under it, newest first (a window closes on them), up to '
                       '1,000 (then stopped=server_capped, a natural end). The directory and featured posts are one page '
                       'each: no window, file or more:.',
                       'limit: --limit counts posts. Without it one page of 10 is read and shown. ' + PAGE,
                       'requests: 1 request per page of 10 (+1 for a topic name). ' + ACCOUNT],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'monthly': {
            'help': 'Read the blogs of the month: an issue\'s topics, blogs and representative posts.',
            'run': _command(platform.directory_monthly), 'check': platform.directory_check_monthly,
            'arguments': [(('--year',), {'type': positive, 'help': 'Issue year (with --month); omitted: the latest issue'}),
                          (('--month',), {'type': positive, 'help': 'Issue month 1-12 (with --year)'}), 'chars', 'json'],
            'epilog': ['A coverage line names the issue shown. A month with no issue (the current one before it is '
                       'published) is exit 9 naming the latest, never silently swapped for it. Each topic section lists '
                       'its blogs ([b] card) each followed by its first representative posts.',
                       'requests: 4 requests (the issue list, the issue, the blogs\' cards, their posts).',
                       'output: one section per topic: [b<n>] blog cards, each followed by [p<n>] posts.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
    }

    COMMANDS['me'] = {**COMMANDS['graph'], 'help': 'Read your neighbor groups.', 'arguments': [(('collection',), {'choices': ['groups'], 'metavar': 'KIND', 'help': 'groups'}), 'limit', 'chars', 'after', 'out', 'json']}

    # The closed sets the commands offer (cli.py checks its parser's choices against this).
    CHOICES = {'search.type': ['posts', 'blogs', 'tags', 'clips'], 'search.sort': ['relevance', 'date'], 'profile.tab': ['posts', 'popular', 'notices'], 'graph.relation': ['buddies', 'followers'], 'me.collection': ['groups'], 'topic.tab': ['newest', 'featured']}

    return COMMANDS, CHOICES


def command_tables(platforms):
    """Build the command and choice tables from platform interfaces."""
    factories = {'x': _x_surface, 'threads': _threads_surface, 'reddit': _reddit_surface, 'facebook': _facebook_surface, 'naver_blog': _naver_blog_surface}
    tables = {word: factories[module.PLATFORM.key](module) for word, module in platforms.items()}
    return ({word: table[0] for word, table in tables.items()},
            {word: table[1] for word, table in tables.items()})


def load_platforms():
    """The platform packages that exist, as {word: module}; each exports its adapter and feature interface."""
    found = {}
    for name in PLATFORM_PACKAGES:
        if importlib.util.find_spec(f'sns.{name}') is not None:
            module = importlib.import_module(f'sns.{name}')
            found[module.PLATFORM.word] = module
    return found


def surface(module, commands):
    """A platform's commands with the shared ones after them."""
    return {**commands, **shared_commands(module.PLATFORM)}


def parser(platforms, hidden=False, commands=None):
    commands = command_tables(platforms)[0] if commands is None else commands
    lines = [f'  {word:<11} {" ".join(surface(module, commands[word]))}' for word, module in platforms.items()]
    root = Parser(prog='cli.py', usage='cli.py [--verbose] <platform> <command> [options]', description=__doc__,
                  formatter_class=argparse.RawTextHelpFormatter, add_help=True,
                  epilog='platforms and their commands (cli.py <platform> <command> --help explains one):\n'
                         + '\n'.join(lines) + '\n\nA URL of another platform is refused with the command that reads '
                         'it. Every result ends with the\nnext command (more:, replies <handle>, post <url>); '
                         '<platform> schema describes every field.\n\nexit codes:\n'
                         + '\n'.join(f'  {code:<2} {meaning}' for code, meaning in EXIT_SUMMARY.items()))
    root.add_argument('--verbose', action='store_true', help='Write scrubbed request metadata to stderr')
    branches = root.add_subparsers(dest='platform', required=True, metavar='<platform>', help=argparse.SUPPRESS)
    templates = {'--tab': 'Choose the view.', '--sort': 'Choose the order.', '--type': 'Choose the result type.', '--in': 'Choose the search scope.', '--limit': 'How many to show; the description explains what is counted.', '--chars': 'Characters of each text to show; the description explains the default.'}
    for word, module in platforms.items():
        platform = module.PLATFORM
        platform_commands = surface(module, commands[word])
        branch = branches.add_parser(word, prog=f'cli.py {word}', formatter_class=argparse.RawTextHelpFormatter,
                                     description=f'{platform.title}: its commands. Run cli.py {word} <command> '
                                                 '--help for one.')
        leaves = branch.add_subparsers(dest='command', required=True, metavar='<command>')
        for name, spec in platform_commands.items():
            leaf = leaves.add_parser(name, help=spec['help'], description=spec['help'], epilog=epilog(spec),
                                     formatter_class=argparse.RawTextHelpFormatter, prog=f'cli.py {word} {name}')
            details = []
            for argument in spec['arguments']:
                flags, settings = option(argument, platform) if isinstance(argument, str) else argument
                settings = dict(settings)
                if flags[0] == 'target':
                    labels = {'profile': 'ACCOUNT', 'about': 'ACCOUNT', 'graph': 'ACCOUNT', 'sub': 'SUB', 'wiki': 'SUB', 'group': 'GROUP', 'list': 'LIST', 'community': 'COMMUNITY', 'post': 'POST', 'comments': 'POST', 'related': 'POST', 'images': 'POST', 'reposts': 'POST', 'quotes': 'POST', 'replies': 'HANDLE', 'search': 'TEXT', 'topic': 'TEXT', 'resolve': 'TEXT'}
                    settings['metavar'] = 'BLOG' if word == 'naver-blog' and name in ('profile', 'about', 'graph') else labels.get(name, settings.get('metavar', 'TEXT'))
                elif flags[0] == 'page':
                    settings['metavar'] = 'PAGE'
                elif flags[0] in ('collection', 'relation'):
                    settings['metavar'] = 'KIND' if flags[0] == 'collection' else 'RELATION'
                if flags[0] in templates or flags[0] in ('--limit', '--chars', '--after', '--out', '--json'):
                    old_help = settings.get('help')
                    generic = templates.get(flags[0]) or option(flags[0][2:], platform)[1]['help']
                    if old_help and old_help != generic:
                        details.append(f'{flags[0]}: {old_help}')
                    settings['help'] = generic
                leaf.add_argument(*flags, **settings)
            if details:
                leaf.epilog = leaf.epilog.replace('exit codes:\n', '\n'.join(details) + '\n\nexit codes:\n')
        if hidden:  # the idle cleanup the skill starts itself; not part of the help
            leaf = leaves.add_parser('idle', prog=f'cli.py {word} idle')
            leaf.add_argument('--account', required=True)
            leaf.add_argument('--token', required=True)
            leaf.add_argument('--after', type=int, default=300)
    return root


def validate(options, spec):
    for key in ('target', 'out'):
        values = options.get(key)
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise SnsError('argument', f'The {key} contains a line break or another control character.',
                               'Pass it on one line.')
    if options.get('since') and options.get('until') and options['since'] > options['until']:
        raise SnsError('argument', '--since must not be later than --until.', 'Swap the two dates.')
    if options.get('after') and options.get('out'):
        raise SnsError('argument', '--after and --out cannot be combined; --out resumes its own file.',
                       'Rerun the same command with the same --out path.')
    if spec.get('check'):
        spec['check'](options)


def emit(kind, envelope, options, module):
    machine = options.get('json') or options.get('command') in ('doctor', 'schema', 'idle') or module is None
    if options.get('out') and envelope.get('out') is not None and (envelope['ok'] or envelope.get('count')):
        print(json.dumps({k: v for k, v in envelope.items() if k != 'results'}, ensure_ascii=False) if machine
              else summary(envelope))
    elif machine or (not envelope['ok'] and not envelope.get('results') and not envelope.get('sections')):
        print(json.dumps(envelope, ensure_ascii=False))
    else:
        drawn = module.PLATFORM.render(envelope, options.get('chars'), options['command'])
        lines, shown = drawn if isinstance(drawn, tuple) else (drawn, None)
        print(page(envelope, lines, shown))
    return KIND_EXIT[kind]


def main(argv=None, platforms=None, commands=None):
    deadline = Deadline()  # the invocation's one deadline, made first: everything after it fits inside
    argv = sys.argv[1:] if argv is None else argv
    platforms = load_platforms() if platforms is None else platforms
    commands = command_tables(platforms)[0] if commands is None else commands
    options, module = {'command': None}, None
    try:
        hidden = len(argv) >= 2 and argv[1] == 'idle'
        options = vars(parser(platforms, hidden=hidden, commands=commands).parse_args(argv))
        module = platforms[options['platform']]
        # an old install's data/, for every platform, before anything else (a later reinstall removes it again)
        adopt_all([m.PLATFORM for m in platforms.values()], deadline, own=module.PLATFORM.key)
        if options['command'] == 'idle':
            outcome = idle(module.PLATFORM, Invocation(options, deadline, {w: m.PLATFORM for w, m in platforms.items()},
                                                       cli_path()), options['account'], options['token'], options['after'])
            print(json.dumps({'ok': True, 'command': 'idle', 'outcome': outcome}))
            return 0
        spec = surface(module, commands[options['platform']])[options['command']]
        validate(options, spec)
        exit_codes = [(code, meaning, [k for k, c in KIND_EXIT.items() if c == code])
                      for code, meaning in EXIT_CODES.items()]
        invocation = Invocation(options, deadline, {w: m.PLATFORM for w, m in platforms.items()}, cli_path(),
                                exit_codes)
        foreign(module.PLATFORM, invocation, options.get('target'))  # another platform's link: name its command
        kind, envelope = spec['run'](invocation)
    except SnsError as error:
        kind, envelope = failure_envelope(error, module.PLATFORM.key if module else None, options.get('command'))
    return emit(kind, envelope, options, module)


def cli_path():
    return __file__


if __name__ == '__main__':
    sys.exit(main())
