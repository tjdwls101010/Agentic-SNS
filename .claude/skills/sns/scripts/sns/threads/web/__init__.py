"""System: the Threads web app (www.threads.com) — target rules, requests from the dedicated tab, response meaning,
records in the skill's terms. The interface of the platform's features and tests; nothing reaches past it."""
from sns.threads.web import classify, learn, snippets, targets
from sns.threads.web.client import ACTIVITY_FILTERS, QUERIES, START, Client
from sns.threads.web.records import (SCHEMAS, SURFACES, Page, PostPage, connection_page, new_counts, notifications_page,
                                     post_page, post_record, profile_card, reply_batch, user_record)

parse_user, parse_post, shortcode_id = targets.parse_user, targets.parse_post, targets.shortcode_id
route_allowed, locate = targets.route_allowed, targets.locate
ROUTE_SOURCE, ORIGIN = targets.ROUTE_SOURCE, targets.ORIGIN
classify_response, classify_document, follow_redirect = classify.response, classify.document, classify.redirect
classify_signal, SIGNAL_MARKERS = classify.signal, classify.SIGNAL_MARKERS
snippet, SNIPPET_NAMES = snippets.snippet, snippets.NAMES
learn_successor, provider_values = learn.successor, learn.provider_values

__all__ = ['ACTIVITY_FILTERS', 'ORIGIN', 'QUERIES', 'ROUTE_SOURCE', 'SCHEMAS', 'SIGNAL_MARKERS', 'SNIPPET_NAMES',
           'START', 'SURFACES',
           'Client', 'Page', 'PostPage', 'classify_document', 'classify_response', 'classify_signal',
           'connection_page', 'follow_redirect', 'learn_successor', 'locate', 'new_counts', 'notifications_page',
           'parse_post', 'parse_user',
           'post_page', 'post_record', 'profile_card', 'provider_values', 'reply_batch', 'route_allowed',
           'shortcode_id', 'snippet', 'user_record']
