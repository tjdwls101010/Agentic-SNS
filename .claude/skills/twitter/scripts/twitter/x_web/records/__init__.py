"""X responses as the skill's records: accounts, posts, list pages, post pages."""
from twitter.x_web.records.posts import account_record, post_record
from twitter.x_web.records.thread import PostPage, post_page
from twitter.x_web.records.timeline import ListPage, list_page, walk

__all__ = ['ListPage', 'PostPage', 'account_record', 'list_page', 'post_page', 'post_record', 'walk']
