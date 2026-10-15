"""System: Facebook's web client — URL forms, requests from the dedicated tab, response meaning, records."""
from facebook.graphql import targets
from facebook.graphql.client import FEED_SORTS, GROUP_SORTS, Client
from facebook.graphql.records import SCHEMAS, Page, permalink_post, posts_page

normalize_profile, normalize_group, normalize_post, is_group_url = targets.profile, targets.group, targets.post, targets.is_group

__all__ = ['Client', 'FEED_SORTS', 'GROUP_SORTS', 'Page', 'SCHEMAS', 'is_group_url', 'normalize_group',
           'normalize_post', 'normalize_profile', 'permalink_post', 'posts_page']
