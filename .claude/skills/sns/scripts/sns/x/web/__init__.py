"""System: the X web app (x.com) — target rules, requests from the dedicated tab, response meaning, records in the
skill's terms. The interface of the platform's features and tests; nothing reaches past it."""
from sns.x.web import classify, snippets, targets
from sns.x.web.client import OPERATIONS, READ_OPERATIONS, START, Client
from sns.x.web.records import (SCHEMAS, account_record, community_record, list_page, list_record, missing_community,
                               missing_list, missing_space, notification_record, post_page, post_record, space_record,
                               walk)

parse_account, parse_post, parse_list = targets.parse_account, targets.parse_post, targets.parse_list
parse_community, parse_space = targets.parse_community, targets.parse_space

classify_response, classify_signal, bucket_of, fact = classify.response, classify.signal, classify.bucket_of, classify.fact
locate = targets.locate
snippet, SNIPPET_NAMES = snippets.snippet, snippets.NAMES

__all__ = ['OPERATIONS', 'READ_OPERATIONS', 'SCHEMAS', 'SNIPPET_NAMES', 'START', 'Client', 'account_record',
           'bucket_of', 'classify_response', 'classify_signal', 'community_record', 'fact', 'list_page', 'list_record',
           'missing_community', 'missing_list', 'missing_space', 'notification_record', 'parse_account',
           'parse_community', 'parse_list', 'parse_post', 'parse_space', 'post_page', 'post_record', 'snippet',
           'space_record', 'walk', 'locate']
