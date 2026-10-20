"""Naver Blog: the platform adapter the shared reading pipeline runs, and the commands cli.py registers under
`naver-blog`.

Its interface: PLATFORM (a reading.Platform), COMMANDS (command → help, run, arguments, epilog, exits) and CHOICES (the
closed sets the commands offer).
"""
import argparse

from sns import reading
from sns.clock import KST
from sns.limits import LimitPolicy
from sns.window import WindowPolicy

from sns.naver_blog import blog, directory, images, neighbors, post, render, search, web

# Naver publishes no limit and sends no rate-limit headers: a 429 holds the account (30 minutes when it names no time),
# and current-user's network block is a person block. Requests are paced 0.5-0.8 s apart.
POLICY = LimitPolicy(scope='account', hold_seconds=1800, person=('network_blocked',), pace=(0.5, 0.8))

RECORDS = {
    'post': web.record_schema('post', web.Post, web.RECORD_NOTES['post']),
    'post_read': web.record_schema('post_read', web.PostDoc, web.POST_READ_NOTES, skip=('viewer_id',)),
    **{name: web.record_schema(name, cls, web.RECORD_NOTES[name]) for name, cls in (
        ('comment', web.Comment), ('blog', web.Blog), ('category', web.Category), ('buddy', web.Buddy),
        ('topic', web.Topic), ('clip', web.Clip), ('keyword', web.Keyword), ('group', web.Group),
        ('link', web.Resolved), ('image', web.Saved))},
}


def connect(connection):
    """The client of one invocation."""
    return web.Client(connection)


PLATFORM = reading.Platform(
    key='naver_blog', title='Naver Blog', site='blog.naver.com', transport='fetch', policy=POLICY,
    window=WindowPolicy(tz=KST), connect=connect, render=render.render, schemas=RECORDS, locate=web.locate,
    unblock_scope=None, idle_action=None)

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
        'run': _command(search.search), 'check': search.check,
        'arguments': [(('text',), {'nargs': '+', 'metavar': 'TEXT', 'help': 'What to search for; several words are one '
                                                                            'query (no quotes needed)'}),
                      (('--type',), {'choices': ['posts', 'blogs', 'tags', 'clips'], 'default': None,
                                     'help': 'posts (default), blogs (bloggers), tags (posts under an exact tag), or '
                                             'clips (short videos)'}),
                      (('--blog',), {'metavar': 'BLOG', 'help': 'Search inside one blog (id, URL or naver.me link): '
                                                                '--type posts or tags'}),
                      (('--sort',), {'choices': ['sim', 'date'], 'help': 'sim (Naver\'s relevance, default) or date '
                                                                         '(newest first); posts, blogs and clips'}),
                      'since', 'until',
                      (('--own-money',), {'action': 'store_true', 'help': 'Naver-wide post search: only posts carrying '
                                                                          'Naver\'s 내돈내산 인증 card, a purchase or visit '
                                                                          'Naver recorded (a title or tag saying 내돈내산 '
                                                                          'is not it)'}),
                      'limit', 'chars', 'after', 'out', 'json'],
        'epilog': ['What each search honours (refused otherwise, before any request): posts — --sort, --since/--until '
                   '(Naver filters by KST day) and --own-money; blogs — --sort only; tags — no order (newest first), '
                   'so --since/--until is applied here and closes the window; --blog posts — --sort and dates; --blog '
                   'tags — neither, and it matches whole tags only. Relevance (sim) is Naver\'s ranking for this '
                   'account, not a sample of opinion.',
                   'Naver serves at most 1,000 results of any search: the read ends there as a natural end '
                   '(stopped=server_capped, exit 0, a coverage line says so); narrow the words or the dates to reach '
                   'further. A tag result carries no blog name.',
                   'limit: --limit counts records. Without it one page is read (30 posts or tags, 20 blogs, clips or '
                   'in-blog posts) and 10 are shown. ' + PAGE + ' With --out whole pages are saved, so a little over '
                   '--limit.',
                   'cost: 1 request per page; a --blog domain address costs one lookup. ' + ACCOUNT],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
    'keywords': {
        'help': 'Naver Blog\'s popular searches of the day, or the searches related to one keyword.',
        'run': _command(search.keywords),
        'arguments': [(('text',), {'nargs': '*', 'metavar': 'TEXT', 'help': 'A keyword for its related searches; '
                                                                            'omitted: the popular ones'}), 'json'],
        'epilog': ['Popular: about 12 keywords and the day Naver computed them; related: about 15 keywords. Both are '
                   'Naver\'s own order — a ranking, not a share of searches or of opinion. search <keyword> reads '
                   'one.',
                   'cost: 1 request.'],
        'exits': (0, 2, 3, 4, 5, 6, 7),
    },
    'post': {
        'help': 'Read one post in full: body, pictures, links, tags, reactions, same-category posts.',
        'run': _command(post.post),
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
                   'cost: 3 requests (the page, its reactions, the same-category posts), +1 with --comments (+1 when '
                   'the blog number is unknown), +1 for a naver.me link, +1 with --out for the account check.',
                   'output: the post section ([p1]: head, tags and flags, the label, the body lines, links:, url), '
                   'then same category ([p<n>] posts) and comments ([c<n>]). --json: one envelope whose sections hold '
                   'the records (schema post_read).'],
        'exits': (0, 2, 3, 4, 5, 6, 8, 9),
    },
    'comments': {
        'help': 'Read a post\'s comments and replies, newest first, replies under their parent.',
        'run': _command(post.comments),
        'arguments': [(('target',), {'metavar': 'POST', 'help': 'Post URL, blogId/logNo, or a naver.me link'}),
                      'limit', 'chars', 'after', 'out', 'json'],
        'epilog': ['Comments come newest first; each comment\'s replies follow it, oldest first, indented '
                   '(reply-to=#n). A reply whose parent is on another page says (parent not shown). blog: <id> on a '
                   'comment is the commenter\'s blog. A coverage line gives Naver\'s own count of comments, replies, '
                   'deleted and blinded ones.',
                   'limit: --limit counts rows (comments and replies together). Without it one page of up to 100 rows '
                   'is read and 20 are shown. ' + PAGE,
                   'cost: 1 request to find the blog number (a continuation carries it), then 1 per 100 rows. '
                   + ACCOUNT],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
    'images': {
        'help': 'Save a post\'s pictures by their numbers so they can be looked at (Read the printed path).',
        'run': _command(images.images),
        'arguments': [(('target',), {'metavar': 'POST', 'help': 'Post URL, blogId/logNo, or a naver.me link'}),
                      (('numbers',), {'nargs': '*', 'type': positive, 'metavar': 'N', 'help': 'Picture numbers as '
                                                                                          'post shows them ([image N])'}),
                      (('--all',), {'action': 'store_true', 'help': 'Every picture of the post (stickers, cards and '
                                                                    'maps included)'}), 'json'],
        'epilog': ['Reads the post again (1 request) and saves each picture (1 request each) under data/images/, '
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
        'run': _command(post.resolve),
        'arguments': [(('target',), {'nargs': '+', 'metavar': 'LINK', 'help': 'naver.me/<code> links (as post\'s '
                                                                               'links: block prints them)'}),
                      'json'],
        'epilog': ['Each link is read once and its redirect reported, never followed: the destination with its host '
                   'and, for commission or marketing hosts (brandconnect.naver.com is a creator\'s shopping-connect '
                   'link), its id; a Naver Blog post destination is named as post takes it.',
                   'Any number of links is read. When the time limit or a hold interrupts, the links not yet read go '
                   'on in the more: command, which names them.',
                   'cost: 1 request per link.'],
        'exits': (0, 2, 3, 4, 5, 6, 8),
    },
    'blog': {
        'help': 'Read a blog\'s card, post and clip counts, category tree, notices and popular posts.',
        'run': _command(blog.blog),
        'arguments': [(('target',), {'metavar': 'BLOG', 'help': 'Blog id, blog URL (a post URL names its blog), or a '
                                                                'naver.me link'}),
                      (('--brief',), {'action': 'store_true', 'help': 'Card, counts and categories only (3 requests)'}),
                      'chars', 'json'],
        'epilog': ['The card: name, nickname, description, neighbor count, visitors today and in total, posts and '
                   'clips, the viewer\'s relation (neighbor or mutual-neighbor), official/market/power-blog marks. '
                   'Categories are the tree ([n] name · posts; closed ones are counted, not listed). Popular posts are '
                   'the only surface with view counts. A domain address is resolved once to the blog\'s own id.',
                   'cost: 5 requests (card, counts, categories, notices, popular); --brief 3; +1 for a domain address '
                   'or a naver.me link.',
                   'output: sections blog ([b1]), categories, notices and popular ([p<n>]); a failed section is shown '
                   'and makes the exit 8.'],
        'exits': (0, 2, 3, 4, 5, 6, 8, 9),
    },
    'posts': {
        'help': 'List one blog\'s posts newest first: all, one category, its notices or its popular posts.',
        'run': _command(blog.posts), 'check': blog.check,
        'arguments': [(('target',), {'metavar': 'BLOG', 'help': 'Blog id, blog URL (a PostList URL\'s categoryNo counts '
                                                                'as --category), or a naver.me link'}),
                      (('--category',), {'metavar': 'N|NAME', 'help': 'A category number (free) or name (one request: '
                                                                      'exact match first, then part of a name)'}),
                      (('--popular',), {'action': 'store_true', 'help': 'The popular posts (one page, with view '
                                                                        'counts)'}),
                      (('--notices',), {'action': 'store_true', 'help': 'The notice posts (one page)'}),
                      'since', 'until', 'limit', 'chars', 'after', 'out', 'json'],
        'epilog': ['The list is newest first, so --since closes it at the first post older than that day. Naver '
                   'reports no total here. Popular and notices are one page each: no window, file or more:.',
                   'limit: --limit counts posts. Without it one page of 30 is read and 10 are shown. ' + PAGE,
                   'cost: 1 request per page of 30 (+1 for a category name, a domain address or a naver.me link). '
                   + ACCOUNT],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
    'feed': {
        'help': 'Read the logged-in account\'s neighbor feed (이웃새글), newest first, a page at a time.',
        'run': _command(neighbors.feed),
        'arguments': [(('--group',), {'type': positive, 'metavar': 'N', 'help': 'Only one neighbor group (buddies '
                                                                               '--groups lists them)'}),
                      'since', 'until', 'limit', 'chars', 'after', 'out', 'json'],
        'epilog': ['Only the blogs this account follows, newest first, so --since closes at the first post older than '
                   'that day. A coverage line gives Naver\'s count of feed posts.',
                   'limit: --limit counts posts. Without it one page of 20 is read and 10 are shown. ' + PAGE,
                   'cost: 1 request per page of 20, after the account check (current-user, 1 request: the feed is '
                   'addressed by the logged-in account\'s blog id, so it is always asked, and a continuation asks '
                   'again).'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'buddies': {
        'help': 'Read the logged-in account\'s neighbor list, or a blog\'s public one.',
        'run': _command(neighbors.buddies), 'check': neighbors.check,
        'arguments': [(('target',), {'nargs': '?', 'metavar': 'BLOG', 'help': 'A blog id or URL for its public neighbor '
                                                                              'list; omitted: your own neighbors'}),
                      (('--followers',), {'action': 'store_true', 'help': 'The blogs that added you as a neighbor'}),
                      (('--group',), {'type': positive, 'metavar': 'N', 'help': 'Only your neighbors in one group'}),
                      (('--groups',), {'action': 'store_true', 'help': 'Your neighbor groups (one page)'}),
                      'limit', 'chars', 'after', 'out', 'json'],
        'epilog': ['--followers, --group and --groups read your own account and take no blog. Your own list (20 a '
                   'page) carries mutual (서로이웃) and your groups; a blog\'s public list (50 a page) is private by '
                   'default, so an empty one (exit 7) does not mean no neighbors — blog <id> shows the card\'s count.',
                   'limit: --limit counts neighbors. Without it one page is read and 20 are shown. ' + PAGE,
                   'cost: 1 request per page; your own lists ask the account first (current-user, 1 request), a '
                   'blog\'s public list does not.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
    'topic': {
        'help': 'Browse the topic directory, or one topic\'s newest or featured posts.',
        'run': _command(directory.topic), 'check': directory.check,
        'arguments': [(('target',), {'nargs': '?', 'metavar': 'TOPIC', 'help': 'Topic number (free) or name (one '
                                                                               'request); omitted: the directory'}),
                      (('--top',), {'action': 'store_true', 'help': 'The topic\'s featured posts (one page) instead '
                                                                     'of its newest'}),
                      'since', 'until', 'limit', 'chars', 'after', 'out', 'json'],
        'epilog': ['A topic\'s posts are the ones Naver files under it, newest first (a window closes on them), up to '
                   '1,000 (then stopped=server_capped, a natural end). The directory and featured posts are one page '
                   'each: no window, file or more:.',
                   'limit: --limit counts posts. Without it one page of 10 is read and shown. ' + PAGE,
                   'cost: 1 request per page of 10 (+1 for a topic name). ' + ACCOUNT],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
    'monthly': {
        'help': 'Read the blogs of the month: an issue\'s topics, blogs and representative posts.',
        'run': _command(directory.monthly), 'check': directory.check_monthly,
        'arguments': [(('--year',), {'type': positive, 'help': 'Issue year (with --month); omitted: the latest issue'}),
                      (('--month',), {'type': positive, 'help': 'Issue month 1-12 (with --year)'}), 'chars', 'json'],
        'epilog': ['A coverage line names the issue shown. A month with no issue (the current one before it is '
                   'published) is exit 9 naming the latest, never silently swapped for it. Each topic section lists '
                   'its blogs ([b] card) each followed by its first representative posts.',
                   'cost: 4 requests (the issue list, the issue, the blogs\' cards, their posts).',
                   'output: one section per topic: [b<n>] blog cards, each followed by [p<n>] posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
}

# The closed sets the commands offer (cli.py checks its parser's choices against this).
CHOICES = {'search.type': ['posts', 'blogs', 'tags', 'clips'], 'search.sort': ['sim', 'date']}
