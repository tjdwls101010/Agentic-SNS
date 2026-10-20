"""X (Twitter): the platform interface — PLATFORM (the adapter the shared reading pipeline runs), COMMANDS (the command
specs cli.py turns into its parser and help) and CHOICES (every closed set of an argument, which a contract test holds
equal to the specs)."""
import argparse

from sns import reading
from sns.errors import SnsError
from sns.limits import LimitPolicy
from sns.window import WindowPolicy
from sns.x import about, explore, images, listing, search, thread, web
from sns.x.render import render

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
TREND_TABS = list(explore.TABS)

CHOICES = {
    'feed.feed': FEED_CHOICES, 'profile.tab': PROFILE_TABS, 'graph.relation': GRAPH_RELATIONS,
    'me.collection': ME_COLLECTIONS, 'list.tab': LIST_TABS, 'community.tab': COMMUNITY_TABS,
    'community.sort': COMMUNITY_SORTS, 'post.sort': REPLY_SORTS, 'search.type': SEARCH_TYPES,
    'search.sort': SEARCH_SORTS, 'search.within': ['communities'], 'quotes.sort': REPLY_SORTS,
    'trends.tab': TREND_TABS,
}

PLATFORM = reading.Platform(
    key='x', title='X', site='x.com', transport='tab',
    # X's windows are per operation (15 minutes), slowed below 20% left; a 429 without a reset waits one window
    policy=LimitPolicy(scope='operation', slow='fraction', slow_fraction=0.2, hold_seconds=900,
                       person=('challenge', 'account_locked'), pace=(1.0, 2.0)),
    window=WindowPolicy(unit_key='unit'), connect=web.Client, render=render,
    schemas={**web.SCHEMAS, 'image': reading.IMAGE_SCHEMA},
    locate=web.locate, unblock_scope='Viewer', idle_action='close')

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
        'run': _run(listing.feed),
        'arguments': [(('--feed',), {'choices': FEED_CHOICES, 'default': 'foryou',
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
        'run': _run(listing.profile),
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
        'run': _run(about.about),
        'arguments': [(('target',), {'nargs': '+', 'help': 'X @handle or profile URL, several read together; or one x.com/i/spaces/<id> link'}),
                      'json'],
        'epilog': ['A card: name, bio, links, location, join date, counts (followers, following, posts), whether it is protected, its relation to you, and its marks: a paid check is an X subscription, not an identity check; a Business or Government badge is granted by X to an organisation; a declared Parody, Commentary or Fan label is the account\'s own. Several handles: those X did not return are named (unresolved).',
                   'A space link reads the space: title, live/scheduled/ended, host and speakers, listener counts and whether a replay is kept. A space X no longer keeps is unavailable (exit 9).',
                   'requests: 1.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 9, 10),
    },
    'graph': {
        'help': 'Read the accounts a profile follows or that follow it, or the accounts X recommends as similar.',
        'run': _run(listing.graph),
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
        'run': _run(listing.me),
        'arguments': [(('collection',), {'choices': ME_COLLECTIONS, 'help': 'bookmarks, likes (nobody else\'s likes are public on X), notifications or mentions'}),
                      *LIST],
        'epilog': ['In X\'s order (most recently saved or liked first, as X serves it); each post keeps its own date, not when you saved or liked it. There is no date window: X does not serve these in date order.',
                   'notifications are X\'s notification tab as records (what happened, when, which accounts and posts); "suggested by X" marks X recommending something, which is not anyone\'s act. mentions are the posts that mention you. The skill only sends the read and never opens X\'s notifications screen, which marks them as read; whether X counts the read alone as seen is not known. A notification\'s message names other people.',
                   'Without --limit or --out it reads one page; more: continues.',
                   'requests: 1 per page of about 20 posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
    },
    'list': {
        'help': 'Read an X list: its posts, its members or its card.',
        'run': _run(listing.lists),
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
        'run': _run(listing.community),
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
        'run': _run(thread.post),
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
        'run': _run(thread.replies),
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
        'run': _run(listing.reposts),
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'x.com post URL or numeric id'}), *LIST],
        'epilog': ['A repost is an account sharing the post as it is, which records the act, not agreement; quotes (the posts that add words) are read with quotes. The list is what X serves, page by page; three pages in a row with no new account end the read.',
                   'Without --limit or --out it reads one page; more: continues.',
                   'requests: 1 per page of about 20 accounts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
    },
    'quotes': {
        'help': 'Read the posts that quote one post.',
        'run': _run(search.quotes),
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
        'run': _run(search.search),
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
        'run': _run(explore.trends),
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
        'run': _run(images.images),
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'x.com post URL or numeric id'}),
                      (('numbers',), {'nargs': '*', 'type': _positive, 'metavar': 'N',
                                      'help': 'The pictures to save, by the numbers the post shows ([image N])'}),
                      (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
        'epilog': ['The post is read again (its picture links do not last), so N is the Nth picture as X sends the post '
                   'now; each saved line names its kind, size, alt text and media_id to match what the post showed. A '
                   'video is saved as its poster image, not the video. Files go to the skill\'s data/images/ and are '
                   'removed a day later; they are other people\'s pictures. A picture that could not be saved is named '
                   'in coverage (exit 8).',
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
