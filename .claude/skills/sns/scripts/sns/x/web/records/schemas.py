"""What each record field means, for `schema post`, `schema account` and `schema trend`."""

NULL = 'null when X did not report it, which is not 0'

POST = {
    'object': 'post',
    'description': 'A post, reply, parent, quoted or reposted post. A tombstone keeps only id (when known), unavailable '
                   'and unavailable_reason.',
    'fields': {
        'kind': 'string — post',
        'id': 'string — X\'s post id; post <id> opens it',
        'url': 'string|null — the post\'s own URL (a repost row: the original\'s); post <url> opens exactly that post; '
               'a tombstone with a known id has the generic /i/web/status/<id> URL',
        'created_at': 'string|null — when it was written, UTC ISO; a repost row\'s is when it was reposted',
        'text': 'string — the whole text X sent, t.co links expanded and media links removed; a long post\'s full text; '
                'a repost row\'s is empty (the words are the original\'s, in reposted_post)',
        'lang': 'string|null — X\'s guess of the text\'s language',
        'author': 'object|null — who acted, as an account record: for a repost row the reposter, not the writer',
        'reply_count, repost_count, quote_count, like_count, bookmark_count, view_count':
            'integer|null — as X reports them, ' + NULL + '; a repost row has none of its own (see reposted_post)',
        'media': 'array<{n, kind, image_url, video_url, width, height, alt, media_id}> — n counts this post\'s '
                 'pictures and videos from 1 in X\'s order (a quoted post\'s are numbered in its own record); kind '
                 'photo, video or gif; image_url the picture (a video\'s poster); video_url the largest MP4 of a video '
                 'or GIF, null for a photo; alt the description the author (or X) wrote; media_id X\'s id for the item',
        'links': 'array<string> — link destinations in the text',
        'mentions': 'array<string> — handles mentioned, without @, in order, each once',
        'hashtags': 'array<string>',
        'is_long_post': 'boolean — X sent the full text of a long post (not a clipped preview)',
        'is_reply': 'boolean — it answers another post',
        'parent_id': 'string|null — the post it answers',
        'reply_to_author': 'string|null — the handle of that post\'s author, as X names it',
        'root_post_id': 'string|null — the first post of the conversation it belongs to',
        'quoted_post': 'object|null — the post it quotes, a record of its own: two voices, the quoter\'s words and '
                       'the quoted author\'s; unavailable when that post is gone',
        'quoted_post_id': 'string|null — the quoted post\'s id even when X left out its body (post <id> opens it)',
        'reposted_post': 'object|null — the post a repost row shares: its words, media, counts and original time',
        'community_note': 'object|null — a community note shown under the post {id, title, text, url}: context other '
                          'users added and rated helpful, not the author\'s words; no note does not mean the post '
                          'was checked',
        'card': 'object|null — a card: {kind, title, description, domain, url} for a link preview (url the '
                'destination), {kind, poll: {choices: [{label, count}], final, ends_at}} for a poll (poll fields '
                'follow X\'s known card keys and were not seen live when this skill was built), {kind, space_url} '
                'for a space',
        'article': 'object|null — an X article: {id, title, preview, text}; text is the whole article in a post read '
                   '(null in lists, where X sends the title and preview only)',
        'edit': 'object|null — the post was edited: {versions (ids, oldest first), latest (whether this is the newest)}; '
                'post <id> opens any version',
        'limited_actions': 'array<string> — actions X restricts on this post (Reply, Retweet, …)',
        'restricted': 'boolean — X shows the post with limited visibility',
        'community': 'object|null — {id, name} of the community it was posted in',
        'pinned': 'boolean — pinned to the author\'s profile, so it sits first whatever its date',
        'unavailable': 'boolean — a tombstone: deleted, withheld or not visible to this account',
        'role': 'string — in a post read: parent (above the post), post, or reply',
        'depth': 'integer — a reply\'s place in its conversation thread: 0 answers the post, later ones sit under it',
        'parent_shown': 'boolean — replies: whether the post it answers was shown (X can skip posts in a thread)',
        'replies_handle': 'integer — replies <handle> reads what hangs under this reply',
        'unit': 'string — lists: the timeline entry or module it came in (a self-thread shares one)',
        'community_url': 'string|null — lists of a community search: the link of the community a post came from',
        'unavailable_reason': 'string|null — a tombstone: why, in X\'s words, when X says',
    },
}

ACCOUNT = {
    'object': 'account',
    'description': 'An account, as an author, a search result, a follower or a profile card.',
    'fields': {
        'kind': 'string — account',
        'id': 'string — X\'s account id; the handle can change, this does not',
        'username': 'string — the handle, without @',
        'full_name': 'string|null — the display name the account chose',
        'created_at': 'string|null — when the account was made, UTC ISO',
        'follower_count, following_count, post_count, media_count, like_count': 'integer|null — ' + NULL,
        'is_blue_verified': 'boolean — the blue check: a paid X subscription, not an identity check',
        'verified_type': 'string|null — Business or Government: an organisation badge X grants, unlike the paid check',
        'is_verified': 'boolean — X\'s separate verified flag',
        'declared_label': 'string|null — a label the account declared about itself: Parody, Commentary or Fan',
        'affiliation': 'object|null — {label, url}: the organisation X shows next to the name',
        'private': 'boolean — protected: only approved followers see its posts',
        'bio': 'string|null — what the account wrote about itself, links expanded',
        'location, website': 'string|null — as the account wrote them',
        'url': 'string|null — the profile URL (null for an unavailable account)',
        'avatar_url, banner_url': 'string|null',
        'relationship': 'object — the logged-in account\'s relation to this one: {following, followed_by, blocking, '
                        'muting, follow_request_sent}; null when X did not say',
        'pinned_post_ids': 'array<string> — the pinned post',
        'unavailable': 'boolean — suspended, deactivated or not visible (unavailable_reason says which, when X does)',
        'unavailable_reason': 'string|null — why, in X\'s words, when X says',
        'unit': 'string — lists: the timeline entry or module it came in (what a --since window groups by)',
    },
}

TREND = {
    'object': 'trend',
    'description': 'A trend or an event on X\'s Explore tabs: what X shows this account as popular now, not a measure.',
    'fields': {
        'kind': 'string — trend or event',
        'id': 'string — X\'s entry id for it on that tab',
        'created_at': 'null — a trend has no date',
        'name': 'string — the trend\'s words, or the event\'s title',
        'context': 'string|null — X\'s label (topic, place, "Trending")',
        'description': 'string|null — X\'s line under it (often a post count, rounded)',
        'rank': 'integer|null — its place on the tab',
        'query': 'string|null — the words search takes to read it (search "<query>"); an event\'s is its title',
        'url': 'string|null — an https link X gave for it (usually none: X links trends and events inside its app)',
        'unit': 'string — lists: the timeline entry or module it came in (what a --since window groups by)',
    },
}

LIST = {
    'object': 'list',
    'description': 'An X list: a set of accounts someone curated, with its own feed of their posts.',
    'fields': {
        'kind': 'string — list',
        'id': 'string — the list id (list <id> reads it)',
        'name': 'string|null',
        'description': 'string|null',
        'private': 'boolean|null — a private list is seen only by its owner',
        'member_count': 'integer|null — ' + NULL,
        'follower_count': 'integer|null — accounts following the list; ' + NULL,
        'created_at': 'string|null — UTC ISO',
        'owner': 'object|null — {id, username, name} of the account that made it',
        'you_follow': 'boolean|null — this account follows the list',
        'you_are_member': 'boolean|null — this account is one of its members',
        'url': 'string — x.com/i/lists/<id>',
        'unit': 'string — lists: the timeline entry or module it came in (what a --since window groups by)',
    },
}

COMMUNITY = {
    'object': 'community',
    'description': 'An X community: a group with its own feed, members, moderators and rules.',
    'fields': {
        'kind': 'string — community',
        'id': 'string — the community id (community <id> reads it)',
        'name': 'string|null',
        'description': 'string|null',
        'member_count': 'integer|null — ' + NULL,
        'moderator_count': 'integer|null — ' + NULL,
        'created_at': 'string|null — UTC ISO',
        'open_to_join': 'boolean|null — false: joining needs a moderator\'s approval',
        'join_policy': 'string|null — X\'s own value',
        'nsfw': 'boolean|null',
        'your_role': 'string|null — this account\'s place: not a member, member, moderator or admin',
        'topic': 'string|null — the topic X files it under',
        'rules': 'array — the rules\' titles',
        'creator': 'object|null — {id, username, name}',
        'url': 'string — x.com/i/communities/<id>',
        'unit': 'string — lists: the timeline entry or module it came in (what a --since window groups by)',
    },
}

SPACE = {
    'object': 'space',
    'description': 'An X space: a live audio room, possibly kept as a replay.',
    'fields': {
        'kind': 'string — space',
        'id': 'string',
        'title': 'string|null',
        'state': 'string|null — live, scheduled, ended or canceled (X\'s own value, lowercased, when it is another)',
        'created_at': 'string|null — UTC ISO',
        'scheduled_start': 'string|null — UTC ISO',
        'started_at': 'string|null — UTC ISO',
        'ended_at': 'string|null — UTC ISO',
        'host': 'object|null — {id, username, name} of the account that made it',
        'admins': 'array — usernames of its hosts',
        'speakers': 'array — usernames of those who spoke',
        'participant_count': 'integer|null — ' + NULL,
        'live_listener_count': 'integer|null — listening while live; ' + NULL,
        'replay_view_count': 'integer|null — ' + NULL,
        'replay_available': 'boolean|null',
        'url': 'string — x.com/i/spaces/<id>',
    },
}

NOTIFICATION = {
    'object': 'notification',
    'description': 'One of this account\'s notifications, as X words it. Only X\'s suggestions (suggested_by_x) were '
                   'seen live while building the skill; the other event names follow X\'s icons and are unverified.',
    'fields': {
        'kind': 'string — notification',
        'id': 'string',
        'event': 'string|null — like, follow, repost, reply, suggested by X, from X, milestone, security alert, …; X\'s '
                 'own icon name when it is another',
        'suggested_by_x': 'boolean — X recommending something, not anyone\'s act',
        'message': 'string|null — X\'s sentence (names other people)',
        'created_at': 'string|null — UTC ISO',
        'accounts': 'array — usernames of the accounts it is about',
        'post_ids': 'array — the posts it is about (post <id> reads one)',
        'url': 'string|null',
        'unit': 'string — lists: the timeline entry or module it came in (what a --since window groups by)',
    },
}

DOCTOR = {
    'object': 'doctor',
    'description': 'What X adds to doctor\'s results[0] (the fields every platform has are in schema result): the '
                   'dedicated tab, what the tab\'s app defines and whether the skill\'s own requests are told apart '
                   'from the page\'s. doctor opens the tab when none is open (about 15-25 requests the page makes '
                   'itself while it loads, measured; 20 plus what was seen when the start of the load could not be '
                   'measured) and otherwise makes no request.',
    'fields': {
        'tab': 'object — {target_id, opened_now, reopened, opening_measured}: the dedicated x.com tab, whether this '
               'command opened it or opened another because the recorded one was gone or emptied, and whether the '
               'opening cost was measured (the kit was installed before the app ran) or reserved',
        'operations': 'object — each operation the skill reads: the type the tab\'s app defines it as, or "not in the '
                      'tab (stored id used)"',
        'signature_generator': 'boolean — the app\'s request-signing function was found in its modules',
        'bearer': 'boolean — the app\'s bearer token was found (exactly one value, never a guess among several)',
        'own_request_matching': 'string — confirmed when the skill\'s own requests are told apart in the tab\'s timing '
                                'list by the nonce in their URL fragment; not seen yet (an own request may be counted '
                                'twice) when Chrome may drop the fragment; not tried yet before any read',
    },
}

SCHEMAS = {'post': POST, 'account': ACCOUNT, 'trend': TREND, 'list': LIST, 'community': COMMUNITY, 'space': SPACE,
           'notification': NOTIFICATION, 'doctor': DOCTOR}
