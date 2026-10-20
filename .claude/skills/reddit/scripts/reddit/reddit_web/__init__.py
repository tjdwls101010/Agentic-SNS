"""System: www.reddit.com's .json endpoints (a format Reddit owns). Results leave here in the skill's terms.

Its interface: the Client that makes requests, the request builders (routes), target parsing, and the pure
conversions a caller or a test may use on their own — classify (an answer to a body or an error), the record builders
and the comment-tree reader.
"""
from reddit.reddit_web import routes
from reddit.reddit_web.classify import classify
from reddit.reddit_web.client import Client
from reddit.reddit_web.records.comments import comment
from reddit.reddit_web.records.entities import community, moderator, rule, user, wiki_index, wiki_page
from reddit.reddit_web.records.lists import page
from reddit.reddit_web.records.posts import post
from reddit.reddit_web.records.tree import expansion, thread
from reddit.reddit_web.routes import (COMMENT_SORTS, FEED_SORTS, ME_COLLECTIONS, PROFILE_SORTS, PROFILE_TYPES,
                                      SEARCH_SORTS, SEARCH_TYPES, SUB_SORTS, TIMES)
from reddit.reddit_web.targets import Target, parse_target, permalink, require

__all__ = ['Client', 'Target', 'classify', 'comment', 'community', 'expansion', 'moderator', 'page', 'parse_target',
           'permalink', 'post', 'require', 'routes', 'rule', 'thread', 'user', 'wiki_index', 'wiki_page', 'COMMENT_SORTS', 'FEED_SORTS', 'ME_COLLECTIONS',
           'PROFILE_SORTS', 'PROFILE_TYPES', 'SEARCH_SORTS', 'SEARCH_TYPES', 'SUB_SORTS', 'TIMES']
