"""System: www.reddit.com's .json endpoints (a format Reddit owns). Results leave here in the skill's terms.

Its interface: the Client that makes requests (inside the connection's guard), the request builders (`routes`), target
parsing (`parse_target`, `require`, `locate`), and the pure conversions a caller or a test may use on their own —
`classify` (an answer to a body or a failure), `limit_fact` (rate-limit headers → a limits.Fact), the record builders and
the comment-tree readers.
"""
from sns.reddit.web import routes
from sns.reddit.web.classify import classify, outcome
from sns.reddit.web.client import Client
from sns.reddit.web.headers import limit_fact, reset_seconds
from sns.reddit.web.records import (comment, community, media_items, moderator, page, post, rule, user, wiki_index,
                                    wiki_page)
from sns.reddit.web.routes import (COMMENT_SORTS, FEED_SORTS, ME_COLLECTIONS, PROFILE_SORTS, PROFILE_TYPES,
                                   SEARCH_SORTS, SEARCH_TYPES, SUB_SORTS, TIMES)
from sns.reddit.web.targets import ACCEPTS, Target, locate, parse_target, permalink, require
from sns.reddit.web.tree import expansion, thread

__all__ = ['ACCEPTS', 'Client', 'COMMENT_SORTS', 'FEED_SORTS', 'ME_COLLECTIONS', 'PROFILE_SORTS', 'PROFILE_TYPES',
           'SEARCH_SORTS', 'SEARCH_TYPES', 'SUB_SORTS', 'TIMES', 'Target', 'classify', 'comment', 'community',
           'expansion', 'limit_fact', 'locate', 'media_items', 'moderator', 'outcome', 'page', 'parse_target',
           'permalink', 'post', 'require', 'reset_seconds', 'routes', 'rule', 'thread', 'user', 'wiki_index',
           'wiki_page']
