"""System: the Facebook web app (facebook.com) — URL forms, requests from the dedicated tab, response meaning, records in
the skill's terms. The interface of the platform's features and tests; nothing reaches past it."""
from sns.facebook.web import classify, snippets, targets
from sns.facebook.web.client import (COMMENT_SORTS, FEED_SORTS, GROUP_SORTS, HOME, OPEN_RESERVE, QUERIES, READ_NAMES,
                                     ROUTE_RESERVE, Client)
from sns.facebook.web.records import (SCHEMAS, Batch, about_collections, about_fields, comments_page, group_about,
                                      group_card, notifications_page, permalink_post, posts_page, replies_page,
                                      search_page)

normalize_profile, normalize_group, normalize_post = targets.profile, targets.group, targets.post
is_group_url, find_id, about_path, locate = targets.is_group, targets.find_id, targets.about_path, targets.locate
classify_response, classify_location = classify.response, classify.location
snippet, SNIPPET_NAMES = snippets.snippet, snippets.NAMES

__all__ = ['COMMENT_SORTS', 'FEED_SORTS', 'GROUP_SORTS', 'HOME', 'OPEN_RESERVE', 'QUERIES', 'READ_NAMES',
           'ROUTE_RESERVE', 'SCHEMAS', 'SNIPPET_NAMES', 'Batch', 'Client', 'about_collections', 'about_fields',
           'about_path', 'classify_location', 'classify_response', 'comments_page', 'find_id', 'group_about',
           'group_card', 'is_group_url', 'locate', 'normalize_group', 'normalize_post', 'normalize_profile',
           'notifications_page', 'permalink_post', 'posts_page', 'replies_page', 'search_page', 'snippet']
