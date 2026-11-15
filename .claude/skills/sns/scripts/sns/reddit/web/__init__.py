"""System: www.reddit.com's .json endpoints (a format Reddit owns). Results leave here in the skill's terms.

Its interface: the Client that makes requests (inside the connection's guard), the request builders, target
parsing (`parse_target`, `require`, `locate`), and the pure conversions a caller or a test may use on their own —
`classify` (an answer to a body or a failure), `limit_fact` (rate-limit headers → a limits.Fact), the record builders and
the comment-tree readers.
"""
from sns.reddit.web.classify import classify, outcome
from sns.reddit.web.client import Client
from sns.reddit.web.headers import limit_fact, reset_seconds
from sns.reddit.web.records import (comment, community, media_items, moderator, page, post, reply, rule, user,
                                    wiki_index, wiki_page)
from sns.reddit.web.routes import (BATCH, COMMENT_SORTS, FEED_SORTS, ME_COLLECTIONS, PROFILE_SORTS, PROFILE_TYPES,
                                   SEARCH_SORTS, SEARCH_TYPES, SUB_SORTS, TIMES, bucket_of, community as route_community,
                                   feed as route_feed, listing as route_listing, me as route_me, mine as route_mine,
                                   morechildren as route_morechildren, post as route_post, profile as route_profile,
                                   related as route_related, rules as route_rules, search as route_search,
                                   share as route_share, subtree as route_subtree, user as route_user,
                                   wiki_page as route_wiki_page)
from sns.reddit.web.targets import ACCEPTS, Target, locate, parse_target, permalink, require
from sns.reddit.web.tree import expansion, thread

__all__ = ['BATCH', 'bucket_of', 'route_feed', 'route_listing', 'route_post', 'route_morechildren', 'route_subtree',
           'route_profile', 'route_search', 'route_related', 'route_mine', 'route_community', 'route_rules', 'route_user',
           'route_me', 'route_share', 'route_wiki_page', 'ACCEPTS', 'Client', 'COMMENT_SORTS', 'FEED_SORTS',
           'ME_COLLECTIONS', 'PROFILE_SORTS', 'PROFILE_TYPES',
           'SEARCH_SORTS', 'SEARCH_TYPES', 'SUB_SORTS', 'TIMES', 'Target', 'classify', 'comment', 'community',
           'expansion', 'limit_fact', 'locate', 'media_items', 'moderator', 'outcome', 'page', 'parse_target',
           'permalink', 'post', 'reply', 'require', 'reset_seconds', 'rule', 'thread', 'user', 'wiki_index',
           'wiki_page']
