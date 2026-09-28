"""Every Threads operation this reader uses, declared once.

A declaration is what stays true when Meta rotates an operation: where the app loads it, the variables it takes, where
its connection and items sit in the response, how it pages, and whether its order is by writing time. What rotates —
the operation's name, doc_id and feature flags — lives in registry.json and the cache override, keyed by `id`.
"""
from dataclasses import dataclass, field



class _Required:
    """A variable the caller must supply; one object that copying keeps, so a template copy can still be checked."""

    def __repr__(self):
        return 'REQUIRED'

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


REQUIRED = _Required()

RELAY = 'relay'                 # after=<end_cursor> until has_next_page is false
OFFSET = 'offset'               # the cursor is a numeric offset
CAPPED = 'capped'               # one server-chosen sample; the reported total is larger
SINGLE_BATCH = 'single_batch'   # one batch, no server continuation
SSR_ONLY = 'ssr_only'           # read from the route's own rendered payloads, never queried


@dataclass(frozen=True)
class Signature:
    """How a route's preloader for this operation looks, flags aside: `required` <= its variable names <= `required`
    plus `optional`, and each of `values` pinned: 'profile' is the one userID the route's preloaders share, 'query' the
    route's own q parameter."""
    required: frozenset
    optional: frozenset = frozenset()
    values: tuple = ()

    def fits(self, variables, profile=None, query=None):
        keys = {key for key in variables if not key.startswith('__relay_internal__')}
        if not self.required <= keys <= self.required | self.optional:
            return False
        pinned = {'profile': profile, 'query': query}
        return all(pinned[kind] is not None and str(variables.get(key)) == str(pinned[kind]) for key, kind in self.values)


@dataclass(frozen=True)
class Operation:
    id: str
    legacy_names: tuple        # Meta names it has had; a cache override written before the catalogue is keyed by them
    discovery: str             # route: a preloader of `route`; capture: seen only in an app tab; ssr: never queried
    route: str | None = None   # the GET route whose render loads it, with {viewer} for the viewer's own handle
    variables: dict = field(default_factory=dict)
    connection: str | None = None   # dotted path from data to the connection
    items: str | None = None        # dotted path from an edge node to its thread items; None when the node is a user
    pagination: str = RELAY
    ssr_shape: str | None = None    # the data key that marks this operation's server-rendered result
    identity: str | None = None     # dotted path from data to the object whose pk must equal the userID variable
    chronological: bool = False     # newest first by writing time, so passing a window's start ends the read
    signature: Signature | None = None  # route operations only: how a renamed preloader is recognised
    role: str | None = None             # what a replay must show: 'authored' posts by the profile, 'reposted' shares


def _tab(name, legacy, route, chronological, role='authored', first=25, **variables):
    signature = Signature(frozenset({'userID', 'first', *variables}), frozenset({'after'}), (('userID', 'profile'),))
    return Operation(name, (legacy,), 'route', route, {'userID': REQUIRED, 'first': first, **variables, 'after': None},
                     'mediaData', 'thread_items', RELAY, 'mediaData', chronological=chronological,
                     signature=signature, role=role)


OPERATIONS = {op.id: op for op in [
    # A feed is read only as its route renders it (/ for you, /following): Threads refuses the feed queries, first
    # page and pagination alike, from outside its own app tab (2026-09-28).
    Operation('feed', ('BarcelonaFeedDirectQuery',), 'ssr', connection='feedData',
              items='text_post_app_thread.thread_items', pagination=SSR_ONLY, ssr_shape='feedData'),
    Operation('profile.page', ('BarcelonaProfilePageDirectQuery',), 'route', '/@{viewer}',
              {'userID': REQUIRED, 'canSeeFeedsTab': True, 'showLinkedIGStats': False},
              ssr_shape='user', identity='user', pagination=SINGLE_BATCH,
              signature=Signature(frozenset({'userID', 'canSeeFeedsTab', 'showLinkedIGStats'}),
                                  values=(('userID', 'profile'),))),
    # Threads refuses this tab's query above ten posts a page (an execution error, as if rotated).
    _tab('profile.threads', 'BarcelonaProfileThreadsTabDirectQuery', '/@{viewer}', True, first=10,
         allow_page_info_for_lox_user=False),
    _tab('profile.replies', 'BarcelonaProfileRepliesTabDirectQuery', '/@{viewer}/replies', True),
    _tab('profile.reposts', 'BarcelonaProfileRepostsTabDirectQuery', '/@{viewer}/reposts', False, role='reposted'),
    _tab('profile.media', 'BarcelonaProfileMediaTabDirectQuery', '/@{viewer}/media', False),
    Operation('search.posts', ('BarcelonaSearchResultsQuery',), 'route', '/search?q=a&serp_type=default',
              {'query': REQUIRED, 'search_surface': REQUIRED, 'recent': REQUIRED, 'tagID': None, 'meta_place_id': None,
               'power_search_info': None, 'trend_fbid': None, 'after': None},
              'searchResults', 'thread.thread_items', RELAY, 'searchResults',
              signature=Signature(frozenset({'query', 'search_surface', 'recent'}),
                                  frozenset({'tagID', 'meta_place_id', 'power_search_info', 'trend_fbid', 'after'}),
                                  (('query', 'query'),))),
    Operation('post.target', ('BarcelonaPostPageStrongIdTargetQuery',), 'ssr', pagination=SSR_ONLY),
    Operation('post.downward', ('BarcelonaPostPageStrongIdDownwardQuery',), 'ssr', pagination=SSR_ONLY),
    Operation('post.upward', ('BarcelonaPostPageStrongIdUpwardQuery',), 'ssr', pagination=SSR_ONLY),
    Operation('search.accounts', ('useBarcelonaAccountSearchGraphQLDataSourceQuery',), 'capture',
              variables={'query': REQUIRED, 'first': 10, 'should_fetch_friendship_status': False,
                         'should_fetch_fediverse_profiles': True, 'should_fetch_ig_inactive_on_text_app': None,
                         'should_fetch_tag_and_mention_restrictions': False, 'hide_unconnected_private': False,
                         'is_internal_user': False},
              connection='xdt_api__v1__users__search_connection', pagination=SINGLE_BATCH),
    Operation('graph.followers', ('BarcelonaFriendshipsFollowersTabQuery',), 'capture',
              variables={'userID': REQUIRED, 'first': 20}, connection='user.followers', pagination=CAPPED),
    Operation('graph.following', ('BarcelonaFriendshipsFollowingTabQuery',), 'capture',
              variables={'userID': REQUIRED, 'first': 20}, connection='user.following', pagination=OFFSET),
    Operation('graph.following_more', ('BarcelonaFriendshipsFollowingTabRefetchableQuery',), 'capture',
              variables={'id': REQUIRED, 'first': 10, 'after': REQUIRED}, connection='fetch__XDTUserDict.following',
              pagination=OFFSET),
    Operation('me.liked', ('BarcelonaLikedPageViewerQuery',), 'capture',
              connection='xdt_text_app_viewer.liked_media', items='thread_items', pagination=SINGLE_BATCH),
    Operation('me.saved', ('BarcelonaSavedPageViewerQuery',), 'capture',
              connection='xdt_text_app_viewer.saved_media', items='thread_items', pagination=SINGLE_BATCH),
]}


def by_legacy_name(name):
    return next((op for op in OPERATIONS.values() if name in op.legacy_names), None)
