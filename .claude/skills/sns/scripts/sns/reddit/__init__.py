"""reddit: the platform adapter and public feature interface."""
from types import SimpleNamespace

from sns import reading
from sns.limits import LimitPolicy
from sns.window import WindowPolicy

from sns.reddit import about, images, listing, render, search, thread, web, wiki
from sns.reddit.snapshots import Snapshots

POLICY = LimitPolicy(scope='bucket', slow='used', hold_seconds=600, person=('challenge',), pace=(1.0, 2.0),
                     unmetered=('share',))  # a share link is paced and holdable but Reddit reports no window for it


def connect(connection):
    """The client of one invocation; doctor also reports what the comment threads take on disk."""
    return web.Client(connection, extra=lambda: {
        'snapshot_bytes': Snapshots(connection.account, connection.deadline).size(),
        'holds_personal_data_here': 'reddit/<account>/snapshots/ in the state directory — comment threads with other people\'s words; '
                                    'they expire after a day on their own'})


RECORDS = {
    'post': {'object': 'post', 'description': 'A post ([p] label).', 'fields': {
        'kind, id, url, created_at': 'string — kind post; the Reddit fullname t3_<id> (a comment with the same base id, '
                                     't1_, is a different thing); the post\'s permalink (post <url> opens it in full '
                                     'with its comments); UTC ISO-8601 or null',
        'title, text': 'string — as received (text is the body of a text post; [removed] or [deleted] when gone)',
        'subreddit': 'string — the community',
        'author': 'object — {name, id, url}; id and url are null when unknown, name is [deleted] when unknown',
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
    'reply': {'object': 'reply', 'description': 'Something another account sent this one: a reply to its comment, a reply '
              'to its post, or a mention of its name ([r] label; me comment-replies, post-replies, mentions).',
              'fields': {
        'kind, id, url, created_at': 'string — kind reply; the replying comment\'s fullname t1_<id>; its permalink with '
                                     'context (comments <url> opens it with what surrounds it); UTC ISO-8601 or null',
        'type': 'string — comment_reply, post_reply or username_mention, as Reddit names it',
        'author': 'object — {name, id, url}; id and url are null when unknown, name is [deleted] when unknown',
        'subreddit': 'string — where the reply was posted', 'post_title': 'string — the post the reply sits under',
        'parent_id': 'string — the fullname it answers', 'text': 'string — the reply as received',
        'unread': 'boolean — still unread in the account\'s inbox; reading it here does not mark it read'}},
    'comment': {'object': 'comment', 'description': 'A comment ([c] label).', 'fields': {
        'kind, id, url, created_at': 'string — kind comment; the Reddit fullname t1_<id>; the comment\'s permalink '
                                     '(comments <url> opens it in full with what hangs under it); UTC ISO-8601 or '
                                     'null',
        'parent_id': 'string — the fullname it answers (t1_ a comment, t3_ the post)', 'post_id': 'string — t3_<id>',
        'text': 'string — as received; > lines quote someone else ([removed] or [deleted] when gone)',
        'author': 'object — {name, id, url}; id and url are null when unknown, name is [deleted] when unknown',
        'subreddit': 'string', 'edited_at': 'string|null — UTC ISO-8601',
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
    secret_fields=('reddit_session', 'token_v2', 'loid', 'session_tracker', 'csrf_token', 'modhash', 'x-modhash', 'edgebucket',),
    signed_image_hosts=('redd.it',),
    key='reddit', title='Reddit', site='reddit.com', transport='fetch', policy=POLICY,
    window=WindowPolicy(jitter=600), connect=connect, render=render.render,
    schemas={**RECORDS, 'image': reading.IMAGE_SCHEMA}, locate=web.locate,
    unblock_scope='general', idle_action=None)

TREE = SimpleNamespace(create=thread.create, ingest=thread.ingest, order=thread.order, select=thread.select,
                       waiting=thread.waiting, plan=thread.plan, merge=thread.merge, coverage=thread.coverage)

from sns.reddit.about import about as about_about
from sns.reddit.images import images as images_images
from sns.reddit.listing import feed as listing_feed
from sns.reddit.listing import me as listing_me
from sns.reddit.listing import profile as listing_profile
from sns.reddit.listing import related as listing_related
from sns.reddit.listing import sub as listing_sub
from sns.reddit.listing import window_check as listing_window_check
from sns.reddit.search import search as search_search
from sns.reddit.thread import comments as thread_comments
from sns.reddit.thread import post as thread_post
from sns.reddit.web import COMMENT_SORTS as web_COMMENT_SORTS
from sns.reddit.web import FEED_SORTS as web_FEED_SORTS
from sns.reddit.web import ME_COLLECTIONS as web_ME_COLLECTIONS
from sns.reddit.web import PROFILE_SORTS as web_PROFILE_SORTS
from sns.reddit.web import PROFILE_TYPES as web_PROFILE_TYPES
from sns.reddit.web import SEARCH_SORTS as web_SEARCH_SORTS
from sns.reddit.web import SEARCH_TYPES as web_SEARCH_TYPES
from sns.reddit.web import SUB_SORTS as web_SUB_SORTS
from sns.reddit.web import TIMES as web_TIMES
from sns.reddit.wiki import wiki as wiki_wiki
