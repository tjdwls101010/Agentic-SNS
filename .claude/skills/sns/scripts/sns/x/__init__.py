"""x: the platform adapter and public feature interface."""

from sns import reading
from sns.limits import LimitPolicy
from sns.window import WindowPolicy
from sns.x import about, explore, images, listing, search, thread, web
from sns.x.render import render

PLATFORM = reading.Platform(
    secret_fields=('ct0', 'auth_token', 'twid', 'x-csrf-token', 'x-client-transaction-id', 'guest_id', 'kdt', 'att',),
    signed_image_hosts=('pbs.twimg.com',),
    key='x', title='X', site='x.com', transport='tab',
    # X's windows are per operation (15 minutes), slowed below 20% left; a 429 without a reset waits one window
    policy=LimitPolicy(scope='operation', slow='fraction', slow_fraction=0.2, hold_seconds=900,
                       person=('challenge', 'account_locked'), pace=(1.0, 2.0)),
    window=WindowPolicy(unit_key='unit'), connect=web.Client, render=render,
    schemas={**web.SCHEMAS, 'image': reading.IMAGE_SCHEMA},
    locate=web.locate, unblock_scope='Viewer', idle_action='close')


from sns.x.about import about as about_about
from sns.x.explore import TABS as explore_TABS
from sns.x.explore import trends as explore_trends
from sns.x.images import images as images_images
from sns.x.listing import community as listing_community
from sns.x.listing import feed as listing_feed
from sns.x.listing import graph as listing_graph
from sns.x.listing import lists as listing_lists
from sns.x.listing import me as listing_me
from sns.x.listing import profile as listing_profile
from sns.x.listing import reposts as listing_reposts
from sns.x.search import quotes as search_quotes
from sns.x.search import search as search_search
from sns.x.thread import post as thread_post
from sns.x.thread import replies as thread_replies
