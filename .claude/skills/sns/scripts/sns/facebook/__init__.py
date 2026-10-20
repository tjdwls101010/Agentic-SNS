"""Facebook: the platform interface — PLATFORM (the adapter the shared reading pipeline runs), COMMANDS (the command
specs cli.py turns into its parser and help) and CHOICES (every closed set of an argument, which a contract test holds
equal to the specs)."""
import argparse

from sns import reading
from sns.errors import SnsError
from sns.facebook import about, images, listing, notifications, search, thread, web
from sns.facebook.render import render
from sns.limits import LimitPolicy
from sns.window import WindowPolicy

FEED_SORTS = ['top', 'recent']
GROUP_SORTS = ['top', 'recent', 'activity']
COMMENT_SORTS = ['all', 'relevant', 'newest']
SEARCH_TYPES = ['top', 'posts', 'people', 'pages', 'groups']

CHOICES = {'feed.sort': FEED_SORTS, 'group.sort': GROUP_SORTS, 'post.sort': COMMENT_SORTS,
           'comments.sort': COMMENT_SORTS, 'search.type': SEARCH_TYPES}

PLATFORM = reading.Platform(
    key='facebook', title='Facebook', site='facebook.com', transport='tab',
    # Facebook announces no limit: a 429 on any of the tab's requests holds the account for 30 minutes; a checkpoint
    # is the one block only a person clears
    policy=LimitPolicy(scope='account', hold_seconds=1800, person=('checkpoint',), pace=(1.0, 2.0)),
    window=WindowPolicy(), connect=web.Client, render=render, schemas={**web.SCHEMAS, 'image': reading.IMAGE_SCHEMA}, locate=web.locate,
    unblock_scope=None, idle_action='blank')   # window.close() does not take on Facebook's tab (measured): empty it

LIST = ['limit', 'chars', 'after', 'out', 'json']


def check_replies(options):
    if not (options['target'].isascii() and options['target'].isdigit()):
        raise SnsError('argument', 'A replies handle is the number printed after "replies".',
                       'Copy the whole replies line.')


def check_search(options):
    if not options['target'].strip():
        raise SnsError('argument', 'Search text must not be empty.', 'Pass the words to search for.')
    if options['type'] not in ('top', 'posts') and (options.get('recent') or options.get('since')
                                                    or options.get('until') or options.get('in_group')):
        raise SnsError('argument', '--recent, --since, --until and --in-group are for posts; use them with --type top '
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
        'run': _run(listing.feed),
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
        'run': _run(listing.profile),
        'arguments': [(('target',), {'help': 'Profile or page URL, vanity name or numeric id'}), 'since', 'until', *LIST],
        'epilog': ['--since/--until are applied by Facebook (server-filtered) and checked against each post\'s date again; reading to the end closes the window. A post with no date cannot be placed in a window and is left out and counted; a pinned post is judged by its date like the others.',
                   'A timeline can hold posts by other people (posts on the timeline, shares); each record names its author.',
                   'Without --limit or --out it reads one page (about 3-5 posts); a --since/--until window reads on until it ends; more: continues.',
                   'requests: 1 to find the numeric id (none for a numeric id), then 1 per page of about 3-5 posts.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9),
    },
    'group': {
        'help': 'Read a group\'s posts.',
        'run': _run(listing.group),
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
        'run': _run(thread.post),
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
        'run': _run(thread.comments),
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
        'run': _run(thread.replies),
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
        'run': _run(search.search),
        'arguments': [(('target',), {'metavar': 'TEXT', 'help': 'What to search for'}),
                      (('--type',), {'choices': SEARCH_TYPES, 'default': 'top', 'help': 'top mixes posts with people, pages and groups in Facebook\'s order'}),
                      (('--recent',), {'action': 'store_true', 'help': 'Posts only (top, posts): Facebook\'s "recent posts" filter'}),
                      'since', 'until',
                      (('--in-group',), {'metavar': 'GROUP', 'help': 'Search the posts of one group (its URL, vanity name or numeric id), as the group\'s own search box does'}),
                      *LIST],
        'epilog': ['Results are in Facebook\'s order for this account; people and pages with the same name are different results (compare url and verified).',
                   '--recent, --since and --until are Facebook\'s post filters (top and posts only): Facebook applies the dates, so reaching the end closes the window as far as search returns posts; results stay in Facebook\'s order, not by date. A result with no date cannot be placed in a window and is left out and counted.',
                   '--in-group searches one group\'s posts (top or posts): requests: 1 to find the group id (none for a numeric id), then 1 per page.',
                   'Without --limit or --out it reads one page (about 5 results); more: continues.',
                   'requests: 1 per page of about 5 results.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
        'check': check_search,
    },
    'about': {
        'help': 'Read a profile\'s or page\'s visible About fields, or a group\'s card.',
        'run': _run(about.about),
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
        'run': _run(images.images),
        'arguments': [(('target',), {'help': 'Post permalink URL'}),
                      (('numbers',), {'nargs': '*', 'type': _positive, 'metavar': 'N',
                                      'help': 'The pictures to save, by the numbers the post shows ([image N])'}),
                      (('--all',), {'action': 'store_true', 'help': 'Save every picture of the post'}), 'json'],
        'epilog': ['The post is read again (its picture links are signed and do not last), so N is the Nth picture as '
                   'Facebook sends the post now; each saved line names its kind, size and media_id to match what the '
                   'post showed. A video is saved as its poster image. Files go to the skill\'s data/images/ and are '
                   'removed a day later; they are other people\'s pictures. A picture that could not be saved is named '
                   'in coverage (exit 8); a number the post does not have is refused before any picture is fetched (exit 2). A stop between pictures (the time limit, a hold) keeps the saved ones and ends with more: naming the numbers left.',
                   'requests: 2 for the post (its page, then the post), then 1 per picture.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8),
    },
    'notifications': {
        'help': 'Read your notification list, a page at a time, without marking anything seen.',
        'run': _run(notifications.notifications),
        'arguments': [*LIST],
        'epilog': ['Reads the notifications of the account the tab is logged in to, in Facebook\'s order. Each record is [n1] time · type word · unseen, seen or read, then the text Facebook wrote, then url: what it points at (a post permalink opens with post <url>). Bucket headers and the see-previous button are layout and are left out.',
                   'Reading the list sends no seen or read change (those are separate requests this skill never sends); whether Facebook counts a read as seen by itself was not observable when this was measured (no unseen notification at the time). If Facebook stops accepting the stored notifications query the command ends with exit 6 and does not open the notifications screen to relearn it, because opening that screen is what makes the app mark notifications seen.',
                   'Without --limit or --out it reads one page (about 15 notifications); more: continues.',
                   'requests: 1 per page of about 15 notifications.'],
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
       'longer accepts a stored one) about 10 more; both are shown as "tab opened" and counted apart from the reads, '
       'and requests the page finishes later use up those reservations first. Requests the open tab made between '
       'commands are shown as unwatched=, not charged, but a rate limit or a checkpoint seen there stops the command '
       'before it sends anything. The tab is emptied (about:blank) about 5 minutes after the last command.')
for _name in ('feed', 'profile', 'group', 'post', 'comments', 'replies', 'search', 'about', 'notifications'):
    COMMANDS[_name]['epilog'] = [*COMMANDS[_name]['epilog'], RECORDS, TAB]
COMMANDS['images']['epilog'] = [*COMMANDS['images']['epilog'], TAB]
