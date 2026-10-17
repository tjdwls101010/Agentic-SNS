"""System: the Threads web app (www.threads.com) — target rules, requests from the dedicated tab, response meaning,
records in the skill's terms."""
from threads.threads_web import classify, targets
from threads.threads_web.client import Client, snippet
from threads.threads_web.records import (SCHEMAS, SURFACES, Page, PostPage, connection_page, new_counts, post_page,
                                         post_record, profile_card, reply_batch, user_record)

parse_user, parse_post, shortcode_id, route_allowed = targets.parse_user, targets.parse_post, targets.shortcode_id, \
    targets.route_allowed
classify_response, classify_document, follow_redirect = classify.response, classify.document, classify.redirect
classify_signal, SIGNAL_MARKERS = classify.signal, classify.SIGNAL_MARKERS

__all__ = ['SCHEMAS', 'SIGNAL_MARKERS', 'SURFACES', 'Client', 'classify_signal', 'snippet', 'Page', 'PostPage', 'classify_document', 'connection_page', 'post_page', 'post_record',
           'profile_card', 'user_record', 'new_counts', 'reply_batch', 'classify_response', 'follow_redirect', 'parse_post', 'parse_user',
           'route_allowed', 'shortcode_id']
