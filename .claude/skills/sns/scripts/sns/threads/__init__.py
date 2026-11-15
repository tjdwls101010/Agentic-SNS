"""threads: the platform adapter and public feature interface."""

from sns import reading
from sns.limits import LimitPolicy
from sns.threads import about, images, listing, search, thread, web
from sns.threads.render import render
from sns.window import WindowPolicy

PLATFORM = reading.Platform(
    key='threads', title='Threads', site='threads.com', transport='tab',
    # Threads announces no limit windows: a 429 holds the account for 30 minutes; a checkpoint needs a person
    policy=LimitPolicy(scope='account', hold_seconds=1800, person=('checkpoint',), pace=(1.0, 2.0)),
    window=WindowPolicy(unit_key='unit'), connect=web.Client, render=render,
    schemas={**web.SCHEMAS, 'image': reading.IMAGE_SCHEMA},
    locate=web.locate, unblock_scope=None, idle_action='blank')


from sns.threads.about import about as about_about
from sns.threads.images import images as images_images
from sns.threads.listing import activity as listing_activity
from sns.threads.listing import feed as listing_feed
from sns.threads.listing import graph as listing_graph
from sns.threads.listing import me as listing_me
from sns.threads.listing import notifications as listing_notifications
from sns.threads.listing import profile as listing_profile
from sns.threads.search import search as search_search
from sns.threads.thread import post as thread_post
from sns.threads.thread import replies as thread_replies
from sns.threads.web import ACTIVITY_FILTERS as web_ACTIVITY_FILTERS
