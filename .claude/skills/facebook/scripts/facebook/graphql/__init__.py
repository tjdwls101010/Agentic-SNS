"""System: Facebook's web client — URL forms, requests from the dedicated tab, response meaning, records."""
from facebook.graphql import classify, targets
from facebook.graphql.client import COMMENT_SORTS, FEED_SORTS, GROUP_SORTS, Client
from facebook.graphql.records import SCHEMAS, about_collections, about_fields, group_card, Page, comments_page, permalink_post, posts_page, replies_page, search_page

normalize_profile, normalize_group, normalize_post, is_group_url = targets.profile, targets.group, targets.post, targets.is_group
find_id = targets.find_id
classify_response, classify_location = classify.response, classify.location

__all__ = ['classify_location', 'classify_response', 'find_id', 'COMMENT_SORTS', 'Client', 'FEED_SORTS', 'GROUP_SORTS', 'Page', 'SCHEMAS', 'is_group_url', 'normalize_group',
           'normalize_post', 'normalize_profile', 'permalink_post', 'posts_page', 'comments_page', 'replies_page', 'search_page', 'about_collections', 'about_fields', 'group_card']
