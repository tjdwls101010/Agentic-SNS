"""naver_blog: the platform adapter and public feature interface."""

from sns import reading
from sns.clock import KST
from sns.limits import LimitPolicy
from sns.window import WindowPolicy

from sns.naver_blog import blog, directory, images, neighbors, post, render, search, web

# Naver publishes no limit and sends no rate-limit headers: a 429 holds the account (30 minutes when it names no time),
# and current-user's network block is a person block. Requests are paced 0.5-0.8 s apart.
POLICY = LimitPolicy(scope='account', hold_seconds=1800, person=('network_blocked',), pace=(0.5, 0.8))

RECORDS = {
    'post': web.record_schema('post', web.Post, web.RECORD_NOTES['post']),
    'post_read': web.record_schema('post_read', web.PostDoc, web.POST_READ_NOTES, skip=('viewer_id',)),
    **{name: web.record_schema(name, cls, web.RECORD_NOTES[name]) for name, cls in (
        ('comment', web.Comment), ('blog', web.Blog), ('category', web.Category), ('buddy', web.Buddy),
        ('topic', web.Topic), ('clip', web.Clip), ('keyword', web.Keyword), ('group', web.Group),
        ('link', web.Resolved))},
    'image': reading.IMAGE_SCHEMA,
}
RECORDS['post_read']['fields']['author'] = 'object — ' + web.POST_READ_NOTES['author']


def connect(connection):
    """The client of one invocation."""
    return web.Client(connection)


PLATFORM = reading.Platform(
    secret_fields=('nid_aut', 'nid_ses', 'nid_jkl', 'nid_inf', 'nnb', 'userkey', 'bauserkey', 'useridno', 'idno', 'naverid',),
    signed_image_hosts=('pstatic.net',),
    key='naver_blog', title='Naver Blog', site='blog.naver.com', transport='fetch', policy=POLICY,
    window=WindowPolicy(tz=KST), connect=connect, render=render.render, schemas=RECORDS, locate=web.locate,
    unblock_scope=None, idle_action=None)


from sns.naver_blog.blog import blog as blog_blog
from sns.naver_blog.blog import check as blog_check
from sns.naver_blog.blog import posts as blog_posts
from sns.naver_blog.directory import check as directory_check
from sns.naver_blog.directory import check_monthly as directory_check_monthly
from sns.naver_blog.directory import monthly as directory_monthly
from sns.naver_blog.directory import topic as directory_topic
from sns.naver_blog.images import images as images_images
from sns.naver_blog.neighbors import buddies as neighbors_buddies
from sns.naver_blog.neighbors import check as neighbors_check
from sns.naver_blog.neighbors import feed as neighbors_feed
from sns.naver_blog.post import comments as post_comments
from sns.naver_blog.post import post as post_post
from sns.naver_blog.post import resolve as post_resolve
from sns.naver_blog.search import check as search_check
from sns.naver_blog.search import keywords as search_keywords
from sns.naver_blog.search import search as search_search
