"""System: the X web app (x.com) — target rules, requests from the dedicated tab, response meaning, records in the
skill's terms."""
from twitter.x_web import classify, targets
from twitter.x_web.records import account_record, list_page, post_page, post_record, walk

parse_account, parse_post, parse_list = targets.parse_account, targets.parse_post, targets.parse_list
parse_community, parse_space = targets.parse_community, targets.parse_space

classify_response, classify_signal, bucket_of = classify.response, classify.signal, classify.bucket_of

__all__ = ['account_record', 'list_page', 'post_page', 'post_record', 'walk', 'bucket_of', 'classify_response', 'classify_signal', 'parse_account', 'parse_community', 'parse_list', 'parse_post', 'parse_space']
