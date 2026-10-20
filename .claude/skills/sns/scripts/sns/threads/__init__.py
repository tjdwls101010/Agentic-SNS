"""Threads: the platform interface — PLATFORM (the adapter the shared reading pipeline runs), COMMANDS (the command
specs cli.py turns into its parser and help) and CHOICES (every closed set of an argument, which a contract test holds
equal to the specs)."""
import argparse

from sns import reading
from sns.errors import SnsError
from sns.limits import LimitPolicy
from sns.threads import about, images, listing, search, thread, web
from sns.threads.render import render
from sns.window import WindowPolicy

FEED_CHOICES = ['foryou', 'following']
PROFILE_TABS = ['threads', 'replies', 'reposts', 'media']
GRAPH_RELATIONS = ['followers', 'following']
ME_COLLECTIONS = ['liked', 'saved']
REPLY_SORTS = ['top', 'recent']
SEARCH_TYPES = ['posts', 'tags', 'accounts']
SEARCH_SORTS = ['top', 'recent']

CHOICES = {
    'feed.feed': FEED_CHOICES, 'profile.tab': PROFILE_TABS, 'graph.relation': GRAPH_RELATIONS,
    'me.collection': ME_COLLECTIONS, 'search.type': SEARCH_TYPES, 'search.sort': SEARCH_SORTS,
    'post.sort': REPLY_SORTS,
}

PLATFORM = reading.Platform(
    key='threads', title='Threads', site='threads.com', transport='tab',
    # Threads announces no limit windows: a 429 holds the account for 30 minutes; a checkpoint needs a person
    policy=LimitPolicy(scope='account', hold_seconds=1800, person=('checkpoint',), pace=(1.0, 2.0)),
    window=WindowPolicy(unit_key='unit'), connect=web.Client, render=render,
    schemas={**web.SCHEMAS, 'image': reading.IMAGE_SCHEMA},
    locate=web.locate, unblock_scope=None, idle_action='blank')

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


def _run(function):
    return lambda invocation: function(PLATFORM, invocation)


COMMANDS = {
    'feed': {
        'help': 'Read your home feed, a page at a time.',
        'run': _run(listing.feed),
        'arguments': [(('--feed',), {'choices': FEED_CHOICES, 'default': 'foryou',
                                     'help': 'foryou: the posts Threads ranks for this account; following: the accounts it follows, newest first'}),
                      'since', 'until', *LIST],
        'epilog': ['foryou is what Threads chose to show this account, not everything; following holds only the accounts it follows. Neither feed ends by itself, so --out needs --limit.',
                   'A window keeps the dated posts written on its days (posts without a date are left out and counted). Only --feed following can close a --since window (it stops at the first page wholly older than --since, while the feed stays newest first); foryou is a sample of the window: it keeps the posts dated inside it among the page read.',
                   'A feed entry can carry several posts (a post and a reply to it, or an author continuing a post): they are shown together, and the later ones say reply-to= or continuation of.',
                   'Without --limit or --out it reads one page (following with a window reads on until it closes); more: continues.',
                   'requests: 1 per page of about 5-10 posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'profile': {
        'help': 'Read a profile\'s tab: threads, replies, reposts or media.',
        'run': _run(listing.profile),
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
        'run': _run(about.about),
        'arguments': [(('target',), {'help': 'Threads @handle or profile URL'}), 'json'],
        'epilog': ['Threads publishes a follower count but no following or mutual count: those are shown as ? (unknown); graph following lists the accounts.',
                   'A verified badge and a bio are what the account claims about itself.',
                   'requests: 2 (find the profile, read its card).'],
        'exits': (0, 2, 3, 4, 5, 6, 8, 9),
    },
    'graph': {
        'help': 'Read the accounts that follow a profile, or that it follows.',
        'run': _run(listing.graph),
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
        'run': _run(listing.me),
        'arguments': [(('collection',), {'choices': ME_COLLECTIONS, 'help': 'liked or saved'}), *LIST],
        'epilog': ['One batch, as Threads sends it (stopped=not_paginable): not your whole history.',
                   'requests: 1.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'search': {
        'help': 'Search posts, tags or accounts.',
        'run': _run(search.search),
        'arguments': [(('target',), {'metavar': 'TEXT', 'help': 'What to search for (a tag without #)'}),
                      (('--type',), {'choices': SEARCH_TYPES, 'default': 'posts',
                                     'help': 'posts (by words), tags (posts under a tag) or accounts (one batch of profiles)'}),
                      (('--sort',), {'choices': SEARCH_SORTS, 'default': 'top',
                                     'help': 'Posts and tags: top (Threads ranks them) or recent (newest first)'}),
                      'since', 'until',
                      (('--from',), {'metavar': 'HANDLE', 'help': 'Posts and tags: only posts by this @handle'}),
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
        'run': _run(thread.post),
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
        'run': _run(thread.replies),
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
        'run': _run(listing.activity),
        'arguments': [(('target',), {'help': 'Post URL or shortcode'}), *LIST],
        'epilog': ['Each quote is its own post ([p] label, role quote), shown with its author and its text as the activity list gives it (--chars sets how much is shown); post <url> opens it with its media and replies. Threads sends one batch of up to about 100, in its own order: when it reports more (reported_total), the rest cannot be asked for (stopped=server_capped).',
                   'requests: 1.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'reposts': {
        'help': 'Read the accounts that reposted one post (one batch).',
        'run': _run(listing.activity),
        'arguments': [(('target',), {'help': 'Post URL or shortcode'}), *LIST],
        'epilog': ['Each account ([a] label) with when it reposted. Threads sends one batch of up to about 100, in its own order: when it reports more (reported_total), the rest cannot be asked for (stopped=server_capped).',
                   'requests: 1.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'images': {
        'help': 'Save the pictures of one post (a video by its poster) so they can be looked at.',
        'run': _run(images.images),
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'threads.com (or threads.net) post URL'}),
                      (('numbers',), {'nargs': '*', 'type': _positive, 'metavar': 'N',
                                      'help': 'The pictures to save, by the numbers the post shows ([image N])'}),
                      (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
        'epilog': ['The post is read again (its picture links are signed and do not last), so N is the Nth picture as '
                   'Threads sends the post now; each saved line names its kind, size and media_id to match what the '
                   'post showed. A video is saved as its poster image. Files go to the skill\'s data/images/ and are '
                   'removed a day later; they are other people\'s pictures. A picture that could not be saved is named '
                   'in coverage (exit 8).',
                   'requests: 3 for the post (as post reads it), then 1 per picture.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
}


# What every reading command's output holds beyond the shared description (the core's text names no Threads record
# kinds and knows nothing of the dedicated tab).
RECORDS = ('records: one block per record, labelled [p1] post, [r1] reply, [a1] account, each ending with the arguments '
           'of the next command (url: post <url> opens that one post; author; replies <handle>).')
TAB = ('the dedicated tab: the skill reads from its own threads.com tab. Opening it (or loading it again after it was '
       'emptied) costs about 34-40 requests the page makes itself, shown as "tab opened" and counted apart from the '
       'reads; learning a query Threads refused reads one document per try (at most 3 tries and one reload a command); '
       'requests the open tab made between commands are shown as unwatched=, not charged, but a block seen there stops '
       'the command before it sends anything; static files do not count. The tab is emptied (about:blank) about 5 '
       'minutes after the last command.')
for _name in ('feed', 'profile', 'about', 'graph', 'me', 'search', 'post', 'replies', 'quotes', 'reposts'):
    COMMANDS[_name]['epilog'] = [*COMMANDS[_name]['epilog'], RECORDS, TAB]
COMMANDS['images']['epilog'] = [*COMMANDS['images']['epilog'], TAB]
