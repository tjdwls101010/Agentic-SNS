"""facebook: the platform adapter and public feature interface."""

from sns import reading
from sns.facebook import about, images, listing, notifications, screens, search, thread, web
from sns.facebook.render import render
from sns.limits import LimitPolicy
from sns.window import WindowPolicy

PLATFORM = reading.Platform(
    secret_fields=('fb_dtsg', 'lsd', 'jazoest', 'datr', 'sb', 'c_user', 'xs', 'csrftoken', 'ds_user_id', 'mid', 'x-csrftoken', 'x-fb-lsd', '__hs', '__hsi', '__dyn', '__csr', '__spin_t', '__s', '__aaid', '__hsdp', '__hblp', '__sjsp', '__crn',),
    signed_image_hosts=('fbcdn.net', 'cdninstagram.com',),
    key='facebook', title='Facebook', site='facebook.com', transport='tab',
    # Facebook announces no limit: a 429 on any of the tab's requests holds the account for 30 minutes; a checkpoint
    # is the one block only a person clears
    policy=LimitPolicy(scope='account', hold_seconds=1800, person=('checkpoint',), pace=(1.0, 2.0)),
    window=WindowPolicy(), connect=web.Client, render=render, schemas={**web.SCHEMAS, 'image': reading.IMAGE_SCHEMA}, locate=web.locate,
    unblock_scope=None, idle_action='blank')   # window.close() does not take on Facebook's tab (measured): empty it


from sns.facebook.about import about as about_about
from sns.facebook.images import images as images_images
from sns.facebook.listing import feed as listing_feed
from sns.facebook.screens import graph as screens_graph
from sns.facebook.screens import group as screens_group
from sns.facebook.screens import me as screens_me
from sns.facebook.screens import profile as screens_profile
from sns.facebook.search import search as search_search
from sns.facebook.thread import comments as thread_comments
from sns.facebook.thread import post as thread_post
from sns.facebook.thread import replies as thread_replies
