"""Reddit: the platform adapter the shared reading pipeline runs, and the commands cli.py registers under `reddit`.

Its interface: PLATFORM (a reading.Platform), COMMANDS (command → help, run, arguments, epilog, exits) and CHOICES (the
closed sets the commands offer), and TREE, the pure comment-tree policy behind post and comments (state in, state out;
exported so tests can drive it without a browser).
"""
import argparse
from types import SimpleNamespace

from sns import reading
from sns.limits import LimitPolicy
from sns.window import WindowPolicy

from sns.reddit import about, listing, render, search, thread, web, wiki
from sns.reddit.snapshots import Snapshots

POLICY = LimitPolicy(scope='bucket', slow='used', hold_seconds=600, person=('challenge',), pace=(1.0, 2.0))


def connect(connection):
    """The client of one invocation; doctor also reports what the comment threads take on disk."""
    return web.Client(connection, extra=lambda: {
        'snapshot_bytes': Snapshots(connection.account, connection.deadline).size(),
        'holds_personal_data_here': 'data/reddit/<account>/snapshots/ — comment threads with other people\'s words; '
                                    'they expire after a day on their own'})


RECORDS = {
    'post': {'object': 'post', 'description': 'A post ([p] label).', 'fields': {
        'kind, id, url, created_at': 'string — kind post; the Reddit fullname t3_<id> (a comment with the same base id, '
                                     't1_, is a different thing); the post\'s permalink (post <url> opens it in full '
                                     'with its comments); UTC ISO-8601 or null',
        'title, text': 'string — as received (text is the body of a text post; [removed] or [deleted] when gone)',
        'subreddit, author': 'string — the community and the account that posted it ([deleted] when unknown)',
        'edited_at': 'string|null — UTC ISO-8601',
        'score, upvote_ratio': 'number|null — as Reddit shows them; null when not sent',
        'num_comments': 'number|null — Reddit\'s total, deleted and removed comments included; not the number read',
        'post_type': 'string — self, link, image, gallery, video, poll, crosspost (or another post_hint)',
        'link_url, domain': 'string — where a link post points; a crosspost\'s is the original\'s permalink',
        'flair': 'string|null — the post\'s flair in that community',
        'nsfw, spoiler, locked, archived, pinned': 'boolean — markers; NSFW posts are shown, never filtered',
        'distinguished': 'string|null — moderator or admin when posted in that role',
        'removed': 'string|null — why a post is gone (moderator, deleted, automod_filtered, reddit ...)',
        'contest_mode': 'boolean — comments come in random order with scores hidden',
        'suggested_sort': 'string|null — the comment order the moderators chose for this thread',
        'num_crossposts, num_duplicates': 'number|null — other discussions of the same link (related reads them)',
        'media': 'array — the post\'s pictures and clips, in the order Reddit shows them (a gallery\'s own order): '
                 '[{n (from 1), kind (photo, gif, sticker or video), image_url (the original picture, or a video\'s '
                 'poster; null when Reddit sent none), video_url (the clip, or null), width, height (pixels of the '
                 'original, or null), alt (the gallery caption), media_id (Reddit\'s id for a gallery item, or '
                 'null)}]; nothing is downloaded',
        'poll': 'object|null — {options [{text, vote_count|null}], total_vote_count, voting_ends_at}',
        'crosspost': 'object|null — the original post (its own author, community and media numbering)'}},
    'comment': {'object': 'comment', 'description': 'A comment ([c] label).', 'fields': {
        'kind, id, url, created_at': 'string — kind comment; the Reddit fullname t1_<id>; the comment\'s permalink '
                                     '(comments <url> opens it in full with what hangs under it); UTC ISO-8601 or '
                                     'null',
        'parent_id': 'string — the fullname it answers (t1_ a comment, t3_ the post)', 'post_id': 'string — t3_<id>',
        'text': 'string — as received; > lines quote someone else ([removed] or [deleted] when gone)',
        'author, subreddit': 'string', 'edited_at': 'string|null — UTC ISO-8601',
        'score': 'number|null', 'score_hidden': 'boolean — the community hides new comments\' scores for a while',
        'depth': 'integer — 0 for a comment on the post',
        'is_op': 'boolean — written by the post\'s author', 'distinguished': 'string|null — moderator or admin',
        'author_flair': 'string|null — what the author says about themselves in that community',
        'pinned, locked': 'boolean', 'collapsed': 'boolean — Reddit folds it by default',
        'collapsed_reason': 'string|null — Reddit\'s reason code (LOW_SCORE, DELETED ...), sent even when not folded',
        'controversial': 'boolean — many votes both ways', 'removed': 'string|null — removed (by moderators or Reddit) '
        'or deleted (by its author)',
        'media': 'array — pictures posted in the comment, numbered from 1 in the order sent; same items as a post\'s '
                 'media (kind photo, gif or sticker)',
        'context, anchor': 'boolean — only on a comment link\'s page: context rows are the linked comment\'s ancestors, '
                           'anchor is the linked comment'}},
    'subreddit': {'object': 'subreddit', 'description': 'A community ([s] label).', 'fields': {
        'kind, id, url, created_at': 'string — kind subreddit; t5_<id>; the community\'s address; when it was created '
                                     '(UTC ISO-8601 or null)',
        'name, title': 'string', 'text': 'string — the short description',
        'description': 'string — the sidebar', 'subscribers, active': 'number|null',
        'nsfw': 'boolean', 'visibility': 'string — public, restricted, private ...',
        'rules': 'array — about only: [{name, text, applies_to}]',
        'moderators': 'array — about only: moderator records (see schema moderator)',
        'pinned': 'array — about only: the posts pinned at the top of hot (post records); announcements and megathreads, '
                  'often old'}},
    'user': {'object': 'user', 'description': 'A redditor ([u] label). A public history is that account\'s observed '
                                              'activity; a profile may hide it, or hide some communities from it.',
             'fields': {'kind, id, url, created_at': 'string — kind user; t2_<id>; the profile address; when the '
                                                     'account was created (UTC ISO-8601 or null)',
                        'name': 'string',
                        'post_karma, comment_karma': 'number|null — karma earned by posts and by comments',
                        'text': 'string — the profile description',
                        'moderator, admin, verified': 'boolean'}},
    'moderator': {'object': 'moderator', 'description': 'A moderator of a community (about r/).', 'fields': {
        'kind, id, url': 'string — kind moderator; t2_<id>; the profile address', 'name': 'string',
        'flair': 'string|null — their flair in that community',
        'created_at': 'string|null — when they became a moderator there (UTC ISO-8601)'}},
    'wiki_page': {'object': 'wiki_page', 'description': 'One wiki page ([w] label).', 'fields': {
        'kind, id, url': 'string — kind wiki_page; wiki:<community>/<page>@<revision> (a later revision is another '
                         'record); the page\'s address',
        'created_at': 'string|null — when this revision was made (UTC ISO-8601)',
        'subreddit, page': 'string', 'text': 'string — the page\'s markdown as received',
        'revised_by': 'string|null', 'reason': 'string|null — the revision note'}},
    'wiki_index': {'object': 'wiki_index', 'description': 'A wiki\'s page list ([w] label).', 'fields': {
        'kind, id, url': 'string — kind wiki_index; wiki:<community>; the page list\'s address',
        'created_at': 'null — a page list has no date', 'subreddit': 'string',
        'pages': 'array<string> — article pages', 'settings_pages': 'array<string> — config/... pages (sidebar, rules '
                                                                    'text)'}},
}

PLATFORM = reading.Platform(
    key='reddit', title='Reddit', site='reddit.com', transport='fetch', policy=POLICY,
    window=WindowPolicy(jitter=600), connect=connect, render=render.render, schemas=RECORDS, locate=web.locate,
    unblock_scope='general', idle_action=None)

# --- the commands --------------------------------------------------------------------------------------------------

LIST = ['limit', 'chars', 'after', 'out', 'json']
WINDOW = ['since', 'until']
TIME = (('--time',), {'choices': web.TIMES, 'help': 'Reddit\'s own period for a ranking (top, controversial): hour, day, '
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
        'run': _command(listing.feed), 'check': listing.window_check,
        'arguments': [(('--sort',), {'choices': web.FEED_SORTS, 'help': 'best (default) and hot are Reddit\'s ranking '
                                                                        'for this account; new is newest first; top '
                                                                        'with --time'}), TIME, *WINDOW, *LIST],
        'epilog': ['The home feed is Reddit\'s choice for this account (its subscriptions and what it ranks), not Reddit '
                   'as a whole. best and hot never end by themselves: --out needs --limit there.', PAGE, WINDOWS,
                   ACCOUNT],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
    },
    'sub': {
        'help': 'Read a community\'s listing (r/name, r/a+b, r/popular, r/all).',
        'run': _command(listing.sub), 'check': listing.window_check,
        'arguments': [(('target',), {'help': 'r/<name>, a community URL, or r/<a+b> for several at once (r/popular and '
                                             'r/all are Reddit-wide)'}),
                      (('--sort',), {'choices': web.SUB_SORTS, 'help': 'hot (default), new (newest first), top or '
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
        'run': _command(listing.profile), 'check': listing.window_check,
        'arguments': [(('target',), {'help': 'u/<name> or a profile URL'}),
                      (('--type',), {'choices': web.PROFILE_TYPES, 'help': 'overview (posts and comments together, '
                                                                           'default), posts or comments'}),
                      (('--sort',), {'choices': web.PROFILE_SORTS, 'help': 'new (default), hot, top or controversial '
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
        'run': _command(about.about),
        'arguments': [(('target',), {'help': 'r/<name> or u/<name> (or their URLs); a bare word is refused'}),
                      'chars', 'json'],
        'epilog': ['A community: name, title, short description, sidebar, subscribers, active users, age, access type '
                   '(public, restricted, private) and NSFW, then its rules, its moderators and its pinned posts '
                   '(moderators\' announcements and megathreads, which can gather a topic the listing then shows '
                   'less of). A user: karma by kind, account age, profile description, and the moderator, admin and '
                   'verified markers. Karma, age and flair say what an account did on Reddit, not who the person is.',
                   'One live read tied to no handle or file, so the Reddit account is not checked first.',
                   'cost: 4 requests for a community (card, rules, moderators, the first page of hot for its pinned posts), '
                   '1 for a user.'],
        'exits': (0, 2, 3, 4, 5, 6, 9, 10),
    },
    'wiki': {
        'help': 'Read a community\'s wiki: one page in full, or its page list.',
        'run': _command(wiki.wiki),
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
                   'cost: 1 request.'],
        'exits': (0, 2, 3, 4, 5, 6, 9, 10),
    },
    'search': {
        'help': 'Search posts, communities or users, across Reddit or inside one community.',
        'run': _command(search.search), 'check': listing.window_check,
        'arguments': [(('text',), {'metavar': 'TEXT', 'help': 'What to search for, as one argument; sent to Reddit as '
                                                              'it is'}),
                      (('--type',), {'choices': web.SEARCH_TYPES, 'help': 'posts (default), subs (communities) or '
                                                                          'users'}),
                      (('--in',), {'dest': 'within', 'metavar': 'r/NAME', 'help': 'Search posts inside this one '
                                                                                   'community'}),
                      (('--sort',), {'choices': web.SEARCH_SORTS, 'help': 'relevance (default), hot, top, new (newest '
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
        'run': _command(listing.related),
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'A post URL or id (a comment link reads its post)'}),
                      *LIST],
        'epilog': ['Each other post of the same link, in other communities or the same one: one link\'s discussion is '
                   'often split across communities that react differently. Exit 7 when there is none.', PAGE, ACCOUNT],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    },
    'me': {
        'help': 'Read your own subscriptions, saved or upvoted items.',
        'run': _command(listing.me),
        'arguments': [(('collection',), {'choices': web.ME_COLLECTIONS, 'help': 'subs (subscribed communities), saved or '
                                                                                'upvoted'}), *LIST],
        'epilog': ['Lists of the Reddit account the Aside browser is logged in to (the account check names it). saved '
                   'and upvoted hold posts and comments, newest saved or upvoted first.', PAGE, ACCOUNT],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10),
    },
    'post': {
        'help': 'Read one post in full and the first batch of its comments.',
        'run': _command(thread.post),
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'A post URL, id or redd.it link; a comment link opens the '
                                                               'post at that comment; a share link (/r/<sub>/s/...) '
                                                               'is resolved first'}),
                      (('--sort',), {'choices': web.COMMENT_SORTS, 'help': 'Comment order: best (default), top, new, '
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
                   'cost: the account check (/api/me.json) + 1 request (a share link adds 1 per redirect, at most 3).'],
        'exits': (0, 2, 3, 4, 5, 6, 8, 9, 10),
    },
    'comments': {
        'help': 'Read the next batch of a thread, or one comment in full with what hangs under it.',
        'run': _command(thread.comments),
        'arguments': [(('target',), {'metavar': 'URL', 'help': 'A post URL (its next batch), or a comment\'s permalink '
                                                               '(that comment, always, with its ancestors as context '
                                                               'and what hangs under it)'}),
                      (('--sort',), {'choices': web.COMMENT_SORTS, 'help': 'Comment order (default best); a reading '
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
                   'cost: the account check (/api/me.json) + 1 request per expansion (or 1 for a new read); the time limit '
                   'stops a large thread and more: continues.'],
        'exits': (0, 2, 3, 4, 5, 6, 7, 8, 9, 10),
    },
}

# The closed sets the commands offer (cli.py checks its parser's choices against this).
CHOICES = {
    'feed.sort': list(web.FEED_SORTS), 'feed.time': list(web.TIMES),
    'sub.sort': list(web.SUB_SORTS), 'sub.time': list(web.TIMES),
    'profile.type': list(web.PROFILE_TYPES), 'profile.sort': list(web.PROFILE_SORTS), 'profile.time': list(web.TIMES),
    'search.type': list(web.SEARCH_TYPES), 'search.sort': list(web.SEARCH_SORTS), 'search.time': list(web.TIMES),
    'me.collection': list(web.ME_COLLECTIONS),
    'post.sort': list(web.COMMENT_SORTS), 'comments.sort': list(web.COMMENT_SORTS),
}

TREE = SimpleNamespace(create=thread.create, ingest=thread.ingest, order=thread.order, select=thread.select,
                       waiting=thread.waiting, plan=thread.plan, merge=thread.merge, coverage=thread.coverage)
