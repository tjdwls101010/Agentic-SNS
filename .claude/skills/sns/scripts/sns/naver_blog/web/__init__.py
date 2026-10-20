"""System: Naver Blog on the web (m.blog, section.blog, the comment box, blog.naver.com, naver.me, pstatic photos) —
target rules, the read-only request ledger, response meaning, and records in the skill's terms."""
from sns.naver_blog.web import routes, targets
from sns.naver_blog.web import body, records
from sns.naver_blog.web.classify import at, classify
from sns.naver_blog.web.client import Client, policy
from sns.naver_blog.web.pages import Fetched, Policy, numbered

Target = targets.Target
parse_target, short_destination, locate = targets.parse, targets.destination, targets.locate
allowed, build_request, encoded, frame_blog_id = routes.allowed, routes.build, routes.encoded, routes.frame_blog_id
ROUTES, OPERATIONS = routes.ROUTES, routes.OPERATIONS

Post, Comment, Blog, Category, Buddy, Topic = (records.Post, records.Comment, records.Blog, records.Category,
                                               records.Buddy, records.Topic)
Clip, Keyword, Group, Resolved, Saved = records.Clip, records.Keyword, records.Group, records.Resolved, records.Saved
post_record, comment_record, thread_comments, comment_counts = (records.post_record, records.comment_record,
                                                                records.thread_comments, records.comment_counts)
blog_record, categories = records.blog_record, records.categories
buddy_record, topics = records.buddy_record, records.topics
clip_record, keyword_records, group_record = records.clip_record, records.keyword_records, records.group_record
clean, stamp, UNKNOWN, record_schema, RECORD_NOTES = (records.clean, records.stamp, records.UNKNOWN,
                                                      records.record_schema, records.NOTES)
parse_post, link_of, PostDoc = body.parse, body.link_of, body.PostDoc
POST_READ_NOTES = body.NOTES

__all__ = ['Blog', 'Buddy', 'Category', 'Client', 'Clip', 'Comment', 'Fetched', 'Group', 'OPERATIONS', 'Policy', 'Post',
           'PostDoc', 'POST_READ_NOTES', 'RECORD_NOTES', 'ROUTES', 'Resolved', 'Saved', 'Target', 'Topic', 'UNKNOWN',
           'allowed', 'at', 'blog_record', 'build_request', 'buddy_record', 'categories', 'classify', 'clean',
           'clip_record', 'comment_counts', 'comment_record', 'encoded', 'frame_blog_id', 'group_record',
           'keyword_records', 'link_of', 'locate', 'numbered', 'parse_post', 'parse_target', 'policy', 'post_record',
           'record_schema', 'short_destination', 'stamp', 'thread_comments', 'topics']
