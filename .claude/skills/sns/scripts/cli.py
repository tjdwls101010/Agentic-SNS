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
from sns.platforms import PLATFORM_PACKAGES
from sns.reading import Invocation, adopt_all, doctor, foreign, idle
from sns.render import page, summary
from sns.results import failure_envelope


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
# The same table in a few words, one line per code in each command's --help and packed into the top-level map; the
# full meaning is EXIT_CODES, which schema result prints.
EXIT_SUMMARY = {0: 'read, or stopped where more: resumes', 2: 'bad arguments, handle, file or URL',
                3: 'Aside or the tab failed', 4: 'login needed, or the account changed',
                5: 'blocked: a person must clear it, or rate-limited before any record',
                6: 'a request failed before any record', 7: 'explicitly nothing', 8: 'partial',
                9: 'not readable by this account', 10: 'a named limit ran out before any record'}
KIND_EXIT = {'records': 0, 'resumable': 0, 'complete': 0, 'maintenance': 0, 'argument': 2, 'aside': 3, 'login': 4,
             'blocked': 5, 'failed': 6, 'empty': 7, 'partial': 8, 'unavailable': 9, 'scope_limit': 10}

# The words that mean the same on every platform that has them (plan '목표 문법'), in the map's order; a platform's
# other commands are its own places.
CORE_COMMANDS = ('feed', 'profile', 'about', 'graph', 'me', 'post', 'comments', 'replies', 'search', 'images')
MEANINGS = """these words mean the same wherever a platform has them (cli.py <platform> <command> --help explains one):
  feed      your home feed                      profile  an account's posts (or a --tab it has)
  about     an account's or a place's card      me       your own saved, liked, notified
  post      one post in full with its replies   search   posts, accounts or places
  images    save a post's pictures to look at   graph    who follows whom
  replies, comments   the rest of a thread; a result prints the exact next command
  doctor    Aside, login, blocks and limits     schema   what results and fields mean (no request)"""
CONVENTIONS = """--sort, --tab and --type take each platform's own words. A URL of another platform or another kind is
refused with the command that reads it. A read starts with what was read, why it stopped and the next
command when there is one, and names a file that keeps the whole result for about a day."""

# The dedicated tab of the platforms that read through one: doctor --help is its one owner (each reading command's
# first line only says what "tab opened" there means).
TABS = {
    'x': 'the dedicated tab: the skill reads from its own x.com tab. Opening it (or loading it again) costs about 15-25 '
         'requests the page makes itself while it loads, shown as "tab opened" and counted apart from the reads; '
         'requests the open tab made between commands are shown as unwatched=, not charged, but a block seen there '
         'stops the command before it sends anything; static files do not count. The tab is closed about 5 minutes '
         'after the last command.',
    'threads': 'the dedicated tab: the skill reads from its own threads.com tab. Opening it (or loading it again after '
               'it was emptied) costs about 34-40 requests the page makes itself, shown as "tab opened" and counted '
               'apart from the reads; learning a query Threads refused reads one document per try (at most 3 tries and '
               'one reload a command); requests the page itself sends while a read runs are counted with that read, so '
               'requests= can be a few more than the requests: line of a command says; requests the open tab made '
               'between commands are shown as unwatched=, not charged, but a block seen there stops the command before '
               'it sends anything; static files do not count. The tab is emptied (about:blank) about 5 minutes after '
               'the last command.',
    'facebook': 'the dedicated tab: the skill reads from its own www.facebook.com tab. Opening it costs about 30 requests '
                'the page makes itself while it loads, and moving it to the screen that loads a current query id (when '
                'Facebook no longer accepts a stored one; notifications never does, since that screen marks them seen) '
                'about 10 more; both are shown as "tab opened" and counted apart from the reads, and requests the page '
                'finishes later use up those reservations first. Requests the open tab made between commands are shown '
                'as unwatched=, not charged, but a rate limit or a checkpoint seen there stops the command before it '
                'sends anything. The tab is emptied (about:blank) about 5 minutes after the last command.',
}
# The record labels of a platform's text output: schema result is their one owner (Reddit's and Naver Blog's record
# schemas name their labels themselves).
LABELS = {
    'x': 'labelled [p1] post, [r1] reply, [a1] account, [t1] trend or event, [l1] list, [c1] community, [s1] space, '
         '[n1] notification; each ends with the arguments of the next command (url: post <url> opens that one post; '
         'author; replies <handle>; search: <query>)',
    'threads': 'labelled [p1] post, [r1] reply, [a1] account, [n1] notification; each ends with the arguments of the '
               'next command (url: post <url> opens that one post; author; replies <handle>)',
    'facebook': 'labelled [p1] post, [c1] comment or reply, [e1] person, page or group, [n1] notification, [s1] saved '
                'item, [m1] photo; each ends '
                'with the arguments of the next command (url: post <url> opens that one post; author: profile <url>; '
                'replies <handle>); about prints one line per field as section: text',
}


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
        'limit': (('--limit',), {'type': positive, 'help': 'How many to show (with --out: to save)'}),
        'since': (('--since',), {'type': day, 'metavar': 'DAY', 'help': f'First day to include, YYYY-MM-DD, in '
                                                                        f'{_zone(platform)}'}),
        'until': (('--until',), {'type': day, 'metavar': 'DAY', 'help': f'Last day to include, YYYY-MM-DD, in '
                                                                        f'{_zone(platform)}'}),
        'chars': (('--chars',), {'type': chars, 'help': 'Characters of each text to show (default 180; 0 = all)'}),
        'after': (('--after',), {'type': positive, 'metavar': 'HANDLE', 'help': 'The handle a more: line '
                                                                                'printed'}),
        'out': (('--out',), {'metavar': 'FILE', 'help': 'An NDJSON file to save to; rerun to resume'}),
        'json': (('--json',), {'action': 'store_true', 'help': 'Print one JSON envelope'}),
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
                       'requests_last_hour and requests_last_day (every command of this account, which all share one '
                       'lock and the platform\'s pacing; there is no request budget), idle_seconds, data_dir (the state every install of the skill '
                       'on this computer shares), imported_from (an old install\'s data/ taken in), protection_state, '
                       'holds_personal_data and the platform\'s own checks. A saved block is reported as exit 5 without '
                       'touching the browser.',
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
                       'off to keep it).', *([TABS[platform.key]] if platform.key in TABS else [])],
            'exits': (0, 2, 3, 4, 5, 6, 10),
        },
        'schema': {
            'help': 'Describe results, NDJSON output files and record fields; always JSON, no request.',
            'run': lambda invocation: schema(platform, invocation, LABELS.get(platform.key)),
            'arguments': [(('object',), {'nargs': '?', 'choices': objects(platform),
                                         'help': 'What to describe; omitted: the list of objects'})],
            'epilog': ['output: one JSON envelope; results holds the requested description (result: the envelope, '
                       'stop reasons, kinds, exit codes, window coverage and the text page\'s record labels; out: the '
                       'NDJSON file a read writes; the others: record fields), or one line per object.'],
            'requests': 'none.',
            'exits': (0, 2),
        },
    }


def common(word, flags, spec, tab):
    """⑤ of a command's --help: what every read's output holds, said only with the options this command has (when a
    read stops, and the time limit, are schema result's stop reasons)."""
    lines = ['output: first line "… N shown · stopped=<reason> · requests=<n> · saved=<file>" (the whole '
             + ('--json result, texts uncut' if '--json' in flags else 'result') + ', kept a day)'
             + ('; tab opened (+n) is the skill\'s tab loading (doctor --help)' if tab else '') + '.']
    more = []
    if '--after' in flags:
        more.append('Without --limit' + (' or --out' if '--out' in flags else '') + ' it reads one page unless said '
                                                                                  'above')
    if spec.get('more', '--after' in flags):
        more.append('more: <command> continues (handles last 24 hours, URLs forever)')
    if more:
        lines.append('; '.join(more) + '.')
    if '--out' in flags:
        lines.append('--out FILE: ' + ('whole pages (a little over --limit)' if '--limit' in flags else 'the records')
                     + ', one line to stdout; keep the file out of the repository.')
    lines += ['failure: one JSON envelope (error, message, fix) if nothing was read; else the records read (exit 8).',
              f'{word} schema result: fields, stop reasons, exit codes; {word} schema: record kinds.']
    return '\n'.join(lines)


def epilog(spec, word, flags, tab):
    """A command's --help below its arguments: ③ what it reads, ④ requests:, ⑤ the common block, ⑥ exit codes."""
    parts = list(spec.get('epilog') or [])
    if spec.get('requests'):
        parts.append('requests: ' + spec['requests'])
    if '--json' in flags:
        parts.append(common(word, flags, spec, tab))
    parts.append('exit codes:\n' + '\n'.join(f'  {code}  {EXIT_SUMMARY[code]}' for code in spec['exits']))
    return '\n\n'.join(parts)


def exit_map(width=110):
    """The exit codes packed into a few lines for the top-level map."""
    lines, line = [], ''
    for code, meaning in EXIT_SUMMARY.items():
        entry = f'{code} {meaning}'
        if line and len(line) + 3 + len(entry) > width:
            lines.append(line)
            line = ''
        line = f'{line}   {entry}' if line else f'  {entry}'
    return '\n'.join([*lines, line])


def _x_surface(platform):
    PLATFORM = platform.PLATFORM
    FEED_CHOICES = ['foryou', 'following']
    PROFILE_TABS = ['posts', 'replies', 'reposts', 'media', 'highlights', 'articles', 'lists', 'memberships']
    GRAPH_RELATIONS = ['following', 'followers', 'verified', 'known', 'similar']
    ME_COLLECTIONS = ['bookmarks', 'likes', 'notifications', 'verified', 'mentions']
    LIST_TABS = ['posts', 'members', 'about']
    COMMUNITY_TABS = ['posts', 'media', 'members', 'about']
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
        if options['type'] == 'accounts' and any(options.get(k) for k in ('since', 'until')):
            raise SnsError('argument', '--since and --until filter posts, not accounts.', 'Drop them, or search posts.')
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
            'epilog': ['foryou is what X chose to show this account, not everything; following holds only the accounts it follows, and X does not serve it newest first either, so neither feed can close a --since window: a window keeps the posts dated inside it among those read (a sample, not the whole day), on one page too. Neither feed ends by itself, so --out needs --limit.',
                       "A repost row is the reposter's act, dated when it was reposted; the words are the original's, shown under it with their own author. Promoted posts (ads) are included, marked [ad], and count toward --limit."],
            'requests': '1 per page of about 20 posts.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'profile': {
            'help': 'Read a profile\'s tab: posts (with reposts), replies, reposts, media, highlights, articles, lists or memberships.',
            'run': _run(platform.listing_profile),
            'arguments': [(('target',), {'help': f'{TARGET_ACCOUNT}; a tab URL such as /<handle>/with_replies reads that tab'}),
                          (('--tab',), {'choices': PROFILE_TABS, 'help': 'The tab (default: the URL\'s tab, else posts)'}),
                          'since', 'until', *LIST],
            'epilog': ["posts holds the account's posts and reposts (X's own Posts tab now hides reposts); a repost row is dated when it was reposted. reposts lists the posts this account reposted, newest first as X orders them. posts and replies are newest first, so a --since window reads on and closes at the first page wholly older than it (a pinned post sits first whatever its date and does not close it). media, highlights and articles are not in date order: a window only filters the page read, and covers them only when read to the end.",
                       'lists are the lists the account made or follows, memberships the lists others put it in; both hold lists (list <url> reads one) and take no window. A protected account this account does not follow is unavailable (exit 9).'],
            'requests': '1 to find the account, then 1 per page of about 20 posts (the lists tab: about 100 lists).',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'about': {
            'help': 'Read an account\'s card, several accounts\' cards in one request, or a space\'s card.',
            'run': _run(platform.about_about),
            'arguments': [(('target',), {'nargs': '+', 'help': 'X @handle or profile URL, several read together; or one x.com/i/spaces/<id> link'}),
                          'json'],
            'epilog': ["A card: name, bio, links, location, join date, counts (followers, following, posts), whether it is protected, its relation to you, and its marks: a paid check is an X subscription, not an identity check; a Business or Government badge is granted by X to an organisation; a declared Parody, Commentary or Fan label is the account's own. Several handles: those X did not return are named (unresolved).",
                       'A space link reads the space: title, live/scheduled/ended, host and speakers, listener counts and whether a replay is kept; a space X no longer keeps is unavailable (exit 9).'],
            'requests': '1.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 9, 10),
        },
        'graph': {
            'help': 'Read the accounts a profile follows or that follow it, or the accounts X recommends as similar.',
            'run': _run(platform.listing_graph),
            'arguments': [(('target',), {'help': TARGET_ACCOUNT}),
                          (('relation',), {'choices': GRAPH_RELATIONS, 'help': 'following, followers, verified (followers with a paid check), known (its followers you follow) or similar (X\'s recommendation)'}),
                          *LIST],
            'epilog': ["A follow records what an account did, not friendship or agreement; similar is X's recommendation of accounts like this one, not a relationship. Counts on the card (about) are what X reports; the list is what X serves, page by page, and it can stop early: three pages in a row with no new account end the read (stopped=query_failure with that reason)."],
            'requests': '1 to find the account, then 1 per page of about 20 accounts.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'me': {
            'help': 'Read your own bookmarks, likes, notifications or mentions.',
            'run': _run(platform.listing_me),
            'arguments': [(('collection',), {'choices': ME_COLLECTIONS, 'help': 'bookmarks, likes (X shows only your own), notifications, verified or mentions'}),
                          *LIST],
            'epilog': ["In X's order (most recently saved or liked first, as X serves it); each post keeps its own date, not when you saved or liked it. There is no date window: X does not serve these in date order.",
                       'notifications are X\'s notification tab as records (what happened, when, which accounts and posts); "suggested by X" marks X recommending something, not anyone\'s act. mentions are the posts that mention you. The skill never opens X\'s notifications screen, which marks them as read; the unread count X shows stayed the same for two minutes after a read when this was measured (X\'s own refresh of it was not observed). A notification\'s message names other people.'],
            'requests': '1 per page of about 20 posts.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'list': {
            'help': 'Read an X list: its posts, its members or its card.',
            'run': _run(platform.listing_lists),
            'arguments': [(('target',), {'help': 'x.com/i/lists/<id> URL or the numeric list id'}),
                          (('--tab',), {'choices': LIST_TABS, 'default': 'posts', 'help': 'posts (from its members), members, or about (the card)'}),
                          *LIST],
            'epilog': ["A list is a set of accounts someone curated; its posts are its members' posts in X's order, so they are not the members' whole output and no window closes on them. about is one record: name, owner, members, followers, private or public; a private list of someone else, or a deleted one, is unavailable (exit 9)."],
            'requests': '1 per page of about 20; about: 1.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            'check': check_list,
        },
        'community': {
            'help': 'Read a community\'s posts, media, members or card, or without a target the communities X suggests.',
            'run': _run(platform.listing_community),
            'arguments': [(('target',), {'nargs': '?', 'help': 'x.com/i/communities/<id> URL or the numeric id; omitted: the communities X suggests to this account'}),
                          (('--tab',), {'choices': COMMUNITY_TABS, 'help': 'posts (default), media, members, or about (the card); with a target only'}),
                          (('--sort',), {'choices': COMMUNITY_SORTS, 'help': 'posts: top (default, X\'s ranking) or recent'}),
                          *LIST],
            'epilog': ["A community is a group with its own feed: its posts are what members posted there, in X's order (top is a ranking; recent was not verified as newest first), so no window closes on them. about is one record: size, moderators, how one joins, topic, rules, who made it and your role. search reads posts across all communities with its communities scope.",
                       "A suggested community is X's recommendation for this account, not a ranking of all communities."],
            'requests': '1 per page; about: 1.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            'check': check_community,
        },
        'post': {
            'help': 'Read one post in full with its parent chain and first batch of replies, or several posts by id.',
            'run': _run(platform.thread_post),
            'arguments': [(('target',), {'nargs': '+', 'help': 'x.com post URL or numeric id; several: those posts only, without replies'}),
                          (('--sort',), {'choices': REPLY_SORTS, 'default': 'top', 'help': 'Reply order: top (X\'s ranking) or recent (newest first)'}),
                          (('--limit',), {'type': _positive, 'help': 'Reply threads to show from the first batch (each reply with what hangs under it)'}),
                          (('--chars',), {'type': _chars, 'help': 'Characters of each parent and reply to show (default 180; 0 = all); the post itself is always shown in full; --json keeps all'}),
                          'json'],
            'epilog': ['The post is shown in full (a long post\'s whole text, an article\'s whole body), after the posts it answers (parent), then its first batch of replies, each thread as X shows it: depth is a reply\'s place in the thread, and "reply to a post not shown" marks where X skipped posts. A reply with more under it ends with replies <handle>, which reads that branch from the reply\'s own page; more: reads the next batch of direct replies; a coverage line names the handle for the replies X hid as probable spam or low quality.',
                       "top is X's ranking, which by X's own description puts paid subscribers' replies higher; recent is newest first and does not include the replies X hid. A community note under a post is context other users added and rated helpful, not the author's words. An edited post lists its versions; post <id> opens any of them.",
                       'Several ids: one request for those posts in full, without replies; ids X did not return are named (unresolved).'],
            'requests': '1 (the post, its parents and the first replies in one read).',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            'check': check_post,
        },
        'replies': {
            'help': 'Read the next batch of a post\'s replies, the replies X hid, or the replies under one reply, by handle.',
            'run': _run(platform.thread_replies),
            'arguments': [(('target',), {'help': 'The number after "replies" or in a more: line'}),
                          (('--limit',), {'type': _positive, 'help': 'Replies to show; omitted: one batch, or every batch with --out. With --out it counts replies saved'}),
                          'chars', 'out', 'json'],
            'epilog': ["A handle names a batch: the next batch of a post's direct replies, the replies X hid, or every reply one reply's own page lists (batch by batch). Running it again reads the same batch again, live; it is not a replay. more: prints the handle of the batch after."],
            'requests': '1 per batch of about 30-40 replies.',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            'check': check_replies,
        },
        'reposts': {
            'help': 'Read the accounts that reposted one post.',
            'run': _run(platform.listing_reposts),
            'arguments': [(('target',), {'help': 'x.com post URL or numeric id'}), *LIST],
            'epilog': ['A repost is an account sharing the post as it is, which records the act, not agreement; quotes reads the posts that add words. The list is what X serves, page by page; three pages in a row with no new account end the read.'],
            'requests': '1 per page of about 20 accounts.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'quotes': {
            'help': 'Read the posts that quote one post.',
            'run': _run(platform.search_quotes),
            'arguments': [(('target',), {'help': 'x.com post URL or numeric id'}),
                          (('--sort',), {'choices': REPLY_SORTS, 'default': 'top', 'help': 'top (X\'s ranking) or recent'}),
                          *LIST],
            'epilog': ["Each quote is its own post with two voices: the quoter's words, and the quoted post shown under it with its own author. Asked the way X's own quotes screen asks (a search for the post's id and its media links), so it shares search's limit (about 50 per 15 minutes)."],
            'requests': '1 per page of about 20.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'search': {
            'help': 'Search posts, accounts or media, with X\'s search operators.',
            'run': _run(platform.search_search),
            'arguments': [(('target',), {'help': 'What to search for, as typed into X: words, "phrases", OR, -exclusions and operators (from: to: min_faves: filter:links lang: …)'}),
                          (('--type',), {'choices': SEARCH_TYPES, 'default': 'posts', 'help': 'posts, accounts (people) or media'}),
                          (('--sort',), {'choices': SEARCH_SORTS, 'default': 'top', 'help': 'Posts and media: top (X\'s ranking) or latest (newest first)'}),
                          (('--in',), {'choices': ['communities'], 'dest': 'within', 'help': 'communities: search posts in communities only (X\'s community search; posts, in X\'s order)'}),
                          (('--since',), {'type': day, 'metavar': 'DAY', 'help': 'First day to include, YYYY-MM-DD, in X\'s own days (this account\'s time zone)'}),
                          (('--until',), {'type': day, 'metavar': 'DAY', 'help': 'Last day to include, YYYY-MM-DD, in X\'s own days (this account\'s time zone)'}),
                          *LIST],
            'epilog': ["Results are in X's order for this account: top is a ranking, not a sample of opinion; latest is newest first. Accounts with the same or similar names are different results (compare url and their marks). --type accounts refuses --since/--until, and --in communities reads posts in X's order without --type or --sort (exit 2 otherwise).",
                       "--since/--until are sent as X's since:/until: operators (a query that already has a date operator refuses them, exit 2), so X applies the dates itself: a search read to the end (stopped=exhausted) covers its window, window ... closed (server-filtered); stopped earlier it is still open. X decides which day boundaries those operators use (measured once: until:D ran to the end of D in this account's time zone), so check created_at at the edges.",
                       'X allows about 50 searches per 15 minutes for this account (quotes count too); when it runs out the command stops with exit 10 (before any result) or stopped=rate_limited and a more: line (after some), naming when it resets.'],
            'requests': '1 per page of about 20.',
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
            'epilog': ["A trend is what X shows this account as popular now, in X's order and for X's region and language settings, not a measure of opinion or a full list; its count line is X's rounded figure. Each trend ends with search: <query>, the words search takes to read it; an event ends with its title as that query. Promoted trends (ads) are included, marked [ad], and count toward --limit; posts or accounts mixed into Explore are left out and counted."],
            'requests': '1 for foryou (its first page comes with the Explore answer, and only that page is read); 2 for the other tabs (the Explore answer names their timeline), then 1 per further page.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'images': {
            'help': 'Save the pictures of one post (a video by its poster) so they can be looked at.',
            'run': _run(platform.images_images),
            'arguments': [(('target',), {'help': 'x.com post URL or numeric id'}),
                          (('numbers',), {'nargs': '*', 'type': _positive, 'metavar': 'N',
                                          'help': 'The pictures to save, by the numbers the post shows ([image N])'}),
                          (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
            'epilog': ['The post is read again (its picture links do not last), so N is the Nth picture as X sends the post now; each saved line names its kind, size, alt text and media_id to match what the post showed. A video is saved as its poster image. A picture that could not be saved is named in coverage (exit 8); a number the post does not have is refused before any picture is fetched (exit 2). A stop between pictures (the time limit, a hold) keeps the saved ones and ends with more: naming the numbers left.'],
            'requests': '1 for the post, then 1 per picture.',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
    }


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
                       'A window keeps the dated posts written on its days (posts without a date are left out and counted). Only --tab following can close a --since window (it reads on to the first page wholly older than --since, while the feed stays newest first); foryou is a sample of the window: it keeps the posts dated inside it among the page read.',
                       'A feed entry can carry several posts (a post and a reply to it, or an author continuing a post): they are shown together, and the later ones say reply-to= or continuation of.'],
            'requests': '1 per page of about 5-10 posts.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'profile': {
            'help': 'Read a profile\'s tab: threads, replies, reposts or media.',
            'run': _run(platform.listing_profile),
            'arguments': [(('target',), {'help': 'Threads @handle or profile URL; a tab URL such as /@name/replies reads that tab'}),
                          (('--tab',), {'choices': PROFILE_TABS, 'help': 'The tab (default: the URL\'s tab, else threads)'}),
                          'since', 'until', *LIST],
            'epilog': ["threads and replies are newest first, so a --since window reads on and closes at the first page wholly older than it (a pinned post sits first whatever its date and does not close it). reposts and media are in no date order: a window covers them only when read to the end (--limit or --out, or more:). A repost carries the original post's date, not when it was reposted.",
                       'A private profile this account does not follow is unavailable (exit 9).'],
            'requests': "1 to find the profile, then 1 per page (about 10 posts on threads); the first read of the replies, reposts or media tab in a while also reads that tab's screen once to learn its query.",
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'about': {
            'help': 'Read a profile\'s card: name, bio, links, verification, privacy, follower count.',
            'run': _run(platform.about_about),
            'arguments': [(('target',), {'help': 'Threads @handle or profile URL'}), 'json'],
            'epilog': ['Threads publishes a follower count but no following or mutual count: those are shown as ? (unknown); graph following lists the accounts. A verified badge and a bio are what the account claims about itself.'],
            'requests': '2 (find the profile, read its card).',
            'exits': (0, 2, 3, 4, 5, 6, 8, 9),
        },
        'graph': {
            'help': 'Read the accounts that follow a profile, or that it follows.',
            'run': _run(platform.listing_graph),
            'arguments': [(('target',), {'help': 'Threads @handle or profile URL'}),
                          (('relation',), {'choices': GRAPH_RELATIONS, 'help': 'followers or following'}),
                          *LIST],
            'epilog': ['followers: one sample Threads sends (stopped=server_capped; stopped=not_built when Threads offers a next page this skill does not read); the coverage line gives the count the profile reports. following pages on.'],
            'requests': '1 to find the profile, then 1 per page of about 20 accounts.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'me': {
            'help': 'Read liked or saved posts, or activity notifications.',
            'run': lambda invocation: (platform.listing_notifications if invocation.options['collection'] == 'activity' else platform.listing_me)(PLATFORM, invocation),
            'check': check_me,
            'arguments': [(('collection',), {'choices': ME_COLLECTIONS, 'metavar': 'KIND', 'help': 'liked, saved or activity'}), (('--tab',), {'choices': ACTIVITY_FILTERS, 'help': 'App activity filter (default: all); requests means follow requests'}), (('--limit',), {'type': _activity_limit, 'help': 'Rows to show (activity: default 20, 1 to 50)'}), 'chars', 'after', 'out', 'json'],
            'epilog': ["liked and saved: one batch as Threads sends it (stopped=not_paginable), not your whole history. activity: one page in Threads' order (--limit 1 to 50, default 20; no --after or --out); when older activity exists, stopped=not_built and no next page is requested. --tab applies only to activity.",
                       'Reading the list sends no seen change (the app marks notifications seen only when its activity screen opens, which this skill never does); seen state as observed on 2026-10-22.'],
            'requests': '1.',
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
            'epilog': ['Reads one page in Threads\' order. If Threads says older activity exists, stopped=not_built '
                       'and the coverage line say only this page was read; no next page is requested.',
                       'Reading the list sends no seen change (the app marks notifications seen only when its activity '
                       'screen opens, which this skill never does); seen state as observed on 2026-10-22.',
                       'requests: 1.'],
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'search': {
            'help': 'Search posts, tags or accounts.',
            'run': _run(platform.search_search),
            'arguments': [(('target',), {'help': 'What to search for (a tag without #)'}),
                          (('--type',), {'choices': SEARCH_TYPES, 'default': 'posts',
                                         'help': 'posts (by words), tags (posts under a tag) or accounts (one batch of profiles)'}),
                          (('--sort',), {'choices': SEARCH_SORTS, 'default': 'top',
                                         'help': 'Posts and tags: top (Threads ranks them) or recent (newest first)'}),
                          'since', 'until',
                          (('--from',), {'metavar': 'ACCOUNT', 'help': 'Posts and tags: only posts by this @handle'}),
                          *LIST],
            'epilog': ["Results are in Threads' order for this account: top is a ranking, not a sample of opinion; recent is newest first. Accounts with the same or similar names are different results (compare url and verified); accounts are one batch, in Threads' order, and refuse --sort recent, --since, --until and --from.",
                       '--since, --until and --from are filters Threads applies itself (posts and tags), so a filtered search reads on until Threads has no more, and read to the end (stopped=exhausted) it covers its window in either order: window ... closed (server-filtered); stopped by --limit or the time limit, it is still open. The days are judged in the zone the window was made in and keep that span across more:.'],
            'requests': '1 per page of about 10 posts; accounts 1.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
            'check': check_search,
        },
        'post': {
            'help': 'Read one post in full with its parent chain and first batch of replies.',
            'run': _run(platform.thread_post),
            'arguments': [(('target',), {'help': 'Threads post URL (/@name/post/<code> or /t/<code>) or its shortcode'}),
                          (('--sort',), {'choices': REPLY_SORTS, 'default': 'top', 'help': 'Reply order: top (Threads ranks them) or recent (newest first)'}),
                          (('--limit',), {'type': _positive, 'help': 'Direct replies to show from the first batch (each with what hangs under it)'}),
                          (('--chars',), {'type': _chars, 'help': 'Characters of each parent and reply to show (default 180; 0 = all); the post itself is always shown in full'}),
                          'json'],
            'epilog': ['The post is shown in full, after the posts it answers (parent). Its first batch of direct replies follows, each with what hangs under it: replies to it (reply-to=) and the replier continuing (continuation of). A reply with more under it ends with replies <handle>, which opens that branch; more: reads the next batch of direct replies. A replies line says how many direct replies Threads reports, how many arrived and an estimate of those never received.',
                       "Every record's url opens that one post with post <url> (a reply is a post too)."],
            'requests': '3 (the post, its parents, its first replies); no screen is opened.',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 8, 9),
        },
        'replies': {
            'help': 'Read the next batch of a post\'s replies, or the replies under one reply, by the handle post printed.',
            'run': _run(platform.thread_replies),
            'arguments': [(('target',), {'help': 'The number after "replies" (a branch) or in a more: line (the next batch)'}),
                          (('--limit',), {'type': _positive, 'help': 'Replies to show; omitted: one batch, or every batch with --out. With --out it counts replies saved'}),
                          'chars', 'out', 'json'],
            'epilog': ["A handle names a batch: the next batch of a post's direct replies, or the replies under one reply (every reply that reply's own page lists, batch by batch, each with what hangs under it). Running it again reads the same batch again, live; it is not a replay. more: prints the handle of the batch after."],
            'requests': '1 per batch of about 10 replies.',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
            'check': check_replies,
        },
        'quotes': {
            'help': 'Read the posts that quote one post (one batch).',
            'run': _run(platform.listing_activity),
            'arguments': [(('target',), {'help': 'Post URL or shortcode'}), *LIST],
            'epilog': ['Each quote is its own post (role quote), shown with its author and its text as the activity list gives it; post <url> opens it with its media and replies. Threads sends one batch of up to about 100, in its own order: when it reports more (reported_total), the rest cannot be asked for (stopped=server_capped).'],
            'requests': '1.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'reposts': {
            'help': 'Read the accounts that reposted one post (one batch).',
            'run': _run(platform.listing_activity),
            'arguments': [(('target',), {'help': 'Post URL or shortcode'}), *LIST],
            'epilog': ['Each account with when it reposted. Threads sends one batch of up to about 100, in its own order: when it reports more (reported_total), the rest cannot be asked for (stopped=server_capped).'],
            'requests': '1.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'images': {
            'help': 'Save the pictures of one post (a video by its poster) so they can be looked at.',
            'run': _run(platform.images_images),
            'arguments': [(('target',), {'help': 'threads.com (or threads.net) post URL'}),
                          (('numbers',), {'nargs': '*', 'type': _positive, 'metavar': 'N',
                                          'help': 'The pictures to save, by the numbers the post shows ([image N])'}),
                          (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
            'epilog': ['The post is read again (its picture links are signed and do not last), so N is the Nth picture as Threads sends the post now; each saved line names its kind, size and media_id to match what the post showed. A video is saved as its poster image. A picture that could not be saved is named in coverage (exit 8); a number the post does not have is refused before any picture is fetched (exit 2). A stop between pictures (the time limit, a hold) keeps the saved ones and ends with more: naming the numbers left.'],
            'requests': '3 for the post (as post reads it), then 1 per picture.',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
    }


    del COMMANDS['activity']
    return COMMANDS, CHOICES


def _reddit_surface(platform):
    PLATFORM = platform.PLATFORM
    # --- the commands --------------------------------------------------------------------------------------------------

    LIST = ['limit', 'chars', 'after', 'out', 'json']
    WINDOW = ['since', 'until']
    TIME = (('--time',), {'choices': platform.web_TIMES, 'help': 'Reddit\'s period for top or controversial; not a date '
                                                        'window'})
    LISTING = ('1 per page of 100, 25 shown (--limit counts them; more: shows the rest, then reads the next page), plus '
               'the account check (/api/me.json) when the read can be continued (more:, --out) — all a more: that only '
               'shows the rest makes.')
    WINDOWS = ('--since/--until need sort new (their default; another --sort is exit 2) and stop at the first post more '
               'than ten minutes older than --since (Reddit\'s new order can be a minute off); a listing ending first is '
               'partial (8).')


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
                                                                            'or controversial with --time'}), TIME, *WINDOW, *LIST],
            'epilog': ["The home feed is Reddit's choice for this account (its subscriptions and what it ranks), not Reddit as a whole. best and hot never end by themselves: --out needs --limit there.",
                       WINDOWS],
            'requests': LISTING,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'sub': {
            'help': 'Read a community\'s or custom feed\'s listing (r/name, r/a+b, r/popular, r/all, m/name).',
            'run': _command(platform.listing_sub), 'check': platform.listing_window_check,
            'arguments': [(('target',), {'help': 'r/<name>, a community URL, r/<a+b> for several, m/<name> (your custom '
                                                 'feed) or u/<user>/m/<name>'}),
                          (('--sort',), {'choices': platform.web_SUB_SORTS, 'help': 'hot (default), new (newest first), top or '
                                                                           'controversial (with --time), rising'}),
                          TIME, *WINDOW, *LIST],
            'epilog': ["r/popular and r/all are Reddit-wide rankings; a custom feed gathers its communities. Pinned posts (often old) top hot; under new they sit at their own date. A private, quarantined or banned community, or another's private feed: unavailable (exit 9).",
                       WINDOWS],
            'requests': LISTING,
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
            'epilog': ["An account can hide its history, or some communities, from others, so what is shown may leave things out.",
                       "An empty first page (no --after, --time, --since or --until) is checked against the account's karma for that kind (one more request): karma means a history hidden or deleted (exit 9, history_not_visible), none an empty one (7), as is a filtered empty result.",
                       WINDOWS],
            'requests': LISTING,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'about': {
            'help': 'Read a community\'s card and rules, or a user\'s card.',
            'run': _command(platform.about_about),
            'arguments': [(('target',), {'help': 'r/<name> or u/<name> (or their URLs); a bare word is refused'}),
                          'chars', 'json'],
            'epilog': ["A community: name, title, short description, sidebar, subscribers, active users, age, access type (public, restricted, private) and NSFW, then its rules, its moderators and its pinned posts (moderators' announcements and megathreads, which can gather a topic the listing then shows less of). A user: karma by kind, account age, profile description, and the moderator, admin and verified markers. Karma, age and flair say what an account did on Reddit, not who the person is."],
            'requests': '4 for a community (card, rules, moderators, the first page of hot for its pinned posts), 1 for a user; no account check (one live read tied to no handle or file).',
            'exits': (0, 2, 3, 4, 5, 6, 9, 10),
        },
        'wiki': {
            'help': 'Read a community\'s wiki: one page in full, or its page list.',
            'run': _command(platform.wiki_wiki),
            'arguments': [(('target',), {'help': 'r/<name>, or a wiki URL (https://www.reddit.com/r/<name>/wiki/<page>)'}),
                          (('page',), {'nargs': '?', 'help': 'The page (default index; names such as faq or faq/start)'}),
                          (('--pages',), {'action': 'store_true', 'help': 'List the wiki\'s pages instead of reading one'}),
                          (('--chars',), {'type': count, 'help': 'Characters of the page to show (default: all)'}), 'json'],
            'epilog': ["A wiki page is what its community's moderators wrote and revised (when, by whom and why are on its first line): often a FAQ, rules in detail, or recommended resources. The page list keeps settings pages (config/..., the sidebar and rules text) apart. A page that does not exist, or a wiki that is off or private, is unavailable (exit 9).",
                       "Wiki pages count in Reddit's own wiki bucket, not the one listings and threads use; the first line shows its window as wiki."],
            'requests': '1; no account check (one live read tied to no handle or file).',
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
                          (('--sort',), {'choices': platform.web_SEARCH_SORTS, 'help': 'relevance (default); new is newest first, '
                                                                              'comments most commented'}),
                          TIME,
                          (('--nsfw',), {'action': 'store_true', 'help': 'Include posts marked over 18 (otherwise Reddit '
                                                                         'leaves most out)'}),
                          *WINDOW, *LIST],
            'epilog': ['Reddit matches loosely (several words find posts with any of them). Operators inside TEXT: "exact phrase", subreddit:NAME, author:NAME, title:WORD, self:yes (text posts), site:DOMAIN, flair:NAME; url:TEXT matches loosely. Comments cannot be searched here.',
                       "Results are Reddit's ranking, not a sample; empty means nothing matched in Reddit's index, not that nobody discussed it.",
                       WINDOWS],
            'requests': LISTING,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'related': {
            'help': 'Read the other discussions of the same link (crossposts and duplicates).',
            'run': _command(platform.listing_related),
            'arguments': [(('target',), {'help': 'A post URL or id (a comment link reads its post)'}),
                          *LIST],
            'epilog': ["Each other post of the same link, in other communities or the same one: one link's discussion is often split across communities that react differently. Exit 7 when there is none."],
            'requests': LISTING,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'me': {
            'help': 'Read your own subscriptions, saved, upvoted, downvoted or hidden items, or the replies and mentions others sent you.',
            'run': _command(platform.listing_me),
            'arguments': [(('collection',), {'choices': platform.web_ME_COLLECTIONS, 'help': 'subs (subscribed communities), saved, '
                                                                                    'upvoted, downvoted, hidden, comment-replies (replies to '
                                                                                    'your comments), post-replies (replies '
                                                                                    'to your posts) or mentions (of your '
                                                                                    'name)'}), *LIST],
            'epilog': ['Lists of the Reddit account the Aside browser is logged in to (the account check names it). saved and upvoted hold posts and comments, newest saved or upvoted first; downvoted and hidden also hold posts and comments. comment-replies, post-replies and mentions are what other accounts sent you, newest first; reading them never marks them read (unread says which are still new). Private messages are not read.'],
            'requests': LISTING,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
        },
        'post': {
            'help': 'Read one post in full and the first batch of its comments.',
            'run': _command(platform.thread_post),
            'arguments': [(('target',), {'help': 'A post URL, id or redd.it link; a comment link opens the '
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
            'epilog': ['The post is shown in full. Reddit sends up to 500 of its comments, 10 levels deep, in one answer; the rest are gaps. The first batch is shown depth-first within --depth, each [c] line naming the comment it answers (reply-to=); the thread: line counts what Reddit reports (deleted and removed included), what arrived, is shown, is deeper than --depth and is left to expand. more: continues it as a comments command while comments within --depth remain. The first line counts the post and context rows with the comments.',
                       "The sort is the order inside each batch, not across batches. A thread's suggested sort and contest mode (random order, hidden scores) are on the thread: line. comments <a comment's permalink> opens it in full with what hangs under it."],
            'requests': 'the account check (/api/me.json) + 1 (a share link adds 1 per redirect, at most 3).',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 8, 9, 10),
        },
        'comments': {
            'help': 'Read the next batch of a thread, or one comment in full with what hangs under it.',
            'run': _command(platform.thread_comments),
            'arguments': [(('target',), {'help': 'A post URL (its next batch) or a comment\'s permalink (that comment with its ancestors and what hangs under it)'}),
                          (('--sort',), {'choices': platform.web_COMMENT_SORTS, 'help': 'Comment order (default best); a reading '
                                                                               'keeps its order'}),
                          (('--limit',), {'type': positive, 'help': 'Comments to show (default 25); with --out, comments to '
                                                               'save'}),
                          (('--depth',), {'type': count, 'help': 'Reply levels to show (default 2), counted from the linked '
                                                               'comment for a comment link'}),
                          'chars', 'after', 'out', 'json'],
            'epilog': ['A batch is shown from the snapshot the last post or comments read left (for a day), with no request while it holds unshown comments; then the next gaps are expanded (up to 100 comment ids in one request; a "continue this thread" branch, one request each). A comment Reddit lists but never sends when asked is counted as never sent (deleted or removed). more: is offered while comments within --depth remain; deeper ones, and branches Reddit sent nothing for, are coverage notes (a larger --depth shows the first).',
                       'A comment link is answered from the latest snapshot of its post when it holds that comment; otherwise its subtree is read (1 request).',
                       '--out writes the whole thread: the post once, then every comment flat (parent_id, depth), a page per expansion; the same command resumes it even after its snapshot expired. Branches Reddit will not expand end it partial (8).'],
            'requests': 'the account check (/api/me.json) + 1 per expansion (or 1 for a new read); the time limit stops a large thread and more: continues.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        },
        'images': {
            'help': 'Save the pictures of one post (a gallery, an image post, a video\'s preview) so they can be looked at.',
            'run': _command(platform.images_images),
            'arguments': [(('target',), {'help': 'A post URL, id or redd.it link (a comment link or a '
                                                                   'share link opens its post)'}),
                          (('numbers',), {'nargs': '*', 'type': positive, 'metavar': 'N',
                                          'help': 'The pictures to save, by the numbers the post shows (media N:)'}),
                          (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
            'epilog': ["The post is read again (preview links expire), so N is the Nth picture as Reddit sends it now; each saved line names its kind, size and media_id to match the post. Only Reddit's image hosts (i.redd.it, preview.redd.it) are fetched; a picture elsewhere is named and skipped. One that could not be saved is named in coverage (exit 8); a number the post lacks is refused before any fetch (exit 2). A stop between pictures keeps the saved ones; more: names the numbers left."],
            'requests': "1 for the post (plus a share link's hops), then 1 per picture.",
            'more': True,
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
    FEED_TABS = ['all', 'favorites', 'friends', 'groups', 'pages']
    GROUP_SORTS = ['top', 'recent', 'activity']
    COMMENT_SORTS = ['all', 'relevant', 'newest']
    SEARCH_TYPES = ['top', 'posts', 'people', 'pages', 'groups', 'videos']
    ME_KINDS = ['notifications', 'saved', 'groups']
    PROFILE_TABS = ['posts', 'photos']
    GRAPH_RELATIONS = ['followers', 'friends']
    GROUP_TABS = ['posts', 'members']

    CHOICES = {'feed.sort': FEED_SORTS, 'feed.tab': FEED_TABS, 'profile.tab': PROFILE_TABS, 'graph.relation': GRAPH_RELATIONS,
               'group.tab': GROUP_TABS, 'group.sort': GROUP_SORTS, 'post.sort': COMMENT_SORTS, 'comments.sort': COMMENT_SORTS,
               'search.type': SEARCH_TYPES}


    LIST = ['limit', 'chars', 'after', 'out', 'json']


    def check_replies(options):
        if not (options['target'].isascii() and options['target'].isdigit()):
            raise SnsError('argument', 'A replies handle is the number printed after "replies".',
                           'Copy the whole replies line.')


    def check_graph(options):
        if options['relation'] == 'friends' and options.get('target'):
            raise SnsError('argument', 'Only your own friends list is read: another account\'s Friends tab was not '
                                       'observed.', 'Drop the account: graph friends.')
        if options['relation'] == 'followers' and not options.get('target'):
            raise SnsError('argument', 'followers needs the profile or page whose followers to read.',
                           'Pass it: graph ACCOUNT followers.')


    def check_group(options):
        if options['tab'] != 'posts' and (options.get('sort') or options.get('since') or options.get('until')):
            raise SnsError('argument', '--sort, --since and --until are for the posts tab.',
                           'Drop them, or read --tab posts.')


    def check_profile(options):
        if options['tab'] != 'posts' and (options.get('since') or options.get('until')):
            raise SnsError('argument', '--since and --until are for the posts tab.', 'Drop them, or read --tab posts.')


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
            'arguments': [(('--tab',), {'choices': FEED_TABS, 'default': 'all', 'help': 'all (default) or a filter, newest first'}),
                          (('--sort',), {'choices': FEED_SORTS, 'help': 'top: the order Facebook ranks; recent: newest first'}),
                          'since', 'until',
                          *LIST],
            'epilog': ['The feed is what Facebook chose to show this account, not everything its friends and pages posted. Ads are included, marked [ad], and count toward --limit.',
                       "top is Facebook's ranking: a --since window keeps dated posts inside it among those read (a sample). recent and filters are newest first: a window closes at the first page with a dated, unpinned post older than --since; a feed that ends before --since is partial, because Facebook shows no older posts here. An undated post is left out and counted. The top feed never ends by itself, so --out needs --limit."],
            'requests': '1 per page of about 5-10 posts.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'profile': {
            'help': 'Read a profile\'s or page\'s timeline or photos.',
            'run': _run(platform.screens_profile),
            'arguments': [(('target',), {'help': 'Profile or page URL, vanity name or numeric id'}),
                          (('--tab',), {'choices': PROFILE_TABS, 'default': 'posts', 'help': 'posts (the timeline) or photos'}),
                          'since', 'until', *LIST],
            'epilog': ["--since/--until (posts only) are applied by Facebook (server-filtered) and checked against each post's date again; a window reads on until it ends, and reading to the end closes it. A post with no date cannot be placed in a window and is left out and counted; a pinned post is judged by its date like the others.",
                       'A timeline can hold posts by other people (posts on the timeline, shares); each record names its author.',
                       "photos: the tab's first page as its screen loads it (stopped=not_built when Facebook says more follow); post <url> opens one."],
            'requests': '1 to find the numeric id (none for a numeric id), then 1 per page of about 3-5 posts; photos: 1.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
            'check': check_profile,
        },
        'graph': {
            'help': 'Read a profile\'s or page\'s followers, or your own friends.',
            'run': _run(platform.screens_graph),
            'arguments': [(('target',), {'nargs': '?', 'help': 'Profile or page URL, vanity name or numeric id; omitted for friends'}),
                          (('relation',), {'choices': GRAPH_RELATIONS, 'metavar': 'RELATION', 'help': 'followers (of ACCOUNT) or friends (your own)'}),
                          *LIST],
            'epilog': ["The first page the Followers tab or your Friends list loads, in Facebook's order; when Facebook says more follow it ends with stopped=not_built (that request was not observed)."],
            'requests': '1.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
            'check': check_graph,
        },
        'group': {
            'help': 'Read a group\'s posts or new members.',
            'run': _run(platform.screens_group),
            'arguments': [(('target',), {'help': 'Group URL, vanity name or numeric id'}),
                          (('--tab',), {'choices': GROUP_TABS, 'default': 'posts', 'help': 'posts or members (its new members)'}),
                          (('--sort',), {'choices': GROUP_SORTS, 'help': 'posts: top (default) and activity are ranked; recent: newest posts first'}),
                          'since', 'until', *LIST],
            'epilog': ["With --since, only --sort recent can close the window (a group's oldest post ends it), and it reads on until it does; top and activity are samples of it. A post with no date cannot be placed in a window and is left out and counted.",
                       "members: the new members section only (not the tab's other buckets), as its screen loads it (stopped=not_built when Facebook says more follow); --sort and the window are for posts."],
            'requests': '1 to find the numeric id (none for a numeric id), then 1 per page of about 3-5 posts; members: 1.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
            'check': check_group,
        },
        'post': {
            'help': 'Read one post in full with its first parent comments.',
            'run': _run(platform.thread_post),
            'arguments': [(('target',), {'help': 'Facebook post permalink (posts/, permalink.php, story.php, photo, videos/, groups/…/posts/)'}),
                          (('--sort',), {'choices': COMMENT_SORTS, 'default': 'all', 'help': 'Comment order: all (ranked, nothing filtered out), relevant (Facebook\'s "most relevant", which can leave comments out), newest'}),
                          (('--limit',), {'type': _positive, 'help': 'Parent comments to show from the first batch'}),
                          (('--chars',), {'type': _chars, 'help': 'Characters of each comment to show (default 180; 0 = all); the post text is always shown in full; --json keeps all'}),
                          'json'],
            'epilog': ['The post text is shown in full. Each comment with replies ends with replies <handle>; more: continues the parent comments as a comments command. Share links (/share/, /reel/, /watch/, fb.watch) are not read: open the post in the browser and copy its own permalink.'],
            'requests': '3 (the page, to find the story; the post; the first comments).',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 8, 9),
        },
        'comments': {
            'help': 'Read a post\'s parent comments, page by page.',
            'run': _run(platform.thread_comments),
            'arguments': [(('target',), {'help': 'Facebook post permalink'}),
                          (('--sort',), {'choices': COMMENT_SORTS, 'default': 'all', 'help': 'all (ranked, nothing filtered out), relevant (can leave comments out), newest'}),
                          (('--limit',), {'type': _positive, 'help': 'Parent comments to show; omitted: one page (about 10), or every page with --out. With --out it counts parents saved'}),
                          *[option for option in LIST if option != 'limit']],
            'epilog': ['Replies are not expanded here: each comment with replies ends with replies <handle>, which reads that branch. One page is about 10 comments.'],
            'requests': '2 to find the post (none when continuing with --after), then 1 per page of about 10 comments.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'replies': {
            'help': 'Read one batch of replies under a comment, by the handle post or comments printed.',
            'run': _run(platform.thread_replies),
            'arguments': [(('target',), {'help': 'The number after "replies" on a comment or reply'}),
                          (('--limit',), {'type': _positive, 'help': 'Replies to show; omitted: one batch (about 10), or every batch with --out. With --out it counts replies saved'}),
                          'chars', 'out', 'json'],
            'epilog': ["A handle names a batch: the first batch of a comment's replies, or the batch after one already shown (more: prints that one). It is not used up: running it again reads the same batch again, live.",
                       "Each reply that has replies of its own ends with replies <handle>, which reads that deeper branch. Facebook's reply count includes those deeper replies.",
                       "A deeper branch (the replies under a reply, Facebook's last level) is read as one batch: the next-batch request this skill knows brings the same replies again, so it ends with stopped=not_built (Facebook may have more) and a coverage line counting what was not sent. Each of its replies names the comment it answers as its parent, which can be the top comment or another reply in the branch."],
            'requests': '1 per batch of about 10 replies.',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
            'check': check_replies,
        },
        'search': {
            'help': 'Search posts, people, pages, groups or videos.',
            'run': _run(platform.search_search),
            'arguments': [(('target',), {'help': 'What to search for'}),
                          (('--type',), {'choices': SEARCH_TYPES, 'default': 'top', 'help': 'top mixes posts with people, pages and groups in Facebook\'s order'}),
                          (('--recent',), {'action': 'store_true', 'help': 'Posts only (top, posts): Facebook\'s "recent posts" filter'}),
                          'since', 'until',
                          (('--in',), {'dest': 'within', 'metavar': 'GROUP', 'help': 'Search the posts of one group (its URL, vanity name or numeric id), as the group\'s own search box does'}),
                          *LIST],
            'epilog': ["Results are in Facebook's order for this account; people and pages with the same name are different results (compare url and verified). One page is about 5 results.",
                       "--recent, --since, --until and --in are for posts (--type top or posts; exit 2 otherwise). --recent, --since and --until are Facebook's post filters: Facebook applies the dates, so reaching the end closes the window as far as search returns posts; results stay in Facebook's order, not by date. A result with no date cannot be placed in a window and is left out and counted. --in searches one group's posts, as the group's own search box does.",
                       "videos: the first page of the videos search screen (video posts; stopped=not_built when Facebook says more follow)."],
            'requests': '1 per page of about 5 results; --in first finds the group id (1, none for a numeric id); videos: 1.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
            'check': check_search,
        },
        'about': {
            'help': 'Read a profile\'s or page\'s visible About fields, or a group\'s card.',
            'run': _run(platform.about_about),
            'arguments': [(('target',), {'help': 'Profile or page URL, vanity name or numeric id; or a group by its /groups/ URL'}),
                          (('--section',), {'help': 'Only this locale-independent section, e.g. directory_work (schema about lists them as they appear)'}),
                          'json'],
            'epilog': ["What About shows depends on the viewing account and the owner's privacy settings. Fields are never cut.",
                       "A group URL gives the group's card instead: name, privacy as Facebook labels and explains it, the member total as Facebook writes it, the viewing account's relation to the group, whether joining asks questions, the description, recent activity, creation date and the rules in order."],
            'requests': '1 to find the numeric id (none for a numeric id), 1 for the overview, then 1 per About tab (--section stops at the first tab that shows it); a group: 1 to find the id (none for a numeric /groups/<id>/), then 2 (header and About).',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'images': {
            'help': 'Save the pictures of one post (a video by its poster) so they can be looked at.',
            'run': _run(platform.images_images),
            'arguments': [(('target',), {'help': 'Post permalink URL'}),
                          (('numbers',), {'nargs': '*', 'type': _positive, 'metavar': 'N',
                                          'help': 'The pictures to save, by the numbers the post shows ([image N])'}),
                          (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
            'epilog': ['The post is read again (its picture links are signed and do not last), so N is the Nth picture as Facebook sends the post now; each saved line names its kind, size and media_id to match what the post showed. A video is saved as its poster image. A picture that could not be saved is named in coverage (exit 8); a number the post does not have is refused before any picture is fetched (exit 2). A stop between pictures (the time limit, a hold) keeps the saved ones and ends with more: naming the numbers left.'],
            'requests': '2 for the post (its page, then the post), then 1 per picture.',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'notifications': {
            'help': 'Read your notifications (none marked seen), saved items or joined groups.',
            'run': _run(platform.screens_me),
            'arguments': [*LIST],
            'epilog': ["The notifications of the account the tab is logged in to, in Facebook's order, each with unseen, seen or read and url: what it points at (post <url> opens a post). Bucket headers and the see-previous button are layout and are left out.",
                       'Reading the list sends no seen or read change (those are separate requests this skill never sends): reading the first page and an older one, the unseen count stayed as it was (2026-11-16). If Facebook stops accepting a stored notifications query the command ends with exit 6 and does not open the notifications screen to relearn it, because opening that screen is what makes the app mark notifications seen.',
                       'Older notifications come with the query the screen\'s see previous button sends: about 15 first, then 10 a page.',
                       "saved and groups (the groups you joined): only the first page their screens load, in Facebook's order; when Facebook says more follow, stopped=not_built and a coverage line instead of more:. A saved item's url is its own address."],
            'requests': '1 per page.',
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
    }

    CHOICES['me.collection'] = ME_KINDS
    COMMANDS['me'] = COMMANDS.pop('notifications')
    COMMANDS['me']['arguments'].insert(0, (('collection',), {'choices': ME_KINDS, 'metavar': 'KIND', 'help': 'notifications, saved or groups'}))
    return COMMANDS, CHOICES


def _naver_blog_surface(platform):
    PLATFORM = platform.PLATFORM
    # --- the commands --------------------------------------------------------------------------------------------------

    ACCOUNT = ('The account check (current-user, 1) comes first past one screen (a --limit above the default, a window), '
               'for --out and --after; a one-screen more: carries the account seen in the last 12 hours, a hint that '
               'continuing checks.')
    PAGE = 'more: shows the rest of a page (no request) before reading the next.'


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
                                                                                'query, unquoted'}),
                          (('--type',), {'choices': ['posts', 'blogs', 'tags', 'clips'], 'default': None,
                                         'help': 'posts (default), blogs, tags (posts under an exact tag) or clips '
                                                 '(short videos)'}),
                          (('--in',), {'dest': 'within', 'metavar': 'BLOG', 'help': 'Search inside one blog (id, URL or naver.me link)'}),
                          (('--sort',), {'choices': ['relevance', 'date'], 'help': 'relevance (default) or date (newest first); posts, '
                                                                             'blogs and clips'}),
                          'since', 'until',
                          (('--own-money',), {'action': 'store_true', 'help': 'Naver-wide post search: only posts with Naver\'s '
                                                                              '내돈내산 인증 card, a purchase or visit Naver '
                                                                              'recorded (not the word in a title or tag)'}),
                          'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ["What each search takes (others are refused before any request): posts — --sort, --since/--until (Naver filters by KST day), --own-money; blogs — --sort; tags — --since/--until, applied here (tags are newest first, so the window closes); --in posts — --sort and dates; --in tags — neither, whole tags only. Relevance is Naver's ranking for this account, not a sample.",
                       'Naver serves at most 1,000 results of any search: the read ends there (stopped=server_capped, a natural end a coverage line names); narrow the words or dates to reach further. A tag result carries no blog name.',
                       '--limit counts records. One page is 30 posts or tags, or 20 blogs, clips or in-blog posts, and 10 are shown. ' + PAGE],
            'requests': '1 per page (+1 for a --in domain address). ' + ACCOUNT,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'keywords': {
            'help': 'Naver Blog\'s popular searches of the day, or the searches related to one keyword.',
            'run': _command(platform.search_keywords),
            'arguments': [(('text',), {'nargs': '*', 'metavar': 'TEXT', 'help': 'A keyword for its related searches; '
                                                                                'omitted: the popular ones'}), 'json'],
            'epilog': ["Popular: about 12 keywords and the day Naver computed them; related: about 15 keywords. Both are Naver's own order — a ranking, not a share of searches or of opinion. search <keyword> reads one."],
            'requests': '1.',
            'exits': (0, 2, 3, 4, 5, 6, 7),
        },
        'post': {
            'help': 'Read one post in full: body, pictures, links, tags, reactions, same-category posts.',
            'run': _command(platform.post_post),
            'arguments': [(('target',), {'help': 'Post URL (blog.naver.com or m.blog.naver.com), '
                                                                    'blogId/logNo, or a naver.me link to a post'}),
                          (('--comments',), {'action': 'store_true', 'help': 'Also read the first page of comments (10 '
                                                                             'comments with their replies; one request)'}),
                          'chars', (('--out',), {'metavar': 'FILE', 'help': 'Save the post, its sections and its comments '
                                                                           'as NDJSON (written only when every section was read)'}),
                          'json'],
            'epilog': ['The body is never clipped. Its label says how much was read: text[full], text[partial: k of n components reduced] (those blocks gave up only their text and pictures) or text[legacy]. Pictures are numbered in place ([image N: caption], [sticker: image N]); images <post> N saves one. links: lists every outbound link with its host and, for commission or marketing hosts, its id.',
                       "Naver 내돈내산 인증 card: a purchase or visit Naver recorded (shopping order, reservation, receipt, payment) that the writer attached — it proves a recorded purchase, not who paid; words in a title or tag are not it. likes is the live count of the post's reactions; list surfaces can lag it.",
                       'Sections: the post, then same category posts and comments (--json holds them as sections, schema post_read). A deleted, private or neighbors-only post answers the same way (exit 9); a failed section is shown beside the others and makes the exit 8. The post page names the logged-in account for free (kept as a hint); if it is not the account this command started with (--out checks it first), the command ends as a changed login (exit 4).'],
            'requests': '3 (the page, its reactions, the same-category posts), +1 with --comments (+1 when the blog number is unknown), +1 for a naver.me link, +1 with --out for the account check.',
            'exits': (0, 2, 3, 4, 5, 6, 8, 9),
        },
        'comments': {
            'help': 'Read a post\'s comments and replies, newest first, replies under their parent.',
            'run': _command(platform.post_comments),
            'arguments': [(('target',), {'help': 'Post URL, blogId/logNo, or a naver.me link'}),
                          'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ["Comments come newest first; each comment's replies follow it, oldest first, indented (reply-to=#n). A reply whose parent is on another page says (parent not shown). blog: <id> on a comment is the commenter's blog. A coverage line gives Naver's own count of comments, replies, deleted and blinded ones.",
                       '--limit counts rows (comments and replies together). One page is up to 100 rows, and 20 are shown. ' + PAGE],
            'requests': '1 to find the blog number (a continuation carries it), then 1 per 100 rows. ' + ACCOUNT,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'images': {
            'help': 'Save a post\'s pictures by their numbers so they can be looked at (Read the printed path).',
            'run': _command(platform.images_images),
            'arguments': [(('target',), {'help': 'Post URL, blogId/logNo, or a naver.me link'}),
                          (('numbers',), {'nargs': '*', 'type': positive, 'metavar': 'N', 'help': 'Picture numbers as '
                                                                                              'post shows them ([image N])'}),
                          (('--all',), {'action': 'store_true', 'help': 'Every picture of the post (stickers, cards and '
                                                                        'maps included)'}), 'json'],
            'epilog': ['A picture can say what the text does not: prices on a menu, a disclosure drawn into a photo or a sticker. The post is read again and each picture saved, one line per picture with its path to Read; the files are removed once a day old.',
                       'A picture that cannot be saved (gone, over 10 MB, hosted outside Naver, not a picture) is named and skipped, the rest are saved (exit 8). A stop (the time limit, a hold) ends with more: naming the numbers left.'],
            'requests': '1 for the post, then 1 per picture.',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'resolve': {
            'help': 'Show where naver.me short links lead, without following them.',
            'run': _command(platform.post_resolve),
            'arguments': [(('target',), {'nargs': '+', 'help': 'naver.me/<code> links (as post\'s '
                                                                                   'links: block prints them)'}),
                          'json'],
            'epilog': ["Each link is read once and its redirect reported, never followed: the destination with its host and, for commission or marketing hosts (brandconnect.naver.com is a creator's shopping-connect link), its id; a Naver Blog post destination is named as post takes it.",
                       'Any number of links is read. When the time limit or a hold interrupts, the links not yet read go on in the more: command, which names them.'],
            'requests': '1 per link.',
            'more': True,
            'exits': (0, 2, 3, 4, 5, 6, 8),
        },
        'about': {
            'help': 'Read a blog\'s card, post and clip counts, category tree, notices and popular posts.',
            'run': _command(platform.blog_blog),
            'arguments': [(('target',), {'help': 'Blog id, blog URL (a post URL names its blog), or a '
                                                                    'naver.me link'}),
                          (('--brief',), {'action': 'store_true', 'help': 'Card, counts and categories only (3 requests)'}),
                          'chars', 'json'],
            'epilog': ["The card: name, nickname, description, neighbor count, visitors today and in total, posts and clips, the viewer's relation (neighbor or mutual-neighbor), official/market/power-blog marks. Categories are the tree ([n] name · posts; closed ones are counted, not listed). Popular posts are the only surface with view counts. A domain address is resolved once to the blog's own id.",
                       'Sections: the card, categories, notices and popular; a failed section is shown and makes the exit 8.'],
            'requests': '5 (card, counts, categories, notices, popular); --brief 3; +1 for a domain address or a naver.me link.',
            'exits': (0, 2, 3, 4, 5, 6, 8, 9),
        },
        'profile': {
            'help': 'List one blog\'s posts newest first: all, one category, its notices or its popular posts.',
            'run': _command(platform.blog_posts), 'check': platform.blog_check,
            'arguments': [(('target',), {'help': 'Blog id, blog URL (a PostList URL\'s categoryNo counts '
                                                                    'as --category), or a naver.me link'}),
                          (('--category',), {'metavar': 'N|NAME', 'help': 'A category number (free) or name (one request: '
                                                                          'exact match first, then part of a name)'}),
                          (('--tab',), {'choices': ['posts', 'popular', 'notices'], 'default': 'posts', 'help': 'The posts, popular posts (one page, with view counts), or notice posts (one page)'}),
                          'since', 'until', 'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ['The list is newest first, so --since closes it at the first post older than that day. Naver reports no total here. Popular and notices are one page each: no window, file or more:.',
                       '--limit counts posts. One page is 30, and 10 are shown. ' + PAGE],
            'requests': '1 per page of 30 (+1 for a category name, a domain address or a naver.me link). ' + ACCOUNT,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'feed': {
            'help': 'Read the logged-in account\'s neighbor feed (이웃새글), newest first, a page at a time.',
            'run': _command(platform.neighbors_feed),
            'arguments': [(('--group',), {'type': positive, 'metavar': 'N', 'help': 'Only one neighbor group (me '
                                                                                   'groups lists them)'}),
                          'since', 'until', 'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ["Only the blogs this account follows, newest first, so --since closes at the first post older than that day. A coverage line gives Naver's count of feed posts.",
                       '--limit counts posts. One page is 20, and 10 are shown. ' + PAGE],
            'requests': "1 per page of 20, after the account check (current-user, 1: the feed is addressed by the logged-in account's blog id, so it is always asked, and a continuation asks again).",
            'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        },
        'graph': {
            'help': 'Read the logged-in account\'s neighbor list, or a blog\'s public one.',
            'run': _command(platform.neighbors_buddies), 'check': platform.neighbors_check,
            'arguments': [(('target',), {'nargs': '?', 'help': 'A blog id or URL for its public neighbor '
                                                                                  'list; omitted: your own neighbors'}),
                          (('relation',), {'choices': ['buddies', 'followers'], 'metavar': 'RELATION', 'help': 'buddies or followers'}),
                          (('--group',), {'type': positive, 'metavar': 'N', 'help': 'Only your neighbors in one group'}),
                          'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ["followers and --group read your own account and take no blog. Your own list (20 a page) carries mutual (서로이웃) and your groups; a blog's public list (50 a page) is private by default, so an empty one (exit 7) does not mean no neighbors — about <id> shows the card's count.",
                       '--limit counts neighbors; 20 are shown. ' + PAGE],
            'requests': "1 per page; your own lists ask the account first (current-user, 1), a blog's public list does not.",
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'topic': {
            'help': 'Browse the topic directory, or one topic\'s newest or featured posts.',
            'run': _command(platform.directory_topic), 'check': platform.directory_check,
            'arguments': [(('target',), {'nargs': '?', 'help': 'Topic number (free) or name (one '
                                                                                   'request); omitted: the directory'}),
                          (('--tab',), {'choices': ['newest', 'featured'], 'default': 'newest', 'help': 'The topic\'s newest or featured posts (one page)'}),
                          'since', 'until', 'limit', 'chars', 'after', 'out', 'json'],
            'epilog': ["A topic's posts are the ones Naver files under it, newest first (a window closes on them), up to 1,000 (then stopped=server_capped, a natural end). The directory and featured posts are one page each: no window, file or more:.",
                       '--limit counts posts. One page is 10, all shown. ' + PAGE],
            'requests': '1 per page of 10 (+1 for a topic name). ' + ACCOUNT,
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
        'monthly': {
            'help': 'Read the blogs of the month: an issue\'s topics, blogs and representative posts.',
            'run': _command(platform.directory_monthly), 'check': platform.directory_check_monthly,
            'arguments': [(('--year',), {'type': positive, 'help': 'Issue year (with --month); omitted: the latest issue'}),
                          (('--month',), {'type': positive, 'help': 'Issue month 1-12 (with --year)'}), 'chars', 'json'],
            'epilog': ['A coverage line names the issue shown. A month with no issue (the current one before it is published) is exit 9 naming the latest, never silently swapped for it. One section per topic lists its blogs, each followed by its first representative posts.'],
            'requests': "4 (the issue list, the issue, the blogs' cards, their posts).",
            'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
        },
    }

    COMMANDS['me'] = {**COMMANDS['graph'], 'help': 'Read your neighbor groups or your 내소식 (news from neighbors).', 'arguments': [(('collection',), {'choices': ['groups', 'news'], 'metavar': 'KIND', 'help': 'groups or news'}), 'limit', 'chars', 'after', 'out', 'json'], 'epilog': ['groups reads your neighbor groups in one page; it takes no --limit, --after or --out.', 'news reads your 내소식: replies to your comments, comments on your posts and other news from neighbors, newest first, 5 a page. Reading marks nothing read: isRead was unchanged after reads on 2026-11-16. The next page is built from the first page\'s fields (lastMessageTimeKey, hasNext) and was not observed with data.'], 'requests': '1 per page after the account check (current-user, 1).', 'more': True}

    # The closed sets the commands offer (cli.py checks its parser's choices against this).
    CHOICES = {'search.type': ['posts', 'blogs', 'tags', 'clips'], 'search.sort': ['relevance', 'date'], 'profile.tab': ['posts', 'popular', 'notices'], 'graph.relation': ['buddies', 'followers'], 'me.collection': ['groups', 'news'], 'topic.tab': ['newest', 'featured']}

    return COMMANDS, CHOICES


# Which kinds of a platform's own links (what its locate() names) each command that takes a link reads; a link of
# another kind ends before the browser with the command that reads it. A command not listed takes no link of its own
# platform's kinds to refuse (search words, handles), and a short link whose kind shows only later (naver.me) passes.
LINKS = {
    'x': {'post': {'post'}, 'reposts': {'post'}, 'quotes': {'post'}, 'images': {'post'}, 'profile': {'profile'},
          'about': {'profile', 'about'}, 'graph': {'profile'}, 'list': {'list'}, 'community': {'community'}},
    'threads': {'post': {'post'}, 'quotes': {'post'}, 'reposts': {'post'}, 'images': {'post'},
                'profile': {'profile'}, 'about': {'profile'}, 'graph': {'profile'}},
    'reddit': {'post': {'post'}, 'comments': {'post'}, 'images': {'post'}, 'related': {'post'}, 'sub': {'sub'},
               'about': {'sub', 'profile'}, 'profile': {'profile'}, 'wiki': {'wiki', 'sub'}},
    'facebook': {'post': {'post'}, 'comments': {'post'}, 'images': {'post'}, 'profile': {'profile'}, 'graph': {'profile'},
                 'about': {'profile', 'group'}, 'group': {'group'}},
    'naver-blog': {'post': {'post'}, 'comments': {'post'}, 'images': {'post'}, 'about': {'about', 'profile', 'post'},
                   'profile': {'about', 'profile'}, 'graph': {'about', 'profile', 'post'}},
}


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


# What a positional argument is called in help, one word per kind of thing across platforms (plan '목표 문법': ACCOUNT,
# POST, the place's own name, HANDLE for numbered handles): the one owner of these labels; the tables leave them out.
POSITIONAL_LABELS = {'target': {'profile': 'ACCOUNT', 'about': 'ACCOUNT', 'graph': 'ACCOUNT', 'sub': 'SUB', 'wiki': 'SUB',
                                'group': 'GROUP', 'list': 'LIST', 'community': 'COMMUNITY', 'post': 'POST',
                                'comments': 'POST', 'related': 'POST', 'images': 'POST', 'reposts': 'POST',
                                'quotes': 'POST', 'replies': 'HANDLE', 'search': 'TEXT', 'topic': 'TEXT',
                                'resolve': 'TEXT'},
                     'page': 'PAGE', 'collection': 'KIND', 'relation': 'RELATION'}


def label(word, command, dest):
    """The help label of a positional argument."""
    found = POSITIONAL_LABELS[dest]
    if not isinstance(found, dict):
        return found
    if word == 'naver-blog' and command in ('profile', 'about', 'graph'):
        return 'BLOG'
    return found.get(command, 'TEXT')


def usage(prog, actions):
    """A command's usage on one line: its options are listed under it, so only the positional arguments are spelled."""
    words = [prog, '[options]']
    for action in actions:
        if not action.option_strings:
            name = action.metavar or action.dest
            words.append({None: name, '?': f'[{name}]', '*': f'[{name} ...]', '+': f'{name} [{name} ...]'}[action.nargs])
    return ' '.join(words)


def parser(platforms, hidden=False, commands=None):
    commands = command_tables(platforms)[0] if commands is None else commands
    lines = []
    for word, module in platforms.items():
        names = list(commands[word])
        core = [name for name in CORE_COMMANDS if name in names]
        own = [name for name in names if name not in CORE_COMMANDS]
        lines.append(f'  {word:<11} {" ".join(core)}' + (f' | {" ".join(own)}' if own else ''))
    root = Parser(prog='cli.py', usage='cli.py [--verbose] <platform> <command> [options]',
                  description='Read social networks through the logged-in Aside browser. Read-only.\nPlatforms: '
                              + ' '.join(platforms) + '.',
                  formatter_class=argparse.RawTextHelpFormatter, add_help=False,
                  epilog=MEANINGS + '\n\nplatforms and their commands (after | each platform\'s own places):\n'
                         + '\n'.join(lines) + '\n  (every platform also has doctor and schema)\n\n' + CONVENTIONS
                         + '\n\nexit codes:\n' + exit_map())
    root.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)  # as on every leaf: the row says nothing
    root.add_argument('--verbose', action='store_true', help='Write scrubbed request metadata to stderr')
    branches = root.add_subparsers(dest='platform', required=True, metavar='<platform>', help=argparse.SUPPRESS)
    for word, module in platforms.items():
        platform = module.PLATFORM
        platform_commands = surface(module, commands[word])
        branch = branches.add_parser(word, prog=f'cli.py {word}', formatter_class=argparse.RawTextHelpFormatter,
                                     description=f'{platform.title}: its commands. Run cli.py {word} <command> '
                                                 '--help for one.')
        leaves = branch.add_subparsers(dest='command', required=True, metavar='<command>')
        for name, spec in platform_commands.items():
            leaf = leaves.add_parser(name, help=spec['help'], description=spec['help'], add_help=False,
                                     formatter_class=argparse.RawTextHelpFormatter, prog=f'cli.py {word} {name}')
            leaf.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)
            leaf._positionals.title = 'arguments'  # argparse has no public setter; "positional arguments" in fewer words
            for argument in spec['arguments']:
                flags, settings = option(argument, platform) if isinstance(argument, str) else argument
                if flags[0] in POSITIONAL_LABELS:
                    settings = {**settings, 'metavar': label(word, name, flags[0])}
                leaf.add_argument(*flags, **settings)
            leaf.usage = usage(leaf.prog, leaf._actions)
            leaf.epilog = epilog(spec, word, {flag for action in leaf._actions for flag in action.option_strings},
                                 platform.transport == 'tab')
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
                                exit_codes, tuple(argv))
        # another platform's link, or one of this platform of another kind: name the command that reads it
        foreign(module.PLATFORM, invocation, options.get('target'), options['command'],
                LINKS.get(options['platform'], {}).get(options['command']))
        kind, envelope = spec['run'](invocation)
    except SnsError as error:
        command = options.get('command')
        if command is None and len(argv) >= 2 and argv[0] == 'naver-blog' and argv[1] == 'me':
            command = 'me'
        kind, envelope = failure_envelope(error, module.PLATFORM.key if module else None, command)
    return emit(kind, envelope, options, module)


def cli_path():
    return __file__


if __name__ == '__main__':
    sys.exit(main())
